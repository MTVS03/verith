# schemas/graph.py
"""Neo4j 노드/관계 계약 모델(신규, TASK 07 소유).

그래프 빌더(services/graph_builder.py)의 출력 타입이자 backend(TASK 08)가 저장할 payload 계약이다.
erd.dbml / backend/db/models/news/SCHEMA_SPEC.md §3 의 노드·관계와 1:1 대응한다. 라벨·관계 타입
문자열은 여기 Enum 한 곳에 두고(계약), 정책값(3차 토글·NewsRef 키 방식)만 config 에 둔다.

★ 이 payload 는 "이번 배치가 추가/갱신할 델타"다. 기존 그래프와의 합치기는 backend 가 정체성 키
  기준 MERGE(upsert)로 한다(증분, event_merge.md §7). 그래프 빌더는 기존 그래프를 읽지 않는다.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeLabel(str, Enum):
    """Neo4j 노드 라벨(erd.dbml 그대로)."""
    EVENT = "Event"
    COMPANY = "Company"
    KEYWORD = "Keyword"
    PERSON = "Person"
    COUNTRY = "Country"
    SECTOR = "Sector"        # 3차·보류(BELONGS_TO off 면 미생성)
    NEWS_REF = "NewsRef"


class RelType(str, Enum):
    """Neo4j 관계 타입(erd.dbml 그대로). 주석은 방향(start→end)."""
    PARTICIPATES_IN = "PARTICIPATES_IN"   # (Company)->(Event)
    HAS_NEWS = "HAS_NEWS"                  # (Event)->(NewsRef)
    HAS_KEYWORD = "HAS_KEYWORD"           # (Event)->(Keyword)
    MENTIONS = "MENTIONS"                 # (Event)->(Person)
    ABOUT = "ABOUT"                       # (Event)->(Country)
    BELONGS_TO = "BELONGS_TO"             # (Company)->(Sector)   ※ 3차·보류
    RELATED_TO = "RELATED_TO"             # (Company)->(Company)  ※ 3차·보류


class GraphNode(BaseModel):
    """MERGE 대상 노드. `label` + `key` 가 정체성(backend 가 이 둘로 MERGE).

    key 규약: Event=canonical_id(UUID), 개체(Company/Keyword/Person/Country/Sector)=정규화된 이름,
    NewsRef=str(url). properties 값은 JSON 직렬화 가능한 타입만 담는다(backend HTTP 계약) —
    datetime 은 ISO8601 문자열로 넣는다. 감성 count/분포 property 는 두지 않는다(조회 시 집계, CLAUDE.md §5).
    """
    label: NodeLabel
    key: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphRelationship(BaseModel):
    """MERGE 대상 관계. 방향·양끝 노드로만 유일하다(식별 property 없음).

    정체성 = (type, start_label, start_key, end_label, end_key). 방향은 erd.dbml 그대로
    (예: PARTICIPATES_IN 은 start=Company, end=Event). start/end 는 GraphNode 의 (label,key)를 가리킨다.
    """
    type: RelType
    start_label: NodeLabel
    start_key: str
    end_label: NodeLabel
    end_key: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphBatch(BaseModel):
    """이번 배치가 추가/갱신할 노드·관계 델타. backend 가 key 기준 MERGE(upsert)로 기존 그래프에 합침.

    - 감성 미포함(구조만; 분포는 조회 시 집계, CLAUDE.md §5).
    - NewsRef 는 url 키(backend 가 저장 시 news_id 로 해소, SCHEMA_SPEC §3).
    - 결정적: 같은 배치 입력이면 항상 같은 GraphBatch(정렬·dedup, 난수·시간·LLM 없음).
    """
    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)
