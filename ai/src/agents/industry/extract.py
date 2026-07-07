"""Step 3 — graph extraction: LLM triples + the structured ownership backbone.

Turns the Step 1 corpus into reviewable (source, relation, target) triples:

* **LLM** — each company's '사업의 내용' text is chunked and run through a custom
  extractor: ``get_chat_llm().with_structured_output(Extraction)`` with a Korean
  schema prompt (see :data:`SYSTEM_PROMPT`). Rolling our own — instead of
  ``LLMGraphTransformer`` — is what lets us reliably elicit the sparse
  ``BELONGS_TO`` (Industry) and ``BENEFITS_FROM`` (Policy) relations that Q1/Q5
  need, while keeping tight anti-noise rules.
* **Structured backbone** — ``holdings.csv`` (타법인출자) and the controlling
  rows of ``major_shareholders.csv`` become precise ``OWNS_STAKE`` edges with no
  LLM, so ownership is exact.

Every entity name passes through :func:`normalize.normalize_name` (the #1 risk)
so LLM and CSV triples share one node identity. Output goes to
``data/extracted/`` for human review **before** Neo4j ingestion (Step 4):

* ``triples.csv``          — source, source_type, relation, target, target_type, origin
* ``nodes.csv``            — distinct normalized nodes + type + degree (spot duplicates)
* ``graph_documents.json`` — normalized nodes + relationships for Step 4 MERGE

Run:
    uv run python -m src.agents.industry.extract --company 247540   # smoke
    uv run python -m src.agents.industry.extract --limit 2
    uv run python -m src.agents.industry.extract                    # all 10
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
import pandas as pd
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from .companies import COMPANIES, Company, by_stock_code
from .config import EXTRACTED_DIR, RAW_DIR, STRUCTURED_DIR, get_chat_llm
from .normalize import is_self_reference, normalize_name
from .schema import NodeType, REL_SHAPES, RelType

CHUNK_SIZE = 2500
CHUNK_OVERLAP = 200

# Evidence verification: each LLM-quoted `evidence` must actually appear in the
# filer's source text, or it's dropped (a fabricated citation is worse than none).
# 90 tolerates minor 조사/구두점/whitespace drift on an otherwise-verbatim quote.
VERIFY_THRESHOLD = 90

# --- Custom extraction schema (fixed graph schema, CLAUDE.md) ----------------
# NodeType/RelType are the fixed schema, defined once in schema.py so ingestion
# (Step 4) and the Cypher chain (Step 5) share the same source of truth.


class Relation(BaseModel):
    """One extracted (source)-[relation]->(target) edge."""

    source: str = Field(description="관계 출발 엔티티 이름 (법인 접사 제외)")
    source_type: NodeType = Field(description="출발 엔티티 타입")
    relation: RelType = Field(description="관계 유형")
    target: str = Field(description="관계 도착 엔티티 이름 (법인 접사 제외)")
    target_type: NodeType = Field(description="도착 엔티티 타입")
    evidence: str = Field(
        default="",
        description="이 관계를 직접 뒷받침하는 원문 문장 또는 절을 그대로 인용",
    )


class Extraction(BaseModel):
    """All relations found in one text chunk."""

    relations: list[Relation] = Field(default_factory=list)


SYSTEM_PROMPT = """\
너는 한국 기업 사업보고서에서 지식그래프용 (엔티티, 관계) 삼중항을 추출하는 엔진이다.
아래 스키마에 **정확히** 맞는 관계만 뽑아라.

[노드 타입]
- Company(기업/법인), Industry(산업/밸류체인), Product(제품/소재), Policy(정책/규제/법), Person(인물)

[관계 타입과 방향 — source -> target]
- SUPPLIES: 공급사 -> 고객사. 원재료·소재·부품·제품을 판매/납품하는 경우만. (예: 양극재사 -> 셀제조사)
- COMPETES_WITH: 경쟁하는 두 기업 (Company-Company).
- OWNS_STAKE: 지분 보유사 -> 피출자사 (Company-Company).
- BELONGS_TO: 기업 -> 산업/밸류체인 (Company-Industry). (예: 어떤 기업 -> 이차전지 양극재 산업)
- BENEFITS_FROM: 기업 -> 정책 (Company-Policy). 정부 정책/규제/보조금의 수혜.
  (예: IRA, 배터리 소재 국산화 정책, ESS 설치 의무화, 친환경차 보조금)

