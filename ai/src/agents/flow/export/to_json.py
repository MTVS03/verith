"""export/to_json.py — 신호·검증 → JSON 페이로드 (render 와 나란한 또 하나의 출구).

원리: "직렬화지 재계산이 아니다."
  계산·검증은 signals.py·verify_*.py 가 이미 끝냈다. 여기서는 그 결과를 받는
  쪽이 읽을 수 있게 '옮겨 담기만' 한다 — signals 를 재호출하지 않고 어떤 값도
  만들거나 바꾸지 않는다(허용되는 실변환은 UUID→str 하나). render 가 "표시만",
  extract_daily 가 "꺼내기만"인 것과 같은 원리다.

verification 키가 "검증된 데이터" 정체성의 운반체다: 게이트 1·2·3의 통과 여부와
checks 전문이 실려, JSON 만 받은 쪽도 숫자마다 무엇으로 검증됐는지 확인할 수
있다(확인 가능성). gate3 판정은 실패 기록도 그대로 싣는다(정직한 검증 이력).

구조는 지금 dict 를 그대로 반영한 기본형(한글 키 무변환): 받는 쪽(팀)이 아직
안 정해졌으므로 이름을 추측해 바꾸지 않는다 — JSON↔리포트↔검증 문장이 같은
어휘로 대조되고, 팀 요청이 오면 매핑은 이 모듈 한 곳에서 한다.
"""

from __future__ import annotations

import json
from uuid import UUID

from ..schemas import GateResult

# 페이로드 스키마 버전. **깨는** 변경(필드 삭제·의미 변경·타입 변경)에만 +1 —
# 저장된 JSON 을 불러오는 쪽이 세대를 구분할 열쇠. 필드 **추가**는 하위 호환이라
# 버전을 올리지 않는다(옛 소비자는 새 키를 무시하면 그만). storage-spec.md 참조.
PAYLOAD_VERSION = 1


def derive_data_status(signals: dict | None) -> str:
    """데이터 가용성 상태 — 공통 lexicon(ok | data_limited). 옮겨 담기지 새 판정 아님.

    코어(매매동향)는 리포트가 존재하면 항상 있다: 수집 실패면 예외로 멈춰
    저장될 리포트가 없다(graph.collect_node). 따라서 저장되는 리포트의
    "제한"은 심화 데이터 결측으로만 생긴다. 정직한 단일 신호는 `price_daily`
    (일별시세)의 유무다 — 없으면 시세표와 한도소진율이 함께 빠진 축소 리포트다.

    검증(게이트) 축과 분리한다: 게이트2 실패는 verification.gate2_passed·
    outcome 가 이미 표현하므로 data_status 로 중복 인코딩하지 않는다(데이터
    가용성 ≠ 검증 결과). inst_detail None 은 다수 종목의 정상 상태라 신호로
    쓰지 않는다. 값 어휘는 백엔드 공통 관례(technical·news 가 저장하는
    "data_limited")를 그대로 재사용한다 — flow 전용 신조어를 만들지 않는다.
    """
    price_daily = (signals or {}).get("price_daily")
    return "data_limited" if price_daily is None else "ok"


def build_payload(
    signals: dict,
    meta: dict,
    gate1: GateResult | None,
    gate2: GateResult | None,
    gate3: GateResult | None = None,
    interpretation: str | None = None,
    report_id: UUID | None = None,
    *,
    regen_count: int = 0,
    provider: str | None = None,
    model: str | None = None,
    trace_id: UUID | str | None = None,
) -> dict:
    """검증된 조각들을 JSON 호환 dict 로 조립한다 (옮겨 담기만).

    interpretation 은 게이트3 통과분만 싣는다 — render_node 와 같은 규칙
    (두 출구 일관). 이것이 이 모듈의 유일한 판정이며, 새 판정이 아니라
    같은 규칙의 재적용이다. gate3 판정 자체는 실패여도 그대로 싣는다.

    저장 계약(storage-spec.md) 대응 추가 필드 — 모두 이미 아는 값을 옮겨 담을
    뿐 새 계산이 아니다:
    - trace_id: 상관관계 ID. 기본 = report_id(슈퍼바이저가 상위 ID를 주면 그걸로).
    - verification.outcome / interpretation_meta.source: gate3 통과 여부의
      재표현("explained"/"llm" vs "fact_only"/"fallback") — interpretation 필터와
      같은 규칙의 재적용이지 새 판정이 아니다.
    - verification.regen_count: state.explain_retries(게이트3 재시도 횟수).
    - interpretation_meta.provider/model: 해석 LLM 식별. 해석이 실린 경우에만
      싣는다(interpretation null 이면 provider/model 도 null — 출처와 정합).
    - data_status: 데이터 가용성(ok|data_limited). derive_data_status 참조 —
      signals 유무의 재표현이지 새 계산이 아니다.
    """
    passed3 = gate3 is not None and gate3.passed
    rid = str(report_id) if report_id else None
    tid = str(trace_id) if trace_id else rid   # 기본 = report_id
    return {
        "version": PAYLOAD_VERSION,
        "report_id": rid,                # UUID→str (유일한 실변환)
        "trace_id": tid,
        "data_status": derive_data_status(signals),  # ok | data_limited (공통 lexicon)
        "meta": meta,                    # base_date 는 이미 ISO 문자열(호출부 책임)
        "signals": signals,              # compute_signals dict 그대로 (한글 키 포함)
        "verification": {
            "gate1": gate1.model_dump() if gate1 else None,
            "gate2": gate2.model_dump() if gate2 else None,
            "gate3": gate3.model_dump() if gate3 else None,
            "outcome": "explained" if passed3 else "fact_only",
            "regen_count": regen_count,
        },
        "interpretation": interpretation if passed3 else None,
        "interpretation_meta": {
            "source": "llm" if passed3 else "fallback",
            "provider": provider if passed3 else None,
            "model": model if passed3 else None,
        },
    }


def to_json(payload: dict) -> str:
    """payload → JSON 문자열. 한글 키·값이 그대로 보이게 ensure_ascii=False."""
    return json.dumps(payload, ensure_ascii=False)
