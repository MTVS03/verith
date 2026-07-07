"""Step 5 — retrieval pipeline: answer Korean questions over the Neo4j graph.

Three composable stages, each its own function so they can be tuned/tested in
isolation (this is how part 1, translation, was built and verified):

    question -> generate_cypher -> Cypher -> graph.query -> rows -> generate_answer -> 한국어 답변

We compose these ourselves rather than using ``GraphCypherQAChain`` so our tuned
Cypher prompt stays the source of truth and each stage stays transparent.

Cypher accuracy is risk #2 (CLAUDE.md), so the generation prompt carries the
live graph schema plus few-shot examples written with *real* entity names and
the five benchmark archetypes (competitor lookup, competitor ∩ policy-benefit,
2-hop supply chain, high-degree hub, multi-hop path). COMPETES_WITH is stored in
a single direction, so competitor examples match it undirected + DISTINCT to
catch the edge regardless of which way it was written.

The answer stage's #1 risk is hallucination: the model padding answers about
these *real* companies from prior knowledge. The QA prompt forces strict
grounding — answer only from the returned rows, and say so plainly when empty.

Run:
    uv run python -m src.agents.industry.retrieve "삼성SDI와 경쟁하는 기업은?"
    uv run python -m src.agents.industry.retrieve --show-cypher "..."   # + Cypher & rows
    uv run python -m src.agents.industry.retrieve --cypher-only "..."   # translation only
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse

from .config import RAW_DIR, get_chat_llm, get_neo4j_graph
from .faithfulness import check_faithfulness
from .schema import CYPHER_SCHEMA

# Cap rows fed into the answer prompt so a broad query (e.g. "수혜 없는 기업" =>
# hundreds of rows) can't blow the context window. The count is still reported.
MAX_CONTEXT_ROWS = 50

# The prompt injects {schema} (fixed public graph schema) and {question}. Few-shot
# examples use real node names from the loaded graph and cover the benchmark
# archetypes so the model has a direction-correct pattern for each.
CYPHER_GENERATION_TEMPLATE = """\
너는 Neo4j 지식그래프에 질문하기 위한 Cypher 질의문을 작성하는 전문가다.
아래 스키마와 규칙, 예시를 참고해 질문에 답할 **Cypher 질의문 하나만** 출력하라.

[스키마]
{schema}

[규칙]
1. 스키마에 있는 노드 라벨과 관계 타입만 사용한다. 없는 것을 지어내지 마라.
2. 관계 방향을 지켜라: (공급사)-[:SUPPLIES]->(고객사), (지분보유사)-[:OWNS_STAKE]->(피출자사),
   (기업)-[:BELONGS_TO]->(산업), (기업)-[:BENEFITS_FROM]->(정책).
   COMPETES_WITH는 방향이 한쪽으로만 저장돼 있으니, 저장 방향과 무관하게 잡히도록
   방향 없이 매칭하고 DISTINCT로 중복을 없애라.
3. 회사 이름은 정식 명칭으로 매칭한다. 반면 산업(Industry)·정책(Policy) 이름은 노드에 짧은
   키워드로 저장돼 있어 질문의 긴 표현과 정확히 일치하지 않는다. 이 둘은 **핵심 키워드 하나만
   뽑아 CONTAINS로 매칭**하라. (예: 질문 "이차전지 양극재 산업" -> i.name CONTAINS '양극재',
   질문 "배터리 소재 국산화 정책" -> p.name CONTAINS '국산화')
4. 지분율은 OWNS_STAKE **관계**의 속성 `qota_rt`이며 **퍼센트 숫자**로 저장돼 있다
   (예: 41.0 = 41%). 노드 속성이 아니다. "지분율 50% 이상"은 `r.qota_rt >= 50`으로 쓴다.
5. 답변 근거를 위해 관계는 변수로 바인딩하고, 가능하면 `evidence_edges` 컬럼에
   `{{source, relation, target, evidences, origins}}` 맵 목록을 함께 반환한다.
6. 설명·주석·마크다운 코드펜스 없이 Cypher 질의문만 출력한다.

[예시]
# 특정 기업의 경쟁사 (단순 관계)
질문: 삼성SDI와 경쟁하는 기업은?
Cypher: MATCH (a:Company {{name: '삼성SDI'}})-[r:COMPETES_WITH]-(c:Company)
RETURN DISTINCT c.name AS competitor,
       [{{source: a.name, relation: type(r), target: c.name, evidences: r.evidences, origins: r.origins}}] AS evidence_edges

