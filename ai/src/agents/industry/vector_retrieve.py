"""Step 2 (갈래 B) — DART 원문 청크 벡터 검색(읽기 계층).

Step 1(``vectorize.py``)이 색인의 '쓰기' 절반이라면, 여기는 '읽기' 절반이다.
자연어 질의를 받아 관련 원문 청크를 **인용 메타와 함께** top-k로 돌려준다.
Step 3(그래프+벡터 융합 + 인용)이 이 함수 하나를 그대로 소비하도록,
반환값을 답변 인용에 필요한 필드(출처 회사·보고서·섹션·URL)로 정규화한다.

검색 경로는 두 갈래다:

  - **전체 검색**(company=None): 벡터 인덱스 ``db.index.vector.queryNodes``로
    전역 top-k. 대부분의 질의가 이 경로.
  - **회사 한정**(company 지정): 인덱스 top-k에서 사후 필터링하면 특정 회사
    결과가 k보다 적게(때론 0개) 나올 수 있다(인덱스는 전역 상위만 본다).
    코퍼스가 작으니(≈775청크/10개사) 해당 회사 청크만 대상으로 코사인을
    직접 계산·정렬해 **정확한 k**를 보장한다. company는 반드시
    ``normalize_name``을 통과시켜 저장된 Company 키와 맞춘다.

점수는 Neo4j가 코사인을 ``(1+cos)/2``로 정규화한 [0,1] 값(두 경로 동일 스케일).
따라서 무관 청크 컷오프(``min_score``)는 데이터로 관측한 뒤 정할 문제라
기본은 끄고(None) 옵션으로 뺀다 — 임의 임계값을 하드코딩하지 않는다.

Run:
    uv run python -m src.agents.industry.vector_retrieve --query "LG화학 첨단소재 사업"
    uv run python -m src.agents.industry.vector_retrieve --query "..." --company LG화학 --k 3
"""

from __future__ import annotations

import argparse
import threading

from .config import get_embeddings, get_neo4j_graph
from .normalize import normalize_name
from .vectorize import VECTOR_INDEX  # 인덱스 이름의 단일 출처(Step 1)

# 답변 인용에 필요한 청크 속성. id/stock_code/idx는 Step 3의 중복 제거·
# 인접 청크 병합·출처 구분에 쓰이므로 함께 돌려준다.
_RETURN_PROPS = (
    "id", "text", "company", "stock_code",
    "report_nm", "bsns_year", "section", "idx", "source_url",
)
_PROJECTION = "{ " + ", ".join(f".{p}" for p in _RETURN_PROPS) + " }"

# 임베딩 모델은 무겁다(GPU 로딩). 한 번 만들어 재사용한다. 락으로 감싸
# 에이전트에서 동시 첫 호출이 모델을 두 번 로딩하는 경쟁을 막는다.
_EMBEDDINGS = None
_EMBEDDINGS_LOCK = threading.Lock()


def _embeddings():
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        with _EMBEDDINGS_LOCK:
            if _EMBEDDINGS is None:
                _EMBEDDINGS = get_embeddings()
    return _EMBEDDINGS


def vector_search(
    query: str,
    k: int = 5,
    company: str | None = None,
    *,
    min_score: float | None = None,
    graph=None,
    embeddings=None,
) -> list[dict]:
    """질의와 의미적으로 가까운 원문 청크를 top-k로 반환(인용 메타 동반).

    Args:
        query: 사용자 질문 원문.
        k: 반환 청크 수.
        company: 특정 회사로 한정(선택). 저장 키와 맞추려 내부에서
            ``normalize_name``을 적용한다.
        min_score: 지정 시 정규화 코사인 점수가 이 값 미만인 청크는 버린다.
            기본 None(컷오프 없음) — 임계값은 관측 후 정할 문제라 강제하지 않는다.
        graph / embeddings: 주입용(테스트·재사용). 기본은 팩토리에서 얻는다.

    Returns:
        각 청크에 대해 ``_RETURN_PROPS`` + ``score``(정규화 코사인, [0,1])를
        담은 dict의 리스트. 점수 내림차순.
    """
    if not query or not query.strip() or k <= 0:
        return []
    emb = embeddings or _embeddings()

    # arctic 비대칭 프롬프트: embed_query가 'query: ' 프리픽스를 붙인다.
    # 절대 embed_documents로 질의를 임베딩하지 말 것(검색 품질 하락).
    qvec = emb.embed_query(query)

    params: dict = {"qvec": qvec, "k": k}
    if company:
        # 저장된 company는 normalize_name 통과값 — 필터 인자도 같게 맞춘다.
        canonical = normalize_name(company, "Company")
        if not canonical:
            return []  # 정규화가 회사를 지워버림(junk/무효) → 매칭 불가
        params["company"] = canonical
        # 회사 한정: 인덱스 대신 해당 회사 청크만 직접 랭킹 → 정확한 k 보장.
        cypher = f"""
        MATCH (c:Chunk {{company: $company}})
        WITH c, vector.similarity.cosine(c.embedding, $qvec) AS score
        RETURN c {_PROJECTION} AS c, score
        ORDER BY score DESC
        LIMIT $k
        """
    else:
        # 전체 검색: 벡터 인덱스의 전역 top-k.
        params["index"] = VECTOR_INDEX
        cypher = f"""
        CALL db.index.vector.queryNodes($index, $k, $qvec) YIELD node, score
        RETURN node {_PROJECTION} AS c, score
        ORDER BY score DESC
        """

    # 이 함수가 만든 graph만 닫는다(주입받은 건 호출자 소유 — Step 3의 공유
    # graph 재사용 대비). retrieve.py/vectorize.py의 try/finally 패턴과 일치.
    own_graph = graph is None
    graph = graph or get_neo4j_graph()
    try:
        rows = graph.query(cypher, params)
    finally:
        if own_graph:
            graph.close()

    results = []
    for row in rows:
        if min_score is not None and row["score"] < min_score:
            continue
        results.append({**row["c"], "score": row["score"]})
    return results


def _format(results: list[dict]) -> str:
    if not results:
        return "(검색 결과 없음)"
    lines = []
    for i, r in enumerate(results, 1):
        head = f"[{i}] {r['score']:.3f}  {r['company']} · {r['section']} " \
               f"({r.get('report_nm', '')} {r.get('bsns_year', '')})"
        body = r["text"].replace("\n", " ")
        if len(body) > 200:
            body = body[:200] + "…"
        lines.append(f"{head}\n    {body}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Step 2 (갈래 B): DART 원문 청크 벡터 검색(인용 메타 동반)."
    )
    parser.add_argument("--query", required=True, help="검색 질의")
    parser.add_argument("--k", type=int, default=5, help="반환 청크 수")
    parser.add_argument("--company", default=None, help="특정 회사로 한정(선택)")
    parser.add_argument("--min-score", type=float, default=None,
                        help="정규화 코사인 컷오프(기본 없음)")
    args = parser.parse_args()

    graph = get_neo4j_graph()
    try:
        results = vector_search(
            args.query, k=args.k, company=args.company,
            min_score=args.min_score, graph=graph,
        )
    finally:
        graph.close()
    print(_format(results))


if __name__ == "__main__":
    main()
