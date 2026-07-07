"""Step 1 (갈래 B) — DART 원문 청킹 + 임베딩 + Neo4j 벡터 인덱스 적재.

하이브리드 검색의 색인 절반. 그래프(5종 관계)가 못 담는 원문 사실을 벡터로
보완하고, 각 청크에 출처(회사·보고서·섹션·URL)를 실어 답변 인용을 가능케 한다.

    data/raw/<종목코드>/{business_content.txt, meta.json}
      -> 섹션 인지 분할 (헤더 breadcrumb) -> 섹션 내 재귀 분할(~800자)
      -> get_embeddings().embed_documents (arctic-embed, 1024d, GPU)
      -> MERGE (:Chunk {id}) + 벡터 인덱스 + MERGE (c)-[:FROM_FILING]->(:Company)

Company 노드는 `name`으로 키잉되므로(ingest.py), 청크의 소유사도 반드시
``normalize.normalize_name``을 통과시켜 기존 노드에 정확히 붙인다(고아 청크 방지).
읽기(벡터 검색)는 Step 2 ``vector_retrieve``가 담당 — 여기선 색인만.

Run:
    uv run python -m src.agents.industry.vectorize            # 청킹+임베딩+적재
    uv run python -m src.agents.industry.vectorize --reset-chunks  # :Chunk 재적재
    uv run python -m src.agents.industry.vectorize --dry-run  # 통계만(임베딩/적재 X)
    uv run python -m src.agents.industry.vectorize --limit 2  # 앞 2개사만(개발용)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import RAW_DIR, get_embeddings, get_neo4j_graph
from .normalize import normalize_name

# arctic-embed-l-v2.0-ko 차원. config.get_embeddings()와 반드시 일치.
EMBED_DIM = 1024
VECTOR_INDEX = "chunk_embedding"

# 섹션 내 재귀 분할 파라미터. arctic은 8192토큰까지 받지만, 답변 컨텍스트(8192)
# 보호 + top-k 정밀도를 위해 작게 자른다.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
# 본문이 이보다 짧은 조각은 헤더/빈 표 파편 — 검색 노이즈라 버린다.
MIN_PIECE_CHARS = 30

# 사업보고서 '사업의 내용' 헤더 3종. 슬롯별로 breadcrumb를 유지한다.
_TOP_RE = re.compile(r"^\d+\.\s+\S")        # "1. 사업의 개요"
_BRACKET_RE = re.compile(r"^\[.+\]$")        # "[첨단소재 사업부문]"
_SUB_RE = re.compile(r"^[가-힣]\.\s+\S")      # "가. 주요 제품"


def _iter_sections(text: str):
    """원문을 (breadcrumb, 본문) 세그먼트로 나눠 순서대로 yield.

    헤더를 만나면 해당 슬롯(top/bracket/sub)을 갱신하고 하위 슬롯을 비운다.
    breadcrumb가 바뀔 때마다 직전 세그먼트를 방출 — 섹션 경계가 청킹 경계가 된다.
    """
    top = bracket = sub = ""
    buf: list[str] = []

    def crumb() -> str:
        return " > ".join(p for p in (top, bracket, sub) if p)

    prev = crumb()
    for line in text.splitlines():
        s = line.strip()
        is_header = True
        if _TOP_RE.match(s):
            top, bracket, sub = s, "", ""
        elif _BRACKET_RE.match(s):
            bracket, sub = s, ""
        elif _SUB_RE.match(s):
            sub = s
        else:
            is_header = False

        if is_header:
            if buf and "".join(buf).strip():
                yield prev, "\n".join(buf).strip()
            buf = []
            prev = crumb()
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        yield prev, "\n".join(buf).strip()


def _chunk_id(stock_code: str, idx: int, text: str) -> str:
    """재실행 시 MERGE로 겹치도록, 같은 입력이면 같은 id (내용 해시 포함)."""
    h = hashlib.sha1(f"{stock_code}|{idx}|{text}".encode("utf-8")).hexdigest()
    return f"{stock_code}-{idx:04d}-{h[:8]}"


def build_chunks(*, limit: int | None = None) -> list[dict]:
    """원문 폴더를 청크 레코드 리스트로 변환 (임베딩/DB 접근 없음).

    각 레코드: id, text(=breadcrumb 접두 포함), company(정규화됨), stock_code,
    source_url, report_nm, bsns_year, section, idx.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    records: list[dict] = []
    dirs = sorted(p for p in RAW_DIR.iterdir() if p.is_dir())
    if limit is not None:
        dirs = dirs[:limit]

    for d in dirs:
        content_f, meta_f = d / "business_content.txt", d / "meta.json"
        if not (content_f.exists() and meta_f.exists()):
            continue
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        company = normalize_name(meta["canonical"], "Company")
        base = {
            "company": company,
            "stock_code": meta.get("stock_code", d.name),
            "source_url": meta.get("source_url", ""),
            "report_nm": meta.get("report_nm", ""),
            "bsns_year": meta.get("bsns_year"),
        }
        text = content_f.read_text(encoding="utf-8")
        idx = 0
        for crumb, body in _iter_sections(text):
            for piece in splitter.split_text(body):
                if len(piece.strip()) < MIN_PIECE_CHARS:
                    continue
                # 회사+섹션 경로를 본문 앞에 붙여 문맥 보강(잘린 조각의 소속 명시).
                header = f"[{company}] {crumb}".strip()
                chunk_text = f"{header}\n{piece}" if crumb else f"[{company}]\n{piece}"
                records.append({
                    **base,
                    "id": _chunk_id(base["stock_code"], idx, piece),
                    "section": crumb,
                    "idx": idx,
                    "text": chunk_text,
                })
                idx += 1
    return records