# 경쟁 관계 ∩ 정책 수혜 (교집합, 2홉)
질문: LG화학과 경쟁하는 기업 중 국산화 정책 수혜를 받는 회사는?
Cypher: MATCH (a:Company {{name: 'LG화학'}})-[r1:COMPETES_WITH]-(c:Company)-[r2:BENEFITS_FROM]->(p:Policy)
WHERE p.name CONTAINS '국산화'
RETURN DISTINCT c.name AS company, p.name AS policy,
       [{{source: a.name, relation: type(r1), target: c.name, evidences: r1.evidences, origins: r1.origins}},
        {{source: c.name, relation: type(r2), target: p.name, evidences: r2.evidences, origins: r2.origins}}] AS evidence_edges

# 간접 공급망 (2홉, 직접 거래처 제외)
질문: SK이노베이션과 직접 거래하진 않지만 1차 협력사를 통해 간접 연결된 부품사는?
Cypher: MATCH (a:Company {{name: 'SK이노베이션'}})<-[r1:SUPPLIES]-(t1:Company)<-[r2:SUPPLIES]-(t2:Company)
WHERE NOT (t2)-[:SUPPLIES]->(a) AND t2 <> a
RETURN DISTINCT t2.name AS second_tier, t1.name AS first_tier,
       [{{source: t1.name, relation: type(r1), target: a.name, evidences: r1.evidences, origins: r1.origins}},
        {{source: t2.name, relation: type(r2), target: t1.name, evidences: r2.evidences, origins: r2.origins}}] AS evidence_edges

# 허브 식별 (고차수 노드)
질문: 여러 기업이 공통으로 의존하는 핵심 공급자는?
Cypher: MATCH (s:Company)-[r:SUPPLIES]->(c:Company)
WITH s, count(DISTINCT c) AS customers
WHERE customers >= 3
RETURN s.name AS supplier, customers ORDER BY customers DESC

# 다홉 파급 경로
질문: LG화학에서 시작하는 공급 경로가 어디까지 이어지나?
Cypher: MATCH path = (a:Company {{name: 'LG화학'}})-[:SUPPLIES*1..3]->(c:Company)
RETURN [n IN nodes(path) | n.name] AS chain,
       [r IN relationships(path) | {{source: startNode(r).name, relation: type(r), target: endNode(r).name, evidences: r.evidences, origins: r.origins}}] AS evidence_edges
LIMIT 25

질문: {question}
Cypher:"""


def _extract_cypher(text: str) -> str:
    """Strip markdown fences / stray prose, leaving the raw Cypher query.

    The model is told to emit only Cypher, but reasoning models occasionally
    wrap it in ```cypher fences; peel those off defensively.
    """
    fenced = re.search(r"```(?:cypher)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def generate_cypher(question: str, *, schema: str, llm=None) -> str:
    """Translate one Korean question into a Cypher query string.

    ``enable_thinking=False`` (via the factory default) keeps the reasoning
    model from spending its budget on ``<think>`` and returns the query
    promptly. Pass a prebuilt ``llm``/``schema`` to reuse across many questions.
    """
    if llm is None:
        llm = get_chat_llm(enable_thinking=False, max_tokens=1024)
    prompt = CYPHER_GENERATION_TEMPLATE.format(schema=schema, question=question)
    response = llm.invoke(prompt)
    return _extract_cypher(response.content)


# --- Answer generation (rows -> Korean) --------------------------------------
# The prompt injects {question} and {context} (the query rows as JSON). Its whole
# job is grounding: answer only from the rows, and refuse to invent when empty.
ANSWER_TEMPLATE = """\
너는 지식그래프 조회 결과를 바탕으로 한국어로 답하는 리서치 어시스턴트다.
아래 '조회 결과'와 '원문 청크'만 근거로 질문에 답하라.

[반드시 지킬 규칙]
1. 조회 결과와 원문 청크에 있는 사실만 사용한다. 없는 내용을 추측하거나 사전지식으로 보완하지 마라.
2. 둘 다 비어 있으면 "그래프에서 해당하는 연결을 찾지 못했다"고 솔직히 답하고 끝낸다.
3. 어느 기업이 어떤 관계·경로로 연결됐는지 간결히 밝힌다.
4. 간결한 한국어로 답한다.
5. [G1], [V1] 같은 인용 표기는 직접 만들지 마라. 시스템이 답변 뒤에 붙인다.

[질문]
{question}

[조회 결과]
{context}

[원문 청크]
{chunks}

[답변]"""


