"""JSON 출구(export/to_json) — "직렬화지 재계산 아님" 규율 검증.

원리: build_payload 는 옮겨 담기만 한다 — 값 동일성, 원본 무변형,
  게이트3 필터(render 와 두 출구 일관), dumps 왕복(전 필드 JSON 호환)을
  테스트로 고정한다. signals 에 numpy 등 비호환 타입이 새어들면
  왕복 테스트가 즉시 빨간불이 된다.
"""

import copy
import json
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fixtures import df_foreign_5day_streak  # noqa: E402

from agents.flow import graph  # noqa: E402
from agents.flow.core import signals as sig  # noqa: E402
from agents.flow.core.verify_input import verify_input  # noqa: E402
from agents.flow.core.verify_rules import verify_signals  # noqa: E402
from agents.flow.export.to_json import PAYLOAD_VERSION, build_payload, to_json  # noqa: E402
from agents.flow.schemas import AgentInput, GateResult, SupplyDemandState  # noqa: E402

# 재료는 실제 부품으로 한 번만 계산 — build_payload 가 재계산하지 않음을 값 대조로 확인.
_NOW = datetime(2026, 7, 6, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
_INPUT = AgentInput(query="", stock_name="삼성전자", ticker="005930")
_SIGNALS = sig.compute_signals(df_foreign_5day_streak)
_GATE1, _, _ = verify_input(_INPUT, date(2026, 7, 3), now=_NOW)
_GATE2 = verify_signals(df_foreign_5day_streak, _SIGNALS)
_META = {"stock_name": "삼성전자", "ticker": "005930",
         "market": "KOSPI200", "base_date": "2026-07-03"}
_G3_PASS = GateResult(gate=3, passed=True, checks=["해석↔팩트 일치"])
_G3_FAIL = GateResult(gate=3, passed=False, failures=["재시도 소진"])


def test_payload_carries_values_verbatim():
    """조립 결과가 원본 값 그대로다 — 재계산·변형 없음(UUID→str 만 예외)."""
    rid = uuid4()
    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_PASS, "해석 문장", rid)
    assert p["version"] == PAYLOAD_VERSION
    assert p["report_id"] == str(rid)
    assert p["meta"] == _META
    assert p["signals"] == _SIGNALS                          # dict 그대로
    assert p["verification"]["gate1"]["checks"] == _GATE1.checks
    assert p["verification"]["gate2"]["passed"] is True
    assert p["verification"]["gate2"]["checks"] == _GATE2.checks  # 검증 전문 포함
    assert p["interpretation"] == "해석 문장"


def test_interpretation_follows_gate3_rule():
    """게이트3 통과분만 싣는다(render 와 두 출구 일관). 실패 기록은 정직하게 남는다."""
    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_FAIL, "탈락한 해석", uuid4())
    assert p["interpretation"] is None
    assert p["verification"]["gate3"]["passed"] is False     # 이력은 그대로

    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, None, "미검증 해석", uuid4())
    assert p["interpretation"] is None                       # gate3 부재 = 미검증 → 안 싣는다
    assert p["verification"]["gate3"] is None


def test_trace_id_defaults_to_report_id():
    """trace_id 기본값 = report_id(상관관계 ID). 명시하면 그 값을 쓴다."""
    rid = uuid4()
    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_PASS, "해석", rid)
    assert p["trace_id"] == str(rid) == p["report_id"]

    tid = uuid4()
    p2 = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_PASS, "해석", rid, trace_id=tid)
    assert p2["trace_id"] == str(tid) and p2["report_id"] == str(rid)


def test_storage_fields_follow_gate3_rule():
    """저장 계약 필드(outcome·source·provider·model)가 gate3 규칙과 정합.

    통과 → explained/llm + 모델 식별. 미통과 → fact_only/fallback + 식별 null
    (interpretation null 과 provider/model null 이 함께 움직인다 — 출처 정합)."""
    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_PASS, "해석", uuid4(),
                      regen_count=1, provider="openai", model="gpt-4o-mini")
    assert p["verification"]["outcome"] == "explained"
    assert p["verification"]["regen_count"] == 1
    assert p["interpretation_meta"] == {
        "source": "llm", "provider": "openai", "model": "gpt-4o-mini"}

    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_FAIL, "탈락", uuid4(),
                      regen_count=2, provider="openai", model="gpt-4o-mini")
    assert p["verification"]["outcome"] == "fact_only"
    assert p["verification"]["regen_count"] == 2
    assert p["interpretation_meta"] == {
        "source": "fallback", "provider": None, "model": None}


def test_payload_round_trips_through_json():
    """전 필드가 JSON 왕복 가능 + 한글 키가 이스케이프 없이 그대로."""
    p = build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_PASS, "해석", uuid4())
    text = to_json(p)
    back = json.loads(text)
    assert back["signals"]["alignment"] == _SIGNALS["alignment"]
    assert back["signals"]["daily"] == _SIGNALS["daily"]
    assert '"개인"' in text and "\\uac1c" not in text        # 한글 원문(ensure_ascii=False)


def test_build_payload_does_not_mutate_inputs():
    """옮겨 담기만 — 입력 dict·GateResult 를 절대 바꾸지 않는다."""
    signals_before = copy.deepcopy(_SIGNALS)
    gate2_before = _GATE2.model_copy(deep=True)
    build_payload(_SIGNALS, _META, _GATE1, _GATE2, _G3_PASS, "해석", uuid4())
    assert _SIGNALS == signals_before
    assert _GATE2 == gate2_before


def test_run_wires_payload_into_agent_output(monkeypatch):
    """배선 A: run() 이 최종 state 를 payload 로 조립해 AgentOutput 에 싣는다."""
    from agents.flow import agent

    monkeypatch.setattr(graph, "fetch_supply_demand",
                        lambda base_date, ticker: (df_foreign_5day_streak, "KOSPI200"))
    monkeypatch.setattr(graph, "fetch_daily_quotes", lambda base_date, ticker: None)
    # 게이트2 강제 실패 → explain(LLM) 없이 render 후퇴 — 외부 경계 없이 배선만 본다.
    monkeypatch.setattr(
        graph, "verify_signals",
        lambda df, signals, ownership=None, quotes=None: GateResult(
            gate=2, passed=False, failures=["강제 실패(테스트)"]),
    )

    out = agent.run(base_date=date(2026, 7, 3))
    p = out.payload
    assert p is not None and p["version"] == PAYLOAD_VERSION
    assert p["meta"]["market"] == "KOSPI200"                 # state 의 market 이 실림
    assert p["verification"]["gate2"]["passed"] is False     # 실패도 정직하게
    assert p["interpretation"] is None                       # 해석 없던 경로
    assert p["signals"]["alignment"] in ("동반매수", "동반매도", "엇갈림")
    # 저장 계약 필드도 실배선으로 채워진다(게이트2 실패 경로 = fact_only).
    assert p["trace_id"] == p["report_id"]                   # 기본 = report_id
    assert p["verification"]["outcome"] == "fact_only"
    assert p["verification"]["regen_count"] == 0             # explain 미진입
    assert p["interpretation_meta"]["source"] == "fallback"
    assert p["interpretation_meta"]["provider"] is None      # 해석 없으니 식별도 null
    json.loads(to_json(p))                                   # 실배선 산출물도 왕복 가능