[반드시 지킬 규칙]
1. 본문에 명시적으로 서술된 관계만 추출한다. 추측·상식 보완 금지.
2. 국가·지역·도시·주소, 공장·항만·광산 등 설비, 부서·본부·팀·담당·CIC 등 내부 조직,
   직책, 은행·증권·펀드 등 금융기관은 **노드로 만들지 마라**.
3. SUPPLIES 방향을 반드시 지켜라(납품하는 쪽이 source). 금융·용역·임대 거래는 제외.
4. 회사명은 한국어 정식 명칭으로 쓰고 법인 접사(㈜, 주식회사, Co.,Ltd. 등)는 뺀다.
5. 산업 소속(BELONGS_TO)과 정책 수혜(BENEFITS_FROM)가 본문에 나오면 빠뜨리지 말고 꼭 넣어라.
6. 각 관계마다 evidence에는 그 관계를 직접 뒷받침하는 본문 문장 또는 절을 원문 그대로 인용하라.
   요약하거나 새로 쓰지 말고, 관계가 드러나는 가장 짧은 표현을 선택하라.

[예시]
입력: "당사는 삼성SDI와 SK온에 하이니켈 양극재를 공급하며, 에코프로머티리얼즈로부터 전구체를 매입한다.
당사는 이차전지 양극재 산업에 속하고, 미국 IRA와 배터리 소재 국산화 정책의 수혜가 기대된다."
(이 문서 회사 = 에코프로비엠)
출력 relations:
- 에코프로비엠 / Company / SUPPLIES / 삼성SDI / Company / evidence: "당사는 삼성SDI와 SK온에 하이니켈 양극재를 공급"
- 에코프로비엠 / Company / SUPPLIES / SK온 / Company / evidence: "당사는 삼성SDI와 SK온에 하이니켈 양극재를 공급"
- 에코프로머티리얼즈 / Company / SUPPLIES / 에코프로비엠 / Company / evidence: "에코프로머티리얼즈로부터 전구체를 매입한다"
- 에코프로비엠 / Company / BELONGS_TO / 이차전지 양극재 산업 / Industry / evidence: "당사는 이차전지 양극재 산업에 속하고"
- 에코프로비엠 / Company / BENEFITS_FROM / IRA / Policy / evidence: "미국 IRA와 배터리 소재 국산화 정책의 수혜가 기대된다"
- 에코프로비엠 / Company / BENEFITS_FROM / 배터리 소재 국산화 정책 / Policy / evidence: "미국 IRA와 배터리 소재 국산화 정책의 수혜가 기대된다"

관계가 없으면 빈 목록을 반환하라."""

HUMAN_TEMPLATE = (
    "이 문서는 '{filer}'의 사업보고서 '사업의 내용' 섹션 일부다. "
    "'당사'·'회사'·'지배기업'은 모두 '{filer}'를 가리킨다.\n\n"
    "---\n{text}\n---"
)


@dataclass
class Triple:
    source: str
    source_type: str
    relation: str
    target: str
    target_type: str
    origins: set[str] = field(default_factory=set)
    evidences: set[str] = field(default_factory=set)
    qota_rt: str = ""  # OWNS_STAKE 지분율(%), backbone edges only


def _select_companies(company: str | None, limit: int | None) -> list[Company]:
    if company:
        picked = [c for c in COMPANIES if c.stock_code == company or c.canonical == company]
        if not picked:
            raise SystemExit(f"unknown company: {company}")
        return picked
    return COMPANIES[:limit] if limit else COMPANIES


def load_chunks(companies: list[Company]) -> list[Document]:
    """Load each company's business text and split into overlapping chunks.

    Each chunk carries ``metadata['origin']`` = stock_code for edge provenance.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    docs: list[Document] = []
    for c in companies:
        text_path = RAW_DIR / c.stock_code / "business_content.txt"
        if not text_path.exists():
            print(f"  [skip] {c.canonical}: no business_content.txt")
            continue
        text = text_path.read_text(encoding="utf-8")
        for chunk in splitter.split_text(text):
            docs.append(Document(page_content=chunk, metadata={"origin": c.stock_code}))
    return docs


def build_extractor():
    """LLM constrained to the Extraction schema (function calling, <think> off)."""
    # 8192 so entity-dense chunks don't truncate mid-toolcall (seen with 4096).
    llm = get_chat_llm(temperature=0, max_tokens=8192)
    return llm.with_structured_output(Extraction)


RAW_CACHE = "raw_llm.json"