def _strip_evidence(value):
    if isinstance(value, dict):
        return {
            k: _strip_evidence(v)
            for k, v in value.items()
            if k not in {"evidence_edges", "evidences", "origins"}
        }
    if isinstance(value, list):
        return [_strip_evidence(v) for v in value]
    return value


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _edge_label(edge: dict) -> str:
    src = edge.get("source") or "?"
    rel = edge.get("relation") or "?"
    tgt = edge.get("target") or "?"
    return f"{src}-[{rel}]->{tgt}"


def _format_overview_evidence(view: str, record: dict) -> str | None:
    if view == "공급_허브":
        supplier = record.get("supplier")
        deg = record.get("deg")
        if supplier is None or deg is None:
            return None
        return f"공급_허브: {supplier} deg={deg}"
    if view == "경쟁_상위":
        company = record.get("company")
        deg = record.get("deg")
        if company is None or deg is None:
            return None
        return f"경쟁_상위: {company} deg={deg}"
    if view == "산업별_소속":
        industry = record.get("industry")
        n = record.get("n")
        sample = record.get("sample") or []
        if industry is None or n is None:
            return None
        sample_text = ", ".join(map(str, sample)) if isinstance(sample, list) else str(sample)
        return f"산업별_소속: {industry} n={n} sample={sample_text}"
    return None


def _collect_overview_evidence(row: dict) -> list[str]:
    """Render structural-overview aggregate rows as deterministic graph refs."""
    views = ("공급_허브", "경쟁_상위", "산업별_소속")
    if not any(view in row for view in views):
        return []

    records_by_view = {
        view: records
        for view in views
        if isinstance((records := row.get(view)), list)
    }
    refs: list[str] = []
    max_len = max((len(records) for records in records_by_view.values()), default=0)
    for idx in range(max_len):
        for view in views:
            records = records_by_view.get(view, [])
            if idx >= len(records) or not isinstance(records[idx], dict):
                continue
            body = _format_overview_evidence(view, records[idx])
            if body:
                refs.append(body)
    return refs


# --- Source deep links (click a citation -> jump to the exact sentence) -------
# Each filing's DART viewer URL serves the business-content prose directly in the
# page body, so a text-fragment directive (`#:~:text=`) makes the browser scroll
# to and highlight the quoted sentence — no manual Ctrl+F. #1's verbatim
# verification is what guarantees the quote matches the page so the fragment
# resolves (Chromium/Safari; Firefox/table quotes fall back to the section top).

_FILING_META: dict[str, dict] | None = None


def _load_filing_meta() -> dict[str, dict]:
    """{stock_code: {source_url, report_nm}} from each company's meta.json, cached.

    ``source_url``/``report_nm`` are per filing (one per company), so an edge's
    ``origins`` (stock codes) are enough to source it — no chunk match needed.
    """
    global _FILING_META
    if _FILING_META is None:
        meta: dict[str, dict] = {}
        for meta_path in RAW_DIR.glob("*/meta.json"):
            try:
                m = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            code = str(m.get("stock_code") or meta_path.parent.name)
            meta[code] = {
                "source_url": m.get("source_url", ""),
                "report_nm": m.get("report_nm", ""),
            }
        _FILING_META = meta
    return _FILING_META


_SOURCE_NORM: dict[str, str] = {}


def _source_text_norm(code: str) -> str:
    """Whitespace-normalized full filing text for a stock code, cached."""
    if code not in _SOURCE_NORM:
        path = RAW_DIR / code / "business_content.txt"
        _SOURCE_NORM[code] = (
            " ".join(path.read_text(encoding="utf-8").split()) if path.exists() else ""
        )
    return _SOURCE_NORM[code]


def _pick_origin(origins: list, quote: str | None) -> str | None:
    """Origin whose filing actually contains ``quote`` (right doc for the link).

    origins/evidences are unioned independently in the graph, so ``origins[0]`` can
    belong to a different filing than the quote. Match the quote to a filing to keep
    the deep link on the correct company's report; fall back to the first origin.
    """
    if quote and origins:
        probe = " ".join(re.split(r"\.\.\.+|…", quote)[0].split())
        if len(probe) >= 8:
            for code in origins:
                if probe in _source_text_norm(str(code)):
                    return str(code)
    return str(origins[0]) if origins else None


def _chunk_body(text: str) -> str:
    """Verbatim source prose of a chunk, dropping vectorize's ``[회사] 섹션`` header.

    ``vectorize`` prepends a synthetic ``[company] breadcrumb\\n`` line for context;
    that header is not in the DART page, so the deep link must target the body.
    """
    return str(text or "").split("\n", 1)[-1]