# --- Neo4j 적재 --------------------------------------------------------------

def ensure_vector_index(graph) -> None:
    """:Chunk.id 유니크 제약 + 벡터 인덱스(1024d, cosine). 멱등."""
    graph.query(
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE c.id IS UNIQUE"
    )
    graph.query(
        f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS "
        "FOR (c:Chunk) ON (c.embedding) "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {EMBED_DIM}, "
        "`vector.similarity_function`: 'cosine'}}"
    )


def reset_chunks(graph) -> None:
    """모든 :Chunk 노드(+FROM_FILING) 삭제. 청킹 파라미터 변경 후 재적재용."""
    graph.query("MATCH (c:Chunk) DETACH DELETE c")
    print("Reset: deleted all :Chunk nodes.")


def validate_companies(graph, records: list[dict]) -> None:
    """쓰기 **전에** 모든 청크 소유사가 기존 Company 노드인지 확인, 아니면 중단.

    Company 노드는 ingest.py(Step 4)가 authoritative하게 관리한다. 여기서
    새 Company를 만들면 안 된다 — 정규화가 어긋난 이름은 스스로 고아 노드를
    만들어 그래프를 오염시킨다. 그래서 적재 직전 검증해 어긋난 이름이 하나라도
    있으면 **아무것도 쓰기 전에** 중단한다(validate-then-write)."""
    existing = {r["name"] for r in graph.query("MATCH (c:Company) RETURN c.name AS name")}
    missing = sorted({r["company"] for r in records} - existing)
    if missing:
        raise SystemExit(
            f"중단: 청크 소유사 {len(missing)}개가 그래프에 없음(정규화 확인 필요): {missing}. "
            "적재를 취소한다 — 그래프 오염 방지."
        )


def ingest_chunks(graph, records: list[dict], embeddings: list[list[float]]) -> None:
    """이 실행에 포함된 회사들의 청크를 **교체**(scoped replace)하고 적재.

    먼저 이번 실행의 회사(stock_code) 청크를 지운 뒤 새로 넣는다. 청크 id는
    내용 해시 기반이라 청킹 파라미터가 바뀌면 옛 id 청크가 남아 누적된다(stale).
    회사 단위로 교체하면 ``--reset-chunks`` 없이도 default 실행이 멱등해지고,
    사후 검증이 이번 실행분과 정확히 일치한다. (다른 회사 청크는 건드리지 않아
    ``--limit`` 부분 적재도 안전하다.)

    소유사는 **MATCH**로만 잡는다(MERGE 아님) — Company 노드 생성은 ingest.py의
    몫이라, 여기선 절대 새 회사를 만들지 않는다. 호출 전 :func:`validate_companies`가
    모든 소유사 존재를 보장한다."""
    codes = sorted({r["stock_code"] for r in records})
    graph.query(
        "MATCH (c:Chunk) WHERE c.stock_code IN $codes DETACH DELETE c",
        {"codes": codes},
    )
    rows = []
    for r, emb in zip(records, embeddings):
        rows.append({
            "id": r["id"], "emb": emb, "company": r["company"],
            "props": {k: r[k] for k in
                      ("text", "company", "stock_code", "source_url",
                       "report_nm", "bsns_year", "section", "idx")},
        })
    graph.query(
        """
        UNWIND $rows AS row
        MATCH (co:Company {name: row.company})
        MERGE (c:Chunk {id: row.id})
        SET c += row.props
        WITH c, co, row
        CALL db.create.setNodeVectorProperty(c, 'embedding', row.emb)
        MERGE (c)-[:FROM_FILING]->(co)
        """,
        {"rows": rows},
    )
    print(f"Replaced chunks for {len(codes)} companies -> merged {len(rows)} :Chunk nodes.")