def run_llm(docs: list[Document], extractor) -> list[dict]:
    """Extract chunk-by-chunk and return RAW (unnormalized) records.

    Raw records are cached to ``raw_llm.json`` so normalization/junk filters can
    be re-tuned via ``--from-cache`` without re-hitting the (slow) LLM — the core
    Step 3 review loop.
    """
    raw: list[dict] = []
    total = len(docs)
    for i, doc in enumerate(docs, 1):
        origin = doc.metadata.get("origin", "")
        filer = by_stock_code(origin)
        filer_name = filer.canonical if filer else "이 회사"
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=HUMAN_TEMPLATE.format(filer=filer_name, text=doc.page_content)),
        ]
        try:
            result = extractor.invoke(messages)
        except Exception as exc:  # one bad chunk shouldn't abort the run
            print(f"  [chunk {i}/{total}] FAILED ({origin}): {exc}")
            continue
        rels = result.relations if result else []
        for r in rels:
            raw.append({
                "source": r.source, "source_type": r.source_type,
                "type": r.relation,
                "target": r.target, "target_type": r.target_type,
                "evidence": r.evidence.strip(),
                "origin": origin,
            })
        print(f"  [chunk {i}/{total}] {origin}: {len(rels)} rels")
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    (EXTRACTED_DIR / RAW_CACHE).write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  cached {len(raw)} raw LLM rels -> {RAW_CACHE}")
    return raw


def load_raw_cache() -> list[dict]:
    path = EXTRACTED_DIR / RAW_CACHE
    if not path.exists():
        raise SystemExit(f"no cache at {path}; run once without --from-cache first")
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_ws(text: str) -> str:
    """Collapse every whitespace run to a single space.

    The LLM quote and the source may differ only in newlines/indentation (chunking,
    PDF-to-text), so both sides are normalized the same way before comparison.
    """
    return " ".join(str(text or "").split())


_SOURCE_NORM_CACHE: dict[str, str] = {}


def _load_source_norm(origin: str) -> str:
    """Whitespace-normalized full source text for a filer (stock_code), cached per origin.

    Verifying against the *whole* filing (not the originating chunk) makes the check
    independent of CHUNK_SIZE and immune to quotes that straddle a chunk boundary.
    Empty string (missing file) means every evidence for this origin fails to verify.
    """
    if origin not in _SOURCE_NORM_CACHE:
        path = RAW_DIR / origin / "business_content.txt"
        if path.exists():
            _SOURCE_NORM_CACHE[origin] = _norm_ws(path.read_text(encoding="utf-8"))
        else:
            print(f"  [verify] no source text for {origin}; its evidence cannot be verified")
            _SOURCE_NORM_CACHE[origin] = ""
    return _SOURCE_NORM_CACHE[origin]


_ELLIPSIS_RE = re.compile(r"\.\.\.+|…")


def _match_score(span: str, source_norm: str) -> int:
    """Verbatim -> 100, else best-window fuzzy ratio (tolerates 조사/구두점 drift)."""
    if span in source_norm:
        return 100
    return int(round(fuzz.partial_ratio(span, source_norm)))


def verify_evidence(evidence: str, source_norm: str) -> tuple[bool, int]:
    """Does ``evidence`` actually occur in the source? Exact substring -> (True, 100).

    The LLM often stitches two non-contiguous — but individually verbatim — spans with
    an ellipsis (``A ... B``). Scoring the whole string then penalizes the gap and drops
    a genuinely grounded quote, so ellipsis-joined quotes are verified **per fragment**
    and scored by their weakest fragment. A single span (or a summarized/fabricated
    quote) is scored whole; both are rejected below :data:`VERIFY_THRESHOLD`.
    """
    ev = _norm_ws(evidence)
    if not ev or not source_norm:
        return False, 0
    fragments = [f for f in (_norm_ws(p) for p in _ELLIPSIS_RE.split(ev)) if len(f) >= 8]
    if len(fragments) > 1:
        worst = min(_match_score(f, source_norm) for f in fragments)
        return worst >= VERIFY_THRESHOLD, worst
    score = _match_score(ev, source_norm)
    return score >= VERIFY_THRESHOLD, score


