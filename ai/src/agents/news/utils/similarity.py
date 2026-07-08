# utils/similarity.py
"""병합 신호 순수 계산 — 코사인 유사도·회사 중복도·시간 근접도(TASK 05).

세 함수 모두 **순수 함수**(입력→출력)다. 모델·네트워크·저장이 없어 병합 로직(services/event_merge.py)과
테스트가 그대로 재사용한다(CLAUDE.md §2-2/§7). 유사도 '판정'(임계값 비교·가중 합산)은 여기서 하지
않는다 — 여기는 신호만 만들고, 결합·판정은 services/event_merge.py 가 한다.
"""
from __future__ import annotations

import math
from datetime import datetime

from src.agents.news.config import MERGE_TIME_DECAY_DAYS
from src.agents.news.utils.entity import normalize_entity_name


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도. summary_similarity 신호로 사용.

    - 실무상 병합 신호는 0~1만 의미 있으므로 음수는 0으로 clamp하고 상한은 1로 둔다.
    - 빈 벡터나 영벡터(노름 0)는 0.0(유사도를 정의할 수 없음 → 병합 신호 없음).
    - 차원이 다르면 계약 위반(같은 모델 임베딩이어야 함) → ValueError(호출측이 기사 단위 격리).
    """
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        raise ValueError(f"벡터 차원 불일치: {len(a)} != {len(b)}")

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    cos = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    if cos < 0.0:
        return 0.0
    if cos > 1.0:
        return 1.0
    return cos


def company_overlap(a: list[str], b: list[str]) -> float:
    """두 회사 리스트의 중복도(0~1, Jaccard = |A∩B| / |A∪B|).

    - 회사명은 normalize_entity_name(공유 최소 정규화)으로 맞춘 뒤 집합으로 비교한다(TASK 07과 동일 기준).
    - **한쪽이라도 비어 있으면 0**: 회사 일치를 확인할 수 없으므로 병합 신호로 인정하지 않는다
      (다른 회사 사건 병합 방지, event_merge.md §3).
    """
    set_a = {n for n in (normalize_entity_name(x) for x in a) if n}
    set_b = {n for n in (normalize_entity_name(x) for x in b) if n}
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union)


def time_proximity(t1: datetime | None, t2: datetime | None) -> float:
    """두 이벤트 발생 시점의 근접도(0~1). Δ가 커질수록 0에 수렴(exp 감쇠, MERGE_TIME_DECAY_DAYS 스케일).

    - Δ=0이면 1.0, 하루 차이·이틀 차이로 갈수록 감쇠한다.
    - 한쪽이라도 None이면 시간 신호 없음(0.0). aware/naive 혼용으로 뺄셈이 불가하면 신호 없음으로 처리.
    - 입력은 '이벤트 발생 시점'이다(발행 시점이 아님, TASK 03 §2). 결정은 services/event_merge.py.
    """
    if t1 is None or t2 is None:
        return 0.0
    try:
        delta_days = abs((t1 - t2).total_seconds()) / 86400.0
    except TypeError:  # aware/naive 혼용 등 비교 불가 → 시간 신호 없음
        return 0.0
    return math.exp(-delta_days / MERGE_TIME_DECAY_DAYS)
