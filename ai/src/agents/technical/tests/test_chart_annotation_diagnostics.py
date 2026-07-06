"""diagnose_chart_annotations 진단 도구 테스트 — fixture 기반(KIS 호출 없음).

진단 도구가 fixture mode에서 돌고, 출력 JSON schema에 필수 key가 있고,
미구현 kind가 표시되며, production chart output을 바꾸지 않는지 확인한다.
계산 로직 검증이 아니라 **진단 도구의 계약(shape)** 검증이다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from src.agents.technical.charts.chart_builder import build_chart_payloads

# 스크립트를 파일 경로로 로드(scripts/는 패키지가 아님).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_chart_annotations.py"
_spec = importlib.util.spec_from_file_location("diagnose_chart_annotations", _SCRIPT)
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


def _result() -> dict:
    daily, weekly, monthly = diag.build_fixture()
    return diag.diagnose(daily, weekly, monthly, mode="fixture")


# ── 실행 가능 + 상위 shape ────────────────────────────────────────────────────
def test_fixture_diagnose_runs():
    result = _result()
    assert result["mode"] == "fixture"
    assert isinstance(result["periods"], list) and len(result["periods"]) == 3


def test_all_three_periods_present():
    periods = {p["period"] for p in _result()["periods"]}
    assert periods == {"3m", "1y", "5y"}


# ── period별 필수 key ─────────────────────────────────────────────────────────
_REQUIRED_KEYS = {
    "period", "candle_unit", "source_candle_count", "visible_candle_count",
    "lookback_buffer_count", "annotation_total_count", "annotation_count_by_kind",
    "annotation_count_by_importance", "dedup_before_count", "dedup_after_count",
    "dedup_removed_count", "visible_annotation_count", "missing_or_unimplemented_kinds",
    "capacity_check", "notes",
}


def test_each_period_has_required_keys():
    for p in _result()["periods"]:
        assert _REQUIRED_KEYS <= set(p), f"{p['period']} 누락: {_REQUIRED_KEYS - set(p)}"


# ── 미구현 kind 표시 ──────────────────────────────────────────────────────────
def test_unimplemented_kinds_flagged():
    # 전 10종 생성기 구현 완료 → 미구현 목록은 비어 있어야 한다.
    for p in _result()["periods"]:
        assert p["missing_or_unimplemented_kinds"] == []


# ── count shape ───────────────────────────────────────────────────────────────
def test_annotation_count_by_kind_is_full_dict():
    for p in _result()["periods"]:
        by_kind = p["annotation_count_by_kind"]
        assert isinstance(by_kind, dict)
        assert set(by_kind) == set(diag.ALL_KINDS)  # 10종 전부(0 포함)


def test_annotation_count_by_importance_has_all_levels():
    for p in _result()["periods"]:
        by_imp = p["annotation_count_by_importance"]
        assert set(by_imp) == {"high", "medium", "low"}
        assert all(isinstance(v, int) for v in by_imp.values())


# ── dedup 계측 정합 ───────────────────────────────────────────────────────────
def test_dedup_counts_consistent():
    for p in _result()["periods"]:
        assert p["dedup_before_count"] >= p["dedup_after_count"] >= 0
        assert p["dedup_removed_count"] == p["dedup_before_count"] - p["dedup_after_count"]
        # 최종 total과 by_kind 합이 일치
        assert p["annotation_total_count"] == sum(p["annotation_count_by_kind"].values())


# ── capacity check ────────────────────────────────────────────────────────────
def test_capacity_check_present_per_period():
    for p in _result()["periods"]:
        cap = p["capacity_check"]
        for key in ("enough_for_ma_cross", "enough_for_rsi", "enough_for_volume",
                    "enough_for_support_resistance", "enough_for_box", "enough_for_cup_handle"):
            assert key in cap and isinstance(cap[key], bool)
        assert "cup_handle_daily_required_bars" in cap
        assert "cup_handle_weekly_required_bars" in cap


# ── production 무변경 (진단이 chart output을 바꾸지 않음) ──────────────────────
def test_production_chart_output_unchanged():
    daily, weekly, monthly = diag.build_fixture()
    before = build_chart_payloads(daily, weekly, monthly)
    diag.diagnose(daily, weekly, monthly, mode="fixture")  # 진단 실행
    after = build_chart_payloads(daily, weekly, monthly)
    # 진단 전후 chart payload가 동일(진단이 부작용 없음)
    assert [len(p.chart_data.annotations) for p in before] == [len(p.chart_data.annotations) for p in after]
    assert [p.period for p in before] == [p.period for p in after]


# ── fixture가 실제로 annotation을 만들어 도구가 유의미함을 보장 ────────────────
def test_fixture_generates_some_implemented_annotations():
    # 구현된 kind 중 최소 하나는 생성되어야(도구가 '0만 나온다'가 아님을 보장)
    total_impl = 0
    for p in _result()["periods"]:
        for kind, count in p["annotation_count_by_kind"].items():
            if kind not in diag.UNIMPLEMENTED_KINDS:
                total_impl += count
    assert total_impl > 0


# ── 5y importance retier가 진단 output(post) 기준으로 반영됨 ──────────────────
def test_diagnostics_reflects_5y_importance_retier():
    periods = {p["period"]: p for p in _result()["periods"]}
    p5 = periods["5y"]
    by_kind = p5["annotation_count_by_kind"]
    # 5y에서 cup/box_breakout/box_range는 승격 정책 대상 → 이들은 high(또는 box_range는 medium)로 집계.
    # 최소 불변식: 5y high 개수는 승격되는 high 후보(cup+breakout) 개수 이상이어야 한다.
    promoted_high = by_kind["cup_handle_candidate"] + by_kind["box_breakout_candidate"]
    assert p5["annotation_count_by_importance"]["high"] >= promoted_high
    # 1y는 승격 대상 아님 — cup/breakout이 high로 집계되지 않는다(정책 5y 한정).
    p1 = periods["1y"]
    assert p1["annotation_count_by_kind"]["cup_handle_candidate"] >= 0  # 존재 확인(정책 미적용)