def _first_phrase(text: str, max_words: int = 12, max_chars: int = 80) -> str:
    """A short scroll target from the head of a longer chunk (one phrase)."""
    words = " ".join(str(text or "").split()).split()[:max_words]
    return " ".join(words)[:max_chars]


def _text_fragment(quote: str) -> str:
    """Build a `#:~:text=` directive that resolves to ``quote`` in the page.

    Ellipsis-joined quotes (``A ... B``) become a range ``text=A,B``. A long single
    sentence uses head/tail words as a range (shorter URL, still anchored). Every
    piece is fully percent-encoded so ``,``/``&``/``-`` can't clash with the syntax.
    """
    enc = lambda s: urllib.parse.quote(s, safe="")
    parts = [p.strip() for p in re.split(r"\.\.\.+|…", quote) if p.strip()]
    if len(parts) >= 2:
        return f"#:~:text={enc(parts[0])},{enc(parts[-1])}"
    q = (parts[0] if parts else quote).strip()
    words = q.split()
    if len(q) > 60 and len(words) >= 6:
        return f"#:~:text={enc(' '.join(words[:4]))},{enc(' '.join(words[-4:]))}"
    return f"#:~:text={enc(q)}"


def _deeplink(source_url: str, quote: str | None) -> str:
    """``source_url`` (+ text fragment when a quote is given). Empty if no url."""
    if not source_url:
        return ""
    if not quote:
        return source_url
    return source_url + _text_fragment(quote)


def _source_link(origins: list[str], quote: str | None) -> str:
    """Markdown link to the filing the quote came from, jumping to it if present."""
    code = _pick_origin(origins, quote)
    if code is None:
        return ""
    info = _load_filing_meta().get(code)
    if not info or not info.get("source_url"):
        return ""
    url = _deeplink(info["source_url"], quote)
    return f"[↗원문]({url})" if url else ""


def _collect_graph_evidence(rows: list[dict]) -> list[dict]:
    """Graph citation items: ``{display, quote, origins}`` (quote/origins optional).

    ``quote``/``origins`` let :func:`_format_citations` attach a source deep link;
    structural-overview refs (degree counts) carry neither and stay link-free.
    """
    seen: set[str] = set()
    refs: list[dict] = []

    def _add(display: str, quote: str | None = None, origins: list | None = None):
        if display not in seen:
            seen.add(display)
            refs.append({"display": display, "quote": quote, "origins": origins or []})

    for row in rows:
        if isinstance(row, dict):
            for body in _collect_overview_evidence(row):
                _add(body)
        for edge in row.get("evidence_edges") or []:
            if not isinstance(edge, dict):
                continue
            label = _edge_label(edge)
            evidences = [e for e in edge.get("evidences") or [] if e]
            origins = [o for o in edge.get("origins") or [] if o]
            if evidences:
                _add(f"{label}: \"{_truncate(evidences[0], 220)}\"", evidences[0], origins)
            elif origins:
                _add(f"{label}: origins={', '.join(map(str, origins))}", None, origins)
            else:
                _add(label)
    return refs


def _format_chunk_context(chunks: list[dict]) -> str:
    if not chunks:
        return "[]"
    compact = []
    for i, chunk in enumerate(chunks[:5], 1):
        compact.append({
            "ref": f"V{i}",
            "company": chunk.get("company"),
            "section": chunk.get("section"),
            "report_nm": chunk.get("report_nm"),
            "bsns_year": chunk.get("bsns_year"),
            "text": _truncate(chunk.get("text", ""), 900),
        })
    return json.dumps(compact, ensure_ascii=False, indent=2)


def _format_citations(rows: list[dict], chunks: list[dict]) -> str:
    lines: list[str] = []
    for i, ev in enumerate(_collect_graph_evidence(rows)[:8], 1):
        link = _source_link(ev["origins"], ev["quote"])
        suffix = f" {link}" if link else ""
        lines.append(f"[G{i}] {ev['display']}{suffix}")
    for i, chunk in enumerate(chunks[:5], 1):
        source = " · ".join(
            str(v) for v in [
                chunk.get("company"), chunk.get("section"),
                chunk.get("report_nm"), chunk.get("bsns_year"),
            ] if v
        )
        score = chunk.get("score")
        score_text = f", score={score:.3f}" if isinstance(score, float) else ""
        text = chunk.get("text", "")
        url = _deeplink(chunk.get("source_url", ""), _first_phrase(_chunk_body(text)))
        link = f" [↗원문]({url})" if url else ""
        lines.append(f"[V{i}] {source}{score_text}: \"{_truncate(text, 220)}\"{link}")
    return "\n".join(lines)