def verify(graph, records: list[dict]) -> bool:
    """적재 후 사후 점검 — **이번 실행분**에 한정(전역 카운트 아님).

    ``--limit`` 부분 적재나 회사 단위 교체에서도 옳도록, 그래프 전체 청크 수가
    아니라 이번 실행에서 만든 id들이 (a) 모두 존재하고 (b) 모두 소유사에
    연결됐는지만 본다. validate_companies가 쓰기 전에 소유사 존재를 보장하므로
    2차 방어선이다."""
    ok = True
    ids = [r["id"] for r in records]
    unique = len(set(ids))
    present = graph.query(
        "MATCH (c:Chunk) WHERE c.id IN $ids RETURN count(c) AS n", {"ids": ids}
    )[0]["n"]
    print(f"Chunks (이번 실행): built {unique} -> present {present}")
    if present != unique:
        ok = False
        print(f"  경고: 이번 실행 청크 {unique - present}개가 그래프에 없음(적재 실패 의심).")

    unlinked = graph.query(
        "MATCH (c:Chunk) WHERE c.id IN $ids AND NOT (c)-[:FROM_FILING]->(:Company) "
        "RETURN c.id AS id LIMIT 5", {"ids": ids}
    )
    if unlinked:
        ok = False
        print(f"  FROM_FILING 없는 청크 발견(정규화 의심): {[r['id'] for r in unlinked]}")
    else:
        print("  이번 실행 청크 모두 기존 Company에 연결됨(고아 0).")

    total = graph.query("MATCH (c:Chunk) RETURN count(c) AS n")[0]["n"]
    print(f"  총 :Chunk 노드: {total}")
    return ok


# --- CLI ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Step 1 (갈래 B): DART 원문을 청킹·임베딩해 Neo4j에 벡터 적재."
    )
    parser.add_argument("--reset-chunks", action="store_true",
                        help="적재 전 기존 :Chunk 노드를 모두 삭제")
    parser.add_argument("--dry-run", action="store_true",
                        help="임베딩/DB 없이 청킹 통계만 출력")
    parser.add_argument("--limit", type=int, default=None,
                        help="앞 N개 회사만 처리(개발용)")
    args = parser.parse_args()

    records = build_chunks(limit=args.limit)
    companies = sorted({r["company"] for r in records})
    print(f"Built {len(records)} chunks from {len(companies)} companies.")
    if records:
        lens = [len(r["text"]) for r in records]
        print(f"  chunk chars: min {min(lens)}, avg {sum(lens)//len(lens)}, max {max(lens)}")

    if args.dry_run:
        for c in companies:
            print(f"  {c}: {sum(1 for r in records if r['company'] == c)} chunks")
        return

    graph = get_neo4j_graph()
    try:
        # 쓰기·임베딩 전에 소유사 존재를 먼저 검증 — 어긋나면 즉시 중단(그래프
        # 오염 방지 + 비싼 임베딩 회피).
        validate_companies(graph, records)

        print("Embedding on device (GPU if available)...")
        emb = get_embeddings()
        vectors = emb.embed_documents([r["text"] for r in records])
        print(f"  embedded {len(vectors)} chunks, dim {len(vectors[0])}")

        if args.reset_chunks:
            reset_chunks(graph)
        ensure_vector_index(graph)
        ingest_chunks(graph, records, vectors)
        if not verify(graph, records):
            raise SystemExit(1)
    finally:
        graph.close()


if __name__ == "__main__":
    main()