def raw_to_triples(raw: list[dict]) -> list[Triple]:
    """Normalize raw LLM records -> Triples (self-reference + alias + junk filter).

    Each LLM-quoted ``evidence`` is verified against the filer's source text; only
    verified quotes survive onto the Triple (a fabricated citation is worse than none).
    Rejected quotes are logged to ``evidence_rejected.csv`` for review.
    """
    triples: list[Triple] = []
    skipped_bad_shape = 0
    verified = 0
    rejects: list[dict] = []
    for r in raw:
        origin = r.get("origin", "")
        filer = by_stock_code(origin)
        filer_name = filer.canonical if filer else ""

        def _resolve(name: str, typ: str) -> str:
            # "당사"/"지배기업" etc. are the filer talking about itself.
            if typ == "Company" and filer_name and is_self_reference(name):
                return filer_name
            return normalize_name(name, typ)

        src = _resolve(r["source"], r["source_type"])
        tgt = _resolve(r["target"], r["target_type"])
        if not src or not tgt or src == tgt:
            continue
        shape = (r["source_type"], r["type"], r["target_type"])
        if shape not in REL_SHAPES:
            skipped_bad_shape += 1
            continue
        evidence = str(r.get("evidence", "")).strip()
        kept_evidence: set[str] = set()
        if evidence:
            ok, score = verify_evidence(evidence, _load_source_norm(origin))
            if ok:
                kept_evidence = {evidence}
                verified += 1
            else:
                rejects.append({
                    "source": src, "relation": r["type"], "target": tgt,
                    "origin": origin, "score": score, "evidence": evidence,
                })
        triples.append(
            Triple(
                src, r["source_type"], r["type"], tgt, r["target_type"],
                {origin}, kept_evidence,
            )
        )
    if skipped_bad_shape:
        print(f"  [filter] skipped {skipped_bad_shape} relation(s) with invalid schema shape")
    _write_evidence_rejects(rejects)
    total_with_evidence = verified + len(rejects)
    print(f"  [verify] kept {verified}/{total_with_evidence} evidence quotes "
          f"(rejected {len(rejects)} not found in source)")
    return triples


def _write_evidence_rejects(rejects: list[dict]) -> None:
    """Log dropped (unverified) evidence quotes for human review."""
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    path = EXTRACTED_DIR / "evidence_rejected.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "relation", "target", "origin", "score", "evidence"])
        for r in sorted(rejects, key=lambda x: x["score"]):
            w.writerow([r["source"], r["relation"], r["target"],
                        r["origin"], r["score"], r["evidence"]])


def _clean_rt(val: object) -> str:
    s = str(val).strip()
    return "" if s in {"", "-", "nan"} else s


def extract_ownstake_triples(include_shareholders: bool = True) -> list[Triple]:
    """Build exact OWNS_STAKE triples from the structured CSV backbone."""
    triples: list[Triple] = []

    holdings_path = STRUCTURED_DIR / "holdings.csv"
    if holdings_path.exists():
        df = pd.read_csv(holdings_path, encoding="utf-8-sig", dtype=str).fillna("")
        for _, row in df.iterrows():
            # 'corp_name' is the filer (== query_canonical); the invested company
            # (the OWNS_STAKE target) is 'inv_prm'.
            src = normalize_name(row["query_canonical"], "Company")
            tgt = normalize_name(row["inv_prm"], "Company")
            if not src or not tgt or src == tgt:
                continue
            triples.append(
                Triple(src, "Company", "OWNS_STAKE", tgt, "Company",
                       {row["query_stock_code"]}, set(),
                       _clean_rt(row.get("trmend_blce_qota_rt")))
            )
    else:
        print(f"  [warn] no {holdings_path.name}")

    if include_shareholders:
        sh_path = STRUCTURED_DIR / "major_shareholders.csv"
        if sh_path.exists():
            df = pd.read_csv(sh_path, encoding="utf-8-sig", dtype=str).fillna("")
            # Only the controlling shareholder (relate contains 본인): a clean
            # Company->Company edge; drops 임원/친인척/특수관계인 noise.
            df = df[df["relate"].str.contains("본인", na=False)]
            for _, row in df.iterrows():
                src = normalize_name(row["nm"], "Company")
                tgt = normalize_name(row["query_canonical"], "Company")
                if not src or not tgt or src == tgt:
                    continue
                triples.append(
                    Triple(src, "Company", "OWNS_STAKE", tgt, "Company",
                           {row["query_stock_code"]}, set(),
                           _clean_rt(row.get("trmend_posesn_stock_qota_rt")))
                )
        else:
            print(f"  [warn] no {sh_path.name}")

    return triples


# Symmetric relations: A-REL-B and B-REL-A are the same edge.
SYMMETRIC_RELATIONS = {"COMPETES_WITH"}


