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
