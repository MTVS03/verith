# utils/entity.py
"""개체명(회사 등) 최소 정규화 — 병합 신호(TASK 05)와 그래프 노드 key(TASK 07)가 공유한다.

⚠️ 이 함수는 **결정적·최소**다: 앞뒤/중복 공백 정리 + `㈜`/`(주)`/`（주）` 제거, 그게 전부다.
복잡한 별칭·오타 canonical(`삼전`→`삼성전자`)은 하지 않는다 — 그건 질의측 Dictionary First
(docs/query_spec.md)가 담당한다. 배치측 추출 회사명은 이미 표준형에 가깝다.

같은 함수를 TASK 05(company_overlap)와 TASK 07(Company 노드 key)이 공유해야 병합 신호와 노드
정체성이 어긋나지 않는다(TASK 05 §3.3-2, TASK 07 §graph key). 정규화가 흔들리면 같은 회사가
다른 노드/다른 후보로 갈라진다.
"""
from __future__ import annotations

import re

# 제거 대상 '주식회사' 표기(전각/반각). 사건명이 아니라 회사명에만 붙는 접두/접미.
_CORP_TOKENS = ("㈜", "(주)", "（주）")
_WS_RE = re.compile(r"\s+")


def normalize_entity_name(name: str | None) -> str:
    """개체명을 최소 정규화한다. None/빈 문자열은 빈 문자열로 돌려준다(호출측이 거른다).

    - `㈜`/`(주)`/`（주）`를 공백으로 치환(붙어 있어도 분리).
    - 연속 공백을 하나로 합치고 앞뒤 공백 제거.
    - 그 외(대소문자·오타·별칭)는 건드리지 않는다(결정적·최소).
    """
    if not name:
        return ""
    text = name
    for token in _CORP_TOKENS:
        text = text.replace(token, " ")
    return _WS_RE.sub(" ", text).strip()