def merge_triples(triples: list[Triple]) -> list[Triple]:
    """Dedupe on (source, relation, target); union origins, keep first 지분율.

    Symmetric relations (COMPETES_WITH) are order-normalized so both directions
    collapse to one edge.
    """
    merged: dict[tuple[str, str, str], Triple] = {}
    for t in triples:
        if t.relation in SYMMETRIC_RELATIONS and t.source > t.target:
            t = Triple(t.target, t.target_type, t.relation, t.source, t.source_type,
                       set(t.origins), set(t.evidences), t.qota_rt)
        key = (t.source, t.relation, t.target)
        if key in merged:
            merged[key].origins |= t.origins
            merged[key].evidences |= t.evidences
            if not merged[key].qota_rt and t.qota_rt:
                merged[key].qota_rt = t.qota_rt
        else:
            merged[key] = Triple(t.source, t.source_type, t.relation, t.target,
                                 t.target_type, set(t.origins), set(t.evidences), t.qota_rt)
    return list(merged.values())


def write_outputs(triples: list[Triple]) -> None:
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    # triples.csv — the human-review file
    triples_sorted = sorted(triples, key=lambda t: (t.relation, t.source, t.target))
    with (EXTRACTED_DIR / "triples.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "source", "source_type", "relation", "target", "target_type",
            "qota_rt", "origins", "evidences",
        ])
        for t in triples_sorted:
            w.writerow([t.source, t.source_type, t.relation, t.target, t.target_type,
                        t.qota_rt, "|".join(sorted(t.origins)),
                        "|".join(sorted(t.evidences))])

    # nodes.csv — distinct nodes + type + degree (spot duplicate/variant nodes)
    node_type: dict[str, str] = {}
    degree: dict[str, int] = defaultdict(int)
    for t in triples:
        node_type.setdefault(t.source, t.source_type)
        node_type.setdefault(t.target, t.target_type)
        degree[t.source] += 1
        degree[t.target] += 1
    with (EXTRACTED_DIR / "nodes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node", "type", "degree"])
        for name in sorted(degree, key=lambda n: (-degree[n], n)):
            w.writerow([name, node_type[name], degree[name]])

    # graph_documents.json — normalized nodes + relationships for Step 4 MERGE
    graph = {
        "nodes": [{"id": n, "type": node_type[n]} for n in sorted(node_type)],
        "relationships": [
            {
                "source": t.source, "source_type": t.source_type,
                "type": t.relation,
                "target": t.target, "target_type": t.target_type,
                "properties": ({"qota_rt": t.qota_rt} if t.qota_rt else {}),
                "origins": sorted(t.origins),
                "evidences": sorted(t.evidences),
            }
            for t in triples_sorted
        ],
    }
    (EXTRACTED_DIR / "graph_documents.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rel_counts: dict[str, int] = defaultdict(int)
    nonempty_evidences = 0
    for t in triples:
        rel_counts[t.relation] += 1
        if t.evidences:
            nonempty_evidences += 1
    print(f"\nWrote {len(triples)} triples, {len(node_type)} nodes -> {EXTRACTED_DIR}")
    print("  by relation: " + ", ".join(f"{k}={v}" for k, v in sorted(rel_counts.items())))
    print(f"  triples w/ verified evidence: {nonempty_evidences}/{len(triples)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 3: extract graph triples from DART filings.")
    parser.add_argument("--company", help="single company by stock code or canonical name (smoke test)")
    parser.add_argument("--limit", type=int, help="only the first N companies")
    parser.add_argument("--skip-llm", action="store_true", help="structured OWNS_STAKE backbone only")
    parser.add_argument("--from-cache", action="store_true",
                        help="re-normalize from raw_llm.json (no LLM) — fast filter-tuning loop")
    parser.add_argument("--no-shareholders", action="store_true", help="skip major_shareholders.csv")
    args = parser.parse_args()

    companies = _select_companies(args.company, args.limit)
    print(f"Companies: {', '.join(c.canonical for c in companies)}")

    all_triples: list[Triple] = []

    if args.from_cache:
        raw = load_raw_cache()
        print(f"Re-normalizing {len(raw)} cached raw LLM rels ...")
        all_triples += raw_to_triples(raw)
    elif not args.skip_llm:
        docs = load_chunks(companies)
        print(f"Loaded {len(docs)} chunks; extracting with LLM ...")
        extractor = build_extractor()
        all_triples += raw_to_triples(run_llm(docs, extractor))

    # OWNS_STAKE backbone is company-wide (not per-selection) unless a single
    # company is requested, in which case filter to its provenance.
    print("Extracting OWNS_STAKE backbone from structured CSVs ...")
    backbone = extract_ownstake_triples(include_shareholders=not args.no_shareholders)
    if args.company or args.limit:
        codes = {c.stock_code for c in companies}
        backbone = [t for t in backbone if t.origins & codes]
    all_triples += backbone

    merged = merge_triples(all_triples)
    write_outputs(merged)


if __name__ == "__main__":
    main()
