"""수동 end-to-end smoke — real KIS + fake LLM으로 run_technical_agent 전체 흐름 확인.

목적(단위 테스트 아님): 공식 진입점 `run_technical_agent()`가 실제 KIS D/W/M 시세로
파이프라인을 끝까지 돌려 `TechnicalAgentOutput`을 만들고 JSON으로 저장되는지 사람이 확인한다.

  KIS  : 실제 호출 (기존 kis_client/supervisor 경로만 — 이 스크립트는 KIS API를 직접 부르지 않음)
  LLM  : fake (payload-aware — 프롬프트의 코드 확정 라벨을 읽어 검증 ③ 1차 통과하는 문장 생성)
  저장 : src/agents/technical/scripts/technical_smoke_output/ 에 UTF-8 JSON (secret 미저장)

실행:
  cd ai
  uv run python src/agents/technical/scripts/smoke_technical_agent.py
  uv run python src/agents/technical/scripts/smoke_technical_agent.py --ticker 373220 --as-of 2026-07-06

pytest/CI에는 포함하지 않는다(real KIS env 필요). 검증 로직은 우회하지 않으며 금지어를 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 스탠드얼론 스크립트라 ai/ 를 sys.path에 올려 `src...` import가 되게 한다.
# 이 파일 위치: ai/src/agents/technical/scripts/ → parents[4] = ai/
_AI_ROOT = Path(__file__).resolve().parents[4]
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from src.agents.technical.agent import run_technical_agent  # noqa: E402
from src.agents.technical.config import dev_stock_name, is_supported_ticker, load_kis_settings  # noqa: E402
from src.agents.technical.observability.keyword_rules import (  # noqa: E402
    CONFIDENCE_LABELS,
    CONSENSUS_LABELS,
    INDICATOR_LABELS,
    REGIME_LABELS,
    RISK_LABELS,
    SIGNAL_LABELS,
)
from src.agents.technical.schemas.contracts import (  # noqa: E402
    TechnicalAgentInput,
    TechnicalAgentOutput,
)
from src.agents.technical.schemas.enums import (  # noqa: E402
    AlignmentFlag,
    ConfidenceLevel,
    Consensus,
    DataStatus,
    GenerationSource,
    IndicatorType,
    Regime,
    RiskFlag,
    Signal,
    VerificationOutcome,
)

_DEFAULT_TICKER = "373220"
_DEFAULT_QUERY = "LG에너지솔루션 기술적 흐름을 분석해줘"
_DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "technical_smoke_output"

_FOCUS_RESPONSE = json.dumps(
    {
        "analysis_focus": ["trend", "momentum", "volume", "support_resistance", "risk"],
        "focus_summary": "추세·모멘텀·거래량·지지저항·리스크 관찰점을 함께 확인합니다.",
    },
    ensure_ascii=False,
)


# ─────────────────────────────────────────────────────────────────────────────
# payload-aware fake LLM
# ─────────────────────────────────────────────────────────────────────────────
class SmokeFakeLlm:
    """프롬프트 종류에 따라 응답을 분기하는 fake. 실제 LLM/네트워크 호출 없음.

    분기 기준은 프롬프트가 요구하는 출력 스키마 키:
      - "interpretation_text" → interpret/regenerate (payload의 확정 라벨을 읽어 검증 통과 문장 생성)
      - "analysis_focus"      → focus_analysis (정적 정상 응답)
      - "normalized_question" → normalize_question (ticker 회사명 포함)
    """

    def __init__(self, company_name: str) -> None:
        self._company = company_name

    def complete(self, prompt: str) -> str:
        if "interpretation_text" in prompt:  # interpret_report / regenerate_report
            return _build_interpretation(_extract_payload(prompt))
        if "analysis_focus" in prompt:  # focus_analysis
            return _FOCUS_RESPONSE
        if "normalized_question" in prompt:  # normalize_question
            return json.dumps(
                {"normalized_question": (
                    f"{self._company}의 최근 시세·거래량·기술적 신호를 중심으로 "
                    f"현재 차트 국면과 리스크 관찰점을 분석합니다."
                )},
                ensure_ascii=False,
            )
        raise RuntimeError("알 수 없는 프롬프트 유형(fake LLM 분기 실패)")


def _extract_payload(prompt: str) -> dict:
    """interpret 프롬프트에 렌더된 코드 확정값 payload(JSON)를 뽑는다.

    프롬프트 안의 ```json 블록 중 `final_regime` 키를 가진 것(= 실제 payload)을 고른다.
    (출력 형식 예시 블록에는 final_regime이 없다.)
    """
    for block in re.findall(r"```json\s*(.*?)\s*```", prompt, re.DOTALL):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "final_regime" in data:
            return data
    raise RuntimeError("interpret 프롬프트에서 payload를 찾지 못했습니다")


def _build_interpretation(payload: dict) -> str:
    """확정 라벨을 자연어로 echo. 검증 ③(라벨 대표어·신호·confidence·risk 언급)을 1차 통과하도록.

    코드 확정값을 바꾸지 않고 문장만 만든다. 금지어·매수/매도 표현 없음.
    """
    final_regime = Regime(payload["final_regime"])
    consensus = Consensus(payload["consensus"])
    conf_level = ConfidenceLevel(payload["confidence_level"])
    alignment = AlignmentFlag(payload["alignment_flag"])
    risk_flags = [RiskFlag(item["flag"]) for item in payload.get("risk_items", [])]

    parts = [
        f"현재 차트는 {REGIME_LABELS[final_regime]} 국면으로 관찰되며, "
        f"종합 신호는 {CONSENSUS_LABELS[consensus]} 수준으로 해석됩니다.",
        f"신뢰도는 {CONFIDENCE_LABELS[conf_level]} 수준입니다.",
    ]
    if alignment == AlignmentFlag.ALIGNED:
        parts.append("상위 추세와 정합합니다.")
    elif alignment == AlignmentFlag.COUNTER_TREND:
        parts.append("상위 추세와 역행합니다.")
    if risk_flags:
        parts.append(
            "주요 관찰 요인으로 " + "·".join(RISK_LABELS[f] for f in risk_flags)
            + "이(가) 함께 확인됩니다."
        )
    parts.append("이 내용은 투자 판단을 대신하지 않으며, 기술적 지표 기반 참고 정보입니다.")

    details = [
        {
            "indicator": s["indicator"],
            "detail": (
                f"{INDICATOR_LABELS[IndicatorType(s['indicator'])]} 지표는 "
                f"{SIGNAL_LABELS[Signal(s['signal'])]} 신호로 확인됩니다."
            ),
        }
        for s in payload["technical_signals"]
    ]
    return json.dumps({"interpretation_text": " ".join(parts), "details": details}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# 검증·요약·저장
# ─────────────────────────────────────────────────────────────────────────────
class SmokeValidationError(RuntimeError):
    """smoke 성공 조건 위반. assert(python -O에서 제거) 대신 명시적 예외를 쓴다."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeValidationError(message)


def _validate_basic(output: TechnicalAgentOutput, *, ticker: str, as_of: datetime) -> None:
    """모드 무관 계약 검증. 실패 시 SmokeValidationError."""
    _require(output.ticker == ticker, f"ticker={output.ticker}, expected {ticker}")
    _require(output.source == "KIS", f"source={output.source}, expected KIS")
    _require(output.as_of == as_of, f"as_of={output.as_of.isoformat()}, expected {as_of.isoformat()}")
    _require(bool(output.interpretation.text), "interpretation.text is empty")
    output.model_dump_json()  # 직렬화 불가면 그대로 전파(실제 실패)


def _strict_failures(output: TechnicalAgentOutput) -> list[str]:
    """정상 전체 경로 조건 위반 목록(비어있으면 정상 경로 통과)."""
    checks: list[tuple[bool, str]] = [
        (output.data_status == DataStatus.NORMAL, f"data_status={output.data_status.value}, expected normal"),
        (output.signal is not None, "signal=None, expected not None"),
        (bool(output.technical_signals), "technical_signals is empty"),
        (output.risk is not None, "risk=None, expected not None"),
        (len(output.charts) == 3, f"charts={len(output.charts)}, expected 3"),
        (output.interpretation.source == GenerationSource.LLM,
         f"interpretation.source={output.interpretation.source.value}, expected llm"),
        (output.verification.outcome == VerificationOutcome.PASSED,
         f"verification.outcome={output.verification.outcome.value}, expected passed"),
        (output.verification.regen_count == 0,
         f"regen_count={output.verification.regen_count}, expected 0"),
        (all(ts.detail_source == GenerationSource.LLM for ts in output.technical_signals),
         "일부 technical_signals[].detail_source != llm"),
    ]
    return [message for ok, message in checks if not ok]


def _print_summary(output: TechnicalAgentOutput, out_path: Path, *,
                   degraded: bool, failures: list[str]) -> None:
    if degraded:
        print("Mode: DEGRADED ALLOWED")
        print("This output is valid for inspection but does not prove the full normal pipeline path.")
        for message in failures:
            print(f"  degraded: {message}")
    signal = output.signal
    risk_count = len(output.risk.items) if output.risk else 0
    print("── technical agent smoke summary ─────────────────────────")
    print(f"  ticker         : {output.ticker}")
    print(f"  as_of          : {output.as_of.isoformat()}")
    print(f"  data_status    : {output.data_status.value}")
    print(f"  final_regime   : {output.regime.final_regime.value}")
    print(f"  consensus      : {signal.consensus.value if signal else '-'}")
    print(f"  signal_score   : {signal.signal_score if signal else '-'}")
    print(f"  confidence     : {signal.confidence if signal else '-'}")
    print(f"  interpretation : source={output.interpretation.source.value}")
    print(f"  risk flags     : {risk_count}")
    print(f"  chart payloads : {len(output.charts)}")
    print(f"  output file    : {out_path}")
    print("──────────────────────────────────────────────────────────")


def _save_output(output: TechnicalAgentOutput, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{output.ticker}_{output.as_of.strftime('%Y%m%d')}_{output.request_id[:12]}.json"
    out_path = out_dir / name
    out_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")
    return out_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Technical agent end-to-end smoke (real KIS + fake LLM)")
    parser.add_argument("--ticker", default=_DEFAULT_TICKER, help="종목코드(6자리). 전체 종목 확장 — allowlist 아님")
    parser.add_argument("--query", default=_DEFAULT_QUERY, help="사용자 질의")
    parser.add_argument("--stock-name", dest="stock_name", default=None,
                        help="backend canonical 종목명(주입). 생략 시 dev 표시명 fallback 또는 코드")
    parser.add_argument("--as-of", dest="as_of", default=None,
                        help="분석 기준일 (YYYY-MM-DD 또는 ISO). 생략 시 현재 시각")
    parser.add_argument("--out-dir", dest="out_dir", default=str(_DEFAULT_OUT_DIR),
                        help="출력 JSON 디렉터리")
    parser.add_argument("--allow-degraded", dest="allow_degraded", action="store_true",
                        help="안전 착지(data_limited/regime_unavailable/template_fallback)도 실패로 보지 않고 "
                             "관찰용으로 저장(정상 경로 증명 아님)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # KIS env 확인(fail-fast, secret 미노출). 실제 호출은 이후 supervisor→kis_client 경로에서만.
    try:
        load_kis_settings()
    except RuntimeError as exc:
        print(f"[smoke] KIS 환경변수가 필요합니다 — {exc}", file=sys.stderr)
        print("[smoke] ai/.env 에 KIS_API_KEY / KIS_API_SECRET / KIS_BASE_URL 을 설정하세요.",
              file=sys.stderr)
        return 1

    if not is_supported_ticker(args.ticker):
        print(f"[smoke] 종목코드 형식 오류(6자리 아님): {args.ticker}", file=sys.stderr)
        return 1

    # 종목명 정본 우선순위: 주입 stock_name → dev 표시명 fallback → ticker 코드.
    stock_name = args.stock_name or dev_stock_name(args.ticker)
    as_of = args.as_of if args.as_of else datetime.now()
    agent_input = TechnicalAgentInput(
        ticker=args.ticker,
        query=args.query,
        stock_name=stock_name,
        request_id=f"smoke_{uuid.uuid4().hex[:12]}",
        as_of=as_of,
    )
    fake_llm = SmokeFakeLlm(company_name=stock_name or args.ticker)

    print(f"[smoke] run_technical_agent 실행 (ticker={args.ticker}, as_of={agent_input.as_of.isoformat()})")
    print("[smoke] real KIS 호출 중 (D/W/M)...")
    output = run_technical_agent(agent_input, llm_client=fake_llm)

    _validate_basic(output, ticker=args.ticker, as_of=agent_input.as_of)
    failures = _strict_failures(output)  # 정상 전체 경로 위반 목록
    degraded = bool(failures)

    if degraded and not args.allow_degraded:
        for message in failures:
            print(f"Smoke validation failed: {message}", file=sys.stderr)
        print("[smoke] 정상 전체 경로가 아닙니다. 데이터/as_of 확인 또는 --allow-degraded 사용.",
              file=sys.stderr)
        return 1

    out_path = _save_output(output, Path(args.out_dir))
    _print_summary(output, out_path, degraded=degraded, failures=failures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
