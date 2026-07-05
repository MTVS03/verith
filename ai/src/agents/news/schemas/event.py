# schemas/event.py
"""이벤트(Event) + 병합 판정 모델(MergeCandidate/MergeDecision) + 조회 계약(CandidateEvent/EventArticleStats).

Neo4j 중심 노드의 '개념' 모델이다. Neo4j 노드/관계 상세 모델(schemas/graph.py)은 TASK 07에서 정의.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Neo4j 중심 노드(개념). 감성 count는 저장하지 않음(조회 시 실시간 집계, CLAUDE.md §5)."""
    # 대표 식별자. 문서·코드 공통으로 canonical_id로 부른다(id로 쓰지 않음).
    # 타입은 UUID 문자열 → Article.event_id / MergeCandidate.event_id / MergeDecision.assigned_event_id와 동일.
    canonical_id: str | None = None        # 대표 식별자 UUID(신규 생성 전 None)
    canonical_title: str                   # 대표명. 감성 평가어 금지("실적 발표" O / "실적 호조" X, event_merge.md §6)
    importance: float | None = None        # TASK 06에서 계산(기사 개수 + 언론사 가중치 + 감성 절대값)
    companies: list[str] = Field(default_factory=list)  # PARTICIPATES_IN 대상
    created_at: datetime | None = None     # 이벤트 최초 생성 시각(집계값 아님, 관리·정렬 편의 메타)


class MergeCandidate(BaseModel):
    """병합 후보 1건과 그 점수(TASK 05). 결과 자료구조만 여기 정의, 계산 로직은 TASK 05."""
    event_id: str              # 후보 이벤트의 canonical_id(UUID)
    score: float               # 0.6·summary + 0.3·company + 0.1·time (event_merge.md §3)
    # 병합 품질 디버깅용 세부 점수(선택). 최종 score만으로는 어느 신호가 병합을 이끌었는지 알 수 없음.
    summary_similarity: float | None = None
    company_overlap: float | None = None
    time_similarity: float | None = None


class MergeDecision(BaseModel):
    """새 기사 병합 판정 결과."""
    assigned_event_id: str | None   # 편입될 이벤트의 canonical_id(UUID). None이면 신규 생성 대상
    is_new_event: bool
    best_score: float | None = None
    candidates: list[MergeCandidate] = Field(default_factory=list)
    # 확장 여지(지금은 넣지 않음): 향후 임베딩 병합 위에 LLM 검증 단계를 추가하면
    # llm_verified: bool 등을 여기에 덧붙인다. 현재 스키마는 이 확장을 막지 않도록 설계.


class CandidateEvent(BaseModel):
    """병합 후보 이벤트(조회 결과, TASK 05). RecentEventProvider가 반환, 점수 계산 입력."""
    canonical_id: str
    companies: list[str] = Field(default_factory=list)
    embedding: list[float]              # 대표 벡터(centroid). 계산·갱신은 backend, TASK 05는 읽기만
    event_time: datetime | None = None  # 이벤트 발생 시점(없으면 최신 기사 시각). time_proximity 입력


class EventArticleStats(BaseModel):
    """기존(저장된) 이벤트의 누적 기사 통계(TASK 06). 전체 재계산 시 이번 배치와 '합산'하는 입력."""
    article_count: int = 0
    publishers: list[str] = Field(default_factory=list)   # 원자료·distinct 계약(가중치는 agent가 적용)
    sentiment_magnitude_sum: float = 0.0                  # 감성 있는(None 아님) 저장 기사 강도 합
    sentiment_count: int = 0                              # 감성 있는 저장 기사 개수(평균 재결합용)
    updated_at: datetime | None = None                    # (선택) 통계 산출 시각. 디버깅용, 계산엔 미사용
