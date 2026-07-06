"""수동 smoke — KIS 주식당일분봉조회(inquire-time-itemchartprice) raw 응답·fetcher 가정 검증.

목적(단위 테스트 아님): 실제 KIS 분봉 응답의 정렬 방향·30건 경계·페이징 가정·output1/output2
필드 안정성을 사람이 확인하고, 결과를 `kis_mapping.md §12.9`에 옮길 수 있게 JSON으로 남긴다.

  KIS  : 실제 호출 (raw는 kis_client._call_minute_chart, normalized는 fetch_minute_ohlcv)
  저장 : src/agents/technical/scripts/intraday_smoke_output/ (raw_/normalized_/checklist_ JSON, secret 미포함)

실행:
  cd ai
  uv run python src/agents/technical/scripts/smoke_intraday_minute.py --ticker 373220
  uv run python src/agents/technical/scripts/smoke_intraday_minute.py --ticker 373220 --input-hour 153000
  uv run python src/agents/technical/scripts/smoke_intraday_minute.py --ticker 373220 --limit 120
  uv run python src/agents/technical/scripts/smoke_intraday_minute.py --ticker 373220 --rate-check

pytest/CI에는 포함하지 않는다(real KIS env 필요). 주문/계좌 API·KIS_ACCOUNT_NO는 쓰지 않는다.
장중/장전/장후/휴장 응답은 각 세션 시각에 직접 실행해 executed_at과 함께 기록한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

# 스탠드얼론 스크립트라 ai/ 를 sys.path에 올려 `src...` import가 되게 한다.
# 이 파일 위치: ai/src/agents/technical/scripts/ → parents[4] = ai/
_AI_ROOT = Path(__file__).resolve().parents[4]
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from src.agents.technical.config import REQUIRED_ENV_KEYS  # noqa: E402
from src.agents.technical.services import kis_client as kc  # noqa: E402

_DEFAULT_TICKER = "373220"  # LG에너지솔루션 (MVP allowlist·고유동성). 005930은 allowlist 밖 → raw만.
_DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "intraday_smoke_output"
_OUT1_KEYS = ("stck_prdy_clpr", "stck_prpr", "acml_vol", "acml_tr_pbmn", "hts_kor_isnm")


# ─────────────────────────────────────────────────────────────────────────────
# env (secret 미출력 — 존재 여부만)
# ─────────────────────────────────────────────────────────────────────────────
def _check_env() -> bool:
    import os
    print("── env (KIS) ─────────────────────────────────")
    for key in REQUIRED_ENV_KEYS:
        print(f"  {key:15s}: {'OK' if os.getenv(key) else 'MISSING'}")
    try:
        kc.load_kis_settings()
        return True
    except RuntimeError as exc:
        print(f"  [env] {exc}")  # 누락 키 이름만 (secret 없음)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 1. raw 단일 호출 (_call_minute_chart — 정규화 전)
# ─────────────────────────────────────────────────────────────────────────────
def _raw_stage(ticker: str, input_hour: str, client: httpx.Client) -> tuple[dict, dict]:
    settings = kc.load_kis_settings()
    token = kc.get_access_token(client=client)
    data = kc._call_minute_chart(settings, token, ticker, input_hour, client)

    output2 = data.get("output2") if isinstance(data.get("output2"), list) else []
    count = len(output2)
    first_time = output2[0].get("stck_cntg_hour") if count else None
    last_time = output2[-1].get("stck_cntg_hour") if count else None
    if count <= 1:
        order = "single_or_empty"
    elif first_time < last_time:
        order = "ascending"
    elif first_time > last_time:
        order = "descending"
    else:
        order = "flat"

    out1 = data.get("output1")
    out1 = out1[0] if isinstance(out1, list) and out1 else (out1 if isinstance(out1, dict) else {})
    summary = {
        "rt_cd": data.get("rt_cd"),
        "msg_cd": data.get("msg_cd"),
        "msg1": data.get("msg1"),
        "output1": {k: out1.get(k) for k in _OUT1_KEYS},
        "output2_count": count,
        "first_time": first_time,
        "last_time": last_time,
        "order_direction": order,
        "le_30": count <= 30,
        "fid_combo_ok": data.get("rt_cd") == "0",  # FID_PW_DATA_INCU_YN=Y / FID_ETC_CLS_CODE="" 수용
    }
    return data, summary


# ─────────────────────────────────────────────────────────────────────────────
# 2. normalized fetch (fetch_minute_ohlcv — allowlist 밖이면 skip)
# ─────────────────────────────────────────────────────────────────────────────
def _normalized_stage(ticker: str, as_of: datetime | None, input_hour: str | None,
                      limit: int | None) -> tuple[dict, dict]:
    try:
        result = kc.fetch_minute_ohlcv(ticker, as_of=as_of, input_hour=input_hour, limit=limit)
    except kc.OutOfScopeTickerError:
        skip = {"skipped": "out_of_scope_ticker (MVP allowlist 밖 — raw만 확인)"}
        return skip, skip

    ts = [c.timestamp for c in result.candles]
    payload = {
        "candles": [c.model_dump() for c in result.candles],
        "previous_close": result.previous_close,
        "latest_price": result.latest_price,
        "cumulative_volume": result.cumulative_volume,
        "cumulative_trading_value": result.cumulative_trading_value,
    }
    summary = {
        "candle_count": len(ts),
        "first_timestamp": ts[0] if ts else None,
        "last_timestamp": ts[-1] if ts else None,
        "is_sorted_ascending": ts == sorted(ts),
        "has_duplicates": len(ts) != len(set(ts)),
        "dedupe_count": len(set(ts)),
        "estimated_page_count": (len(ts) + 29) // 30 if ts else 0,  # 30건/호출 추정(정확값 아님)
        "previous_close": result.previous_close,
        "latest_price": result.latest_price,
        "cumulative_volume": result.cumulative_volume,
        "cumulative_trading_value": result.cumulative_trading_value,
        "trading_value_all_none": all(c.trading_value is None for c in result.candles),
        "volume_samples": [c.volume for c in result.candles[:5]],
    }
    return payload, summary


# ─────────────────────────────────────────────────────────────────────────────
# rate-check (소량 3~5회 연속 — 과도 금지)
# ─────────────────────────────────────────────────────────────────────────────
def _rate_check(ticker: str, input_hour: str, client: httpx.Client, n: int) -> list[dict]:
    settings = kc.load_kis_settings()
    token = kc.get_access_token(client=client)
    results = []
    for i in range(n):
        try:
            data = kc._call_minute_chart(settings, token, ticker, input_hour, client)
            results.append({"call": i + 1, "rt_cd": data.get("rt_cd"), "msg_cd": data.get("msg_cd")})
        except kc.KisApiError as exc:
            results.append({"call": i + 1, "error": str(exc)[:120]})
    return results


# ─────────────────────────────────────────────────────────────────────────────
# checklist (kis_mapping §12.9 옮겨쓰기용)
# ─────────────────────────────────────────────────────────────────────────────
def _build_checklist(*, executed_at: str, ticker: str, input_hour: str,
                     raw: dict, norm: dict, rate: object) -> dict:
    skipped = "skipped" in norm
    return {
        "executed_at": executed_at,
        "ticker": ticker,
        "input_hour": input_hour,
        "raw_output2_count": raw["output2_count"],
        "raw_order_direction": raw["order_direction"],
        "raw_first_time": raw["first_time"],
        "raw_last_time": raw["last_time"],
        "normalized_candle_count": None if skipped else norm["candle_count"],
        "normalized_first_timestamp": None if skipped else norm["first_timestamp"],
        "normalized_last_timestamp": None if skipped else norm["last_timestamp"],
        "normalized_is_sorted_ascending": None if skipped else norm["is_sorted_ascending"],
        "normalized_has_duplicates": None if skipped else norm["has_duplicates"],
        "previous_close_present": None if skipped else (norm["previous_close"] is not None),
        "latest_price_present": None if skipped else (norm["latest_price"] is not None),
        "cumulative_volume_present": None if skipped else (norm["cumulative_volume"] is not None),
        "cumulative_trading_value_present": None if skipped else (norm["cumulative_trading_value"] is not None),
        "trading_value_policy_ok": None if skipped else norm["trading_value_all_none"],
        "fid_combo_ok": raw["fid_combo_ok"],
        "rate_check_result": rate,
        "notes": (
            "005930 등 allowlist 밖 ticker는 normalized 단계 skip(raw만). "
            "cntg_vol은 첫 체결 전 직전 분봉 체결량 표기 가능(volume spike 한계, kis_mapping §12.6). "
            "raw_order_direction이 descending이면 fetcher가 오름차순 정규화함(정합)."
        ),
    }


def _save(out_dir: Path, name: str, data: object) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="KIS 주식당일분봉조회 manual smoke (raw + normalized)")
    p.add_argument("--ticker", default=_DEFAULT_TICKER, help="종목코드(6자리). allowlist 밖이면 normalized skip")
    p.add_argument("--as-of", dest="as_of", default=None, help="기준 시각(ISO). 생략 시 현재")
    p.add_argument("--input-hour", dest="input_hour", default=None, help="FID_INPUT_HOUR_1(HHMMSS)")
    p.add_argument("--limit", type=int, default=None, help="normalized 최신 N개만")
    p.add_argument("--rate-check", dest="rate_check", action="store_true", help="소량 연속 호출(3~5회)")
    p.add_argument("--rate-n", dest="rate_n", type=int, default=3, help="rate-check 호출 수(3~5)")
    p.add_argument("--output-dir", dest="out_dir", default=str(_DEFAULT_OUT_DIR))
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not _check_env():
        print("[smoke] ai/.env 에 KIS_API_KEY / KIS_API_SECRET / KIS_BASE_URL 설정 후 재실행하세요.",
              file=sys.stderr)
        return 1

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    input_hour = kc._resolve_input_hour(as_of, args.input_hour)
    rate_n = max(3, min(5, args.rate_n))  # 3~5로 clamp (과도 금지)
    executed_at = datetime.now().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)

    print(f"\n[smoke] ticker={args.ticker} input_hour={input_hour} executed_at={executed_at}")
    client = httpx.Client(timeout=kc.KIS_TIMEOUT_SECONDS)
    try:
        raw_data, raw = _raw_stage(args.ticker, input_hour, client)
        norm_payload, norm = _normalized_stage(args.ticker, as_of, args.input_hour, args.limit)
        rate = _rate_check(args.ticker, input_hour, client, rate_n) if args.rate_check else "skipped"
    finally:
        client.close()

    checklist = _build_checklist(
        executed_at=executed_at, ticker=args.ticker, input_hour=input_hour,
        raw=raw, norm=norm, rate=rate,
    )

    print("\n── raw (single call) ─────────────────────────")
    for k in ("rt_cd", "msg_cd", "output2_count", "first_time", "last_time",
              "order_direction", "le_30", "fid_combo_ok"):
        print(f"  {k:16s}: {raw[k]}")
    print(f"  output1        : {raw['output1']}")
    print("\n── normalized (fetch_minute_ohlcv) ───────────")
    if "skipped" in norm:
        print(f"  {norm['skipped']}")
    else:
        for k in ("candle_count", "first_timestamp", "last_timestamp", "is_sorted_ascending",
                  "has_duplicates", "estimated_page_count", "previous_close", "latest_price",
                  "cumulative_volume", "cumulative_trading_value", "trading_value_all_none"):
            print(f"  {k:24s}: {norm[k]}")
    print(f"\n── rate-check ────────────────────────────────\n  {rate}")

    raw_path = _save(out_dir, f"raw_{args.ticker}_{stamp}.json", raw_data)
    norm_path = _save(out_dir, f"normalized_{args.ticker}_{stamp}.json", norm_payload)
    chk_path = _save(out_dir, f"checklist_{args.ticker}_{stamp}.json", checklist)
    print(f"\n[smoke] saved:\n  {raw_path}\n  {norm_path}\n  {chk_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
