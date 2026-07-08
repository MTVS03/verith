"""news 지식그래프 영속화 — Neo4j.

GraphBatch(노드·관계 델타)를 정체성 키 기준 MERGE(upsert)로 기존 그래프에 합친다(멱등,
SCHEMA_SPEC §3). NewsRef 는 `key=url` 로 오므로 backend 가 같은 배치의 `url→news_id` 맵으로
`news_id` 를 해소해 저장한다(SCHEMA_SPEC §2.4/§3).

라벨·관계 타입 문자열은 ai 계약 Enum(schemas.news NodeLabel/RelType)으로 검증된 값만
쿼리에 삽입한다(화이트리스트 — Cypher 는 라벨을 파라미터화할 수 없음).
"""

from __future__ import annotations

from neo4j import AsyncManagedTransaction, AsyncSession

from src.api.schemas.news import GraphBatch, NodeLabel

# 노드 정체성 속성: NewsRef 는 news_id, 나머지는 key (bootstrap 제약과 일치).
_NEWSREF = NodeLabel.NEWS_REF


def _identity(label: NodeLabel, key: str, url_to_news_id: dict[str, int]):
    """(label 문자열, 정체성 속성명, 정체성 값) 또는 해소 불가 시 None."""
    if label is _NEWSREF:
        news_id = url_to_news_id.get(key)
        if news_id is None:
            return None  # url 이 이번 배치 articles 에 없으면 해소 불가 → skip
        return label.value, "news_id", news_id
    return label.value, "key", key


async def merge_graph(
    session: AsyncSession, graph_batch: GraphBatch, url_to_news_id: dict[str, int]
) -> None:
    """GraphBatch 를 한 트랜잭션으로 MERGE. NewsRef 는 news_id 로 해소."""
    if not graph_batch.nodes and not graph_batch.relationships:
        return

    async def _work(tx: AsyncManagedTransaction) -> None:
        for node in graph_batch.nodes:
            props = dict(node.properties)
            if node.label is _NEWSREF:
                news_id = url_to_news_id.get(node.key)
                if news_id is None:
                    continue
                props.setdefault("url", node.key)
                props["news_id"] = news_id
                await tx.run(
                    "MERGE (n:NewsRef {news_id: $val}) SET n += $props",
                    val=news_id,
                    props=props,
                )
            else:
                await tx.run(
                    f"MERGE (n:{node.label.value} {{key: $val}}) SET n += $props",
                    val=node.key,
                    props=props,
                )

        for rel in graph_batch.relationships:
            start = _identity(rel.start_label, rel.start_key, url_to_news_id)
            end = _identity(rel.end_label, rel.end_key, url_to_news_id)
            if start is None or end is None:
                continue  # 끝점 해소 불가(예: NewsRef url 미저장) → 관계 skip
            s_label, s_prop, s_val = start
            e_label, e_prop, e_val = end
            await tx.run(
                f"MATCH (a:{s_label} {{{s_prop}: $sval}}) "
                f"MATCH (b:{e_label} {{{e_prop}: $eval}}) "
                f"MERGE (a)-[r:{rel.type.value}]->(b) SET r += $props",
                sval=s_val,
                eval=e_val,
                props=dict(rel.properties),
            )

    await session.execute_write(_work)


# ── 조회(질의 흐름) ──────────────────────────────────────────────────────────
async def get_events_by_companies(
    session: AsyncSession, companies: list[str]
) -> list[dict]:
    """single-hop: 주어진 회사들이 참여한 이벤트 목록.

    각 이벤트의 전체 참여 회사(companies)도 함께 반환한다(감성·recency 집계는 PostgreSQL).
    반환: [{canonical_id, canonical_title, importance, companies}].
    """
    if not companies:
        return []
    query = (
        "MATCH (c:Company)-[:PARTICIPATES_IN]->(e:Event) WHERE c.key IN $companies "
        "WITH DISTINCT e "
        "OPTIONAL MATCH (co:Company)-[:PARTICIPATES_IN]->(e) "
        "RETURN e.key AS canonical_id, e.canonical_title AS canonical_title, "
        "       e.importance AS importance, collect(DISTINCT co.key) AS companies"
    )
    result = await session.run(query, companies=companies)
    return [r.data() async for r in result]


async def get_shared_events(
    session: AsyncSession, company_a: str, company_b: str
) -> list[dict]:
    """multi-hop: 두 회사가 함께 참여한 공유 이벤트 목록(관계 질문). 반환 형태는 위와 동일."""
    query = (
        "MATCH (a:Company {key:$a})-[:PARTICIPATES_IN]->(e:Event)"
        "<-[:PARTICIPATES_IN]-(b:Company {key:$b}) "
        "WITH DISTINCT e "
        "OPTIONAL MATCH (co:Company)-[:PARTICIPATES_IN]->(e) "
        "RETURN e.key AS canonical_id, e.canonical_title AS canonical_title, "
        "       e.importance AS importance, collect(DISTINCT co.key) AS companies"
    )
    result = await session.run(query, a=company_a, b=company_b)
    return [r.data() async for r in result]


async def companies_exist(
    session: AsyncSession, companies: list[str]
) -> bool:
    """주어진 회사명 중 하나라도 Company 노드로 존재하면 True('없는 종목' 구분용)."""
    if not companies:
        return False
    result = await session.run(
        "MATCH (c:Company) WHERE c.key IN $companies RETURN count(c) AS n",
        companies=companies,
    )
    rec = await result.single()
    return bool(rec and rec["n"] > 0)


# ── 7일 롤링 cleanup ─────────────────────────────────────────────────────────
async def cleanup_graph(
    session: AsyncSession,
    deleted_news_ids: list[int],
    empty_event_keys: list[str],
    importance_updates: dict[str, float],
) -> int:
    """삭제된 기사에 대응하는 그래프 정리. 삭제된 Event 수를 반환.

    순서: (1) NewsRef 삭제(news_id) → (2) 살아남은 Event importance 갱신 →
    (3) 기사수 0 이벤트 DETACH DELETE → (4) 고아 Keyword/Person/Country 삭제(**Company 유지**).
    SCHEMA_SPEC §5. Event/개체 key = canonical_id/이름 문자열.
    """

    async def _work(tx: AsyncManagedTransaction) -> int:
        if deleted_news_ids:
            await tx.run(
                "MATCH (nr:NewsRef) WHERE nr.news_id IN $ids DETACH DELETE nr",
                ids=deleted_news_ids,
            )

        if importance_updates:
            await tx.run(
                "UNWIND $updates AS u MATCH (e:Event {key: u.key}) SET e.importance = u.score",
                updates=[{"key": k, "score": v} for k, v in importance_updates.items()],
            )

        deleted_events = 0
        if empty_event_keys:
            rec = await (await tx.run(
                "MATCH (e:Event) WHERE e.key IN $keys DETACH DELETE e RETURN count(e) AS n",
                keys=empty_event_keys,
            )).single()
            deleted_events = rec["n"] if rec else 0

        # 고아 정리: 어떤 Event 도 가리키지 않는 Keyword/Person/Country 삭제(Company 는 유지).
        await tx.run(
            "MATCH (n) WHERE (n:Keyword OR n:Person OR n:Country) "
            "AND NOT (:Event)-->(n) DETACH DELETE n"
        )
        return deleted_events

    return await session.execute_write(_work)