def _evidence_lines(rows: list[dict], chunks: list[dict]) -> list[str]:
    """Grounding material for the faithfulness gate — the same evidence shown in
    citations: each graph edge's display (relation + quote) and each chunk's
    verbatim body prose (minus vectorize's synthetic header)."""
    lines = [ev["display"] for ev in _collect_graph_evidence(rows)]
    for chunk in chunks[:5]:
        body = _truncate(_chunk_body(chunk.get("text", "")), 900)
        if body:
            lines.append(body)
    return lines


def generate_answer(
    question: str,
    rows: list[dict],
    chunks: list[dict] | None = None,
    *,
    llm=None,
    verify_llm=None,
    verify: bool = True,
) -> str:
    """Phrase query ``rows`` back as a grounded Korean answer.

    Kept separate from :func:`generate_cypher` so the answer stage can be tuned
    on its own. ``enable_thinking=False`` by default — the graph query already
    did the relational reasoning, so synthesis is fast/deterministic. Flip to
    ``True`` (via a caller-supplied ``llm``) if multi-hop narratives come out
    thin. Rows are capped at :data:`MAX_CONTEXT_ROWS` and serialized as
    ``ensure_ascii=False`` JSON so Korean names stay legible to the model.
    """
    if llm is None:
        llm = get_chat_llm(enable_thinking=False, max_tokens=1500)
    chunks = chunks or []
    clean_rows = [_strip_evidence(row) for row in rows[:MAX_CONTEXT_ROWS]]
    context = json.dumps(clean_rows, ensure_ascii=False, indent=2)
    prompt = ANSWER_TEMPLATE.format(
        question=question,
        context=context,
        chunks=_format_chunk_context(chunks),
    )
    response = llm.invoke(prompt)
    answer = response.content.strip()

    # Faithfulness gate (#3): flag answer sentences the evidence doesn't support
    # before attaching citations. Fails open (leaves the answer untouched) on a
    # refusal, empty evidence, or an unparsable verifier reply.
    parts = [answer]
    if verify:
        result = check_faithfulness(answer, _evidence_lines(rows, chunks), llm=verify_llm)
        parts = [result.text]
        if result.unsupported:
            block = "\n".join(f'- "{s}"' for s in result.unsupported)
            parts.append(f"⚠️ 검증되지 않은 진술 {len(result.unsupported)}건:\n{block}")

    citations = _format_citations(rows, chunks)
    if citations:
        parts.append(f"근거\n{citations}")
    return "\n\n".join(parts)


def answer_question(
    question: str, *, graph, cypher_llm=None, qa_llm=None
) -> dict:
    """Run the full pipeline and return every stage's output.

    Returns ``{"cypher", "rows", "answer"}`` — the intermediates travel with the
    answer so callers can show provenance (the benchmark ``pass_criteria`` want
    the grounding edges).
    """
    cypher = generate_cypher(question, schema=CYPHER_SCHEMA, llm=cypher_llm)
    rows = graph.query(cypher)
    answer = generate_answer(question, rows, llm=qa_llm)
    return {"cypher": cypher, "rows": rows, "answer": answer}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Step 5: answer a Korean question over the Neo4j graph."
    )
    parser.add_argument("question", help="자연어 질문 (한국어)")
    parser.add_argument("--show-cypher", action="store_true",
                        help="답변과 함께 생성된 Cypher와 조회 결과도 출력")
    parser.add_argument("--cypher-only", action="store_true",
                        help="답변 생성은 건너뛰고 번역된 Cypher만 출력 (튜닝용)")
    args = parser.parse_args()

    graph = get_neo4j_graph()
    try:
        cypher = generate_cypher(args.question, schema=CYPHER_SCHEMA)

        if args.cypher_only:
            print(cypher)
            return

        rows = graph.query(cypher)
        answer = generate_answer(args.question, rows)

        if args.show_cypher:
            print("--- 생성된 Cypher ---")
            print(cypher)
            print(f"\n--- 조회 결과 ({len(rows)} rows) ---")
            for row in rows[:MAX_CONTEXT_ROWS]:
                print(row)
            if len(rows) > MAX_CONTEXT_ROWS:
                print(f"  ... ({len(rows) - MAX_CONTEXT_ROWS} more)")
            print("\n--- 답변 ---")
        print(answer)
    finally:
        graph.close()


if __name__ == "__main__":
    main()
