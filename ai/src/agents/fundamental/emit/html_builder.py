import json
import math
import re
from html import escape
from typing import Any, Literal

from ..core.contract import Evidence
from ..report.formatting import format_metric_value

Audience = Literal["user", "debug"]

LABELS = {
    "strong": "양호",
    "moderate": "중립",
    "weak": "주의",
    "insufficient_data": "데이터 제한",
}

FLAG_DESCRIPTIONS = {
    "MISSING_BPS": "발행주식수를 안정적으로 확보하지 못해 BPS를 산출하지 않았습니다.",
    "NOT_MEANINGFUL_OPERATING_INCOME_GROWTH": "영업이익 성장률을 퍼센트로 표시하면 왜곡될 수 있어 방향성으로 표시했습니다.",
    "NOT_MEANINGFUL_REVENUE_GROWTH": "매출 기준이 비정상적이라 매출 성장률을 퍼센트로 표시하지 않았습니다.",
    "LLM_FALLBACK_OPENAI": "Qwen 실패 후 OpenAI 보조 경로를 사용했습니다.",
    "LLM_FALLBACK_TEMPLATE": "규칙 기반 문장 템플릿으로 안전 착지했습니다.",
    "DERIVED_LIABILITIES": "부채총계가 누락되어 파생 계산했습니다.",
    "STALE_DART_CACHE_FALLBACK": "DART 재조회 실패로 기존 캐시 원문을 사용했습니다.",
    "VERDICT_STABILITY_GUARDED": "결론 문구와 결정론 라벨의 정합성 검토가 필요합니다.",
}


def _fmt(value: Any, unit: str) -> str:
    return format_metric_value(value, unit)


def _item_display(item: dict[str, Any]) -> str:
    display_value = item.get("display_value")
    if display_value not in (None, ""):
        return str(display_value)
    return _fmt(item.get("value"), item.get("unit", ""))


def _value_tone_class(metric: str, item: dict[str, Any]) -> str:
    value = item.get("value")
    if value is None or item.get("status") != "available":
        return "vfr-tone-muted"
    if not isinstance(value, int | float) or isinstance(value, bool):
        return "vfr-tone-muted"
    if metric in {"revenue_growth", "operating_income_growth"}:
        return "vfr-tone-up" if value > 0 else "vfr-tone-down" if value < 0 else "vfr-tone-muted"
    if metric in {"roe", "operating_margin", "net_margin"}:
        return "vfr-tone-positive" if value > 0 else "vfr-tone-negative" if value < 0 else "vfr-tone-muted"
    if metric == "current_ratio":
        return "vfr-tone-positive" if value >= 120 else "vfr-tone-caution" if value >= 80 else "vfr-tone-negative"
    if metric == "debt_ratio":
        if value <= 80:
            return "vfr-tone-positive"
        if value <= 150:
            return "vfr-tone-muted"
        if value <= 250:
            return "vfr-tone-caution"
        return "vfr-tone-negative"
    if metric == "eps":
        return "vfr-tone-negative" if value < 0 else "vfr-tone-muted"
    return "vfr-tone-muted"


def _label_summary(label: str, risk_flags: list[str]) -> str:
    if risk_flags:
        return FLAG_DESCRIPTIONS.get(risk_flags[0], risk_flags[0])
    if label == "strong":
        return "수익성, 안정성, 성장성 지표가 전반적으로 양호합니다."
    if label == "moderate":
        return "핵심 지표가 혼재되어 보수적인 해석이 필요합니다."
    if label == "weak":
        return "수익성 또는 성장성 압박이 재무 체력을 제한합니다."
    return "분석 가능한 데이터가 제한적입니다."


def _label_tone_class(label: str) -> str:
    if label == "strong":
        return "vfr-label-strong"
    if label == "weak":
        return "vfr-label-weak"
    if label == "insufficient_data":
        return "vfr-label-insufficient"
    return "vfr-label-moderate"


def _svg_point(cx: float, cy: float, radius: float, value: float) -> tuple[float, float]:
    angle = math.radians(180 - (max(0.0, min(100.0, value)) / 100.0 * 180.0))
    return cx + radius * math.cos(angle), cy - radius * math.sin(angle)


def _arc_path(start: float, end: float, radius: float = 86.0) -> str:
    cx, cy = 120.0, 112.0
    x1, y1 = _svg_point(cx, cy, radius, start)
    x2, y2 = _svg_point(cx, cy, radius, end)
    large_arc = 1 if end - start > 50 else 0
    return f"M {x1:.2f} {y1:.2f} A {radius:.2f} {radius:.2f} 0 {large_arc} 1 {x2:.2f} {y2:.2f}"


def _gauge_tick(value: int) -> str:
    x, y = _svg_point(120.0, 112.0, 100.0, float(value))
    y = min(y + 6.0, 128.0)
    return f'<text class="vfr-gauge-tick" x="{x:.1f}" y="{y:.1f}" text-anchor="middle">{value}</text>'


def _score_gauge_svg(score: int, label: str) -> str:
    # 게이지는 표현 계층이다. 판정 라벨은 score에서 다시 계산하지 않고 인자로 받은 label만 표시한다.
    display_label = LABELS.get(label, label)
    clamped = max(0, min(100, int(score)))
    is_insufficient = label == "insufficient_data"
    needle_x, needle_y = _svg_point(120.0, 112.0, 72.0, clamped)
    tone = "vfr-gauge-insufficient" if is_insufficient else _label_tone_class(label)
    aria = escape(f"절대 재무점수 {score}점, {display_label}")
    needle = (
        ""
        if is_insufficient
        else f'<line class="vfr-gauge-needle" x1="120" y1="112" x2="{needle_x:.2f}" y2="{needle_y:.2f}"/>'
    )
    return f"""
      <svg class="vfr-gauge {tone}" viewBox="0 0 240 206" role="img" aria-label="{aria}">
        <path class="vfr-gauge-track" d="{_arc_path(0, 100)}"/>
        <path class="vfr-gauge-seg vfr-gauge-seg-weak" d="{_arc_path(0, 45)}"/>
        <path class="vfr-gauge-seg vfr-gauge-seg-mid" d="{_arc_path(45, 70)}"/>
        <path class="vfr-gauge-seg vfr-gauge-seg-strong" d="{_arc_path(70, 100)}"/>
        {needle}
        <circle class="vfr-gauge-pin" cx="120" cy="112" r="5"/>
        <text class="vfr-gauge-score vfr-num" x="120" y="160" text-anchor="middle">{score}</text>
        <text class="vfr-gauge-label" x="120" y="182" text-anchor="middle">{escape(display_label)}</text>
        {_gauge_tick(0)}
        {_gauge_tick(45)}
        {_gauge_tick(70)}
        {_gauge_tick(100)}
      </svg>
""".strip()


def _section_chip(text: str, tone: str) -> str:
    return f'<span class="vfr-section-chip vfr-section-chip-{tone}">{escape(text)}</span>'


def _bar_bucket(earned: float, max_points: float) -> str:
    if max_points <= 0:
        return "vfr-bar-w0"
    bucket = max(0, min(10, round((earned / max_points) * 10)))
    return f"vfr-bar-w{bucket}"


def _score_composition_card(score_breakdown: dict[str, Any]) -> str:
    component_labels = {"profitability": "수익성", "stability": "안정성", "growth": "성장성"}
    component_max = score_breakdown.get("component_max") or {"profitability": 40, "stability": 30, "growth": 30}
    rows = []
    for key, label in component_labels.items():
        earned = score_breakdown.get(key)
        max_points = component_max.get(key)
        if not isinstance(earned, (int, float)) or not isinstance(max_points, (int, float)) or max_points <= 0:
            continue
        rows.append(
            f"""
          <div class="vfr-mini-row">
            <div class="vfr-mini-row-top"><span>{escape(label)}</span><strong class="vfr-num">{earned:g}/{max_points:g}</strong></div>
            <span class="vfr-progress"><i class="{_bar_bucket(float(earned), float(max_points))}"></i></span>
          </div>
"""
        )
    if not rows:
        rows.append('<p class="vfr-score-note">점수 구성 세부값이 제공되지 않았습니다.</p>')
    explanation = score_breakdown.get("score_explanation") or "점수는 결정론적 재무지표만 합산해 산출합니다."
    return f"""
      <article class="vfr-hero-card">
        <div class="vfr-hero-card-head"><strong>점수 구성</strong>{_section_chip("코드 계산", "code")}</div>
        <div class="vfr-mini-list">{''.join(rows)}</div>
        <p class="vfr-hero-card-note">{escape(str(explanation))}</p>
      </article>
"""


def _has_missing_or_derived_flag(risk_flags: list[str]) -> bool:
    return any(flag.startswith("MISSING_") or flag.startswith("DERIVED_") for flag in risk_flags)


def _data_confidence_card(meta: dict[str, Any], trend: dict[str, Any], risk_flags: list[str]) -> str:
    years = trend.get("years") or []
    rows = [
        ("출처", "DART 공식 공시"),
        ("신선도", "실시간 재조회" if meta.get("fresh_dart") else "캐시 검증"),
        ("완전성", "결측·파생 플래그 있음" if _has_missing_or_derived_flag(risk_flags) else "핵심 지표 산출 가능"),
    ]
    if years:
        rows.append(("충분성", f"{len(years)}개 기간 추세"))
    items = "".join(
        f'<li><span>{escape(label)}</span><strong>{escape(value)}</strong></li>'
        for label, value in rows
    )
    return f"""
      <article class="vfr-hero-card">
        <div class="vfr-hero-card-head"><strong>데이터 신뢰도</strong>{_section_chip("재현 가능", "verify")}</div>
        <ul class="vfr-check-list">{items}</ul>
      </article>
"""


def _verification_passed(meta: dict[str, Any]) -> bool:
    summary = meta.get("verification_summary") or {}
    if not isinstance(summary, dict):
        return False
    if summary.get("outcome") not in {"passed", "insufficient_data"}:
        return False
    required = ("binding_passed", "consistency_passed", "guard_passed", "verdict_stable")
    explicit = [summary.get(key) for key in required if key in summary]
    return bool(explicit) and all(value is True for value in explicit)


def _display_tokens(ratios: dict[str, Any], evidence: list[Evidence]) -> list[str]:
    tokens: list[str] = []
    for item in ratios.values():
        display = _item_display(item)
        if display and display != "-":
            tokens.append(display)
    for item in evidence:
        display = item.display_value or _fmt(item.value, item.unit)
        if display and display != "-":
            tokens.append(display)
    return sorted(set(tokens), key=len, reverse=True)


def _highlight_interpretation(interpretation: str, ratios: dict[str, Any], evidence: list[Evidence]) -> str:
    # escape 이후 display 문자열과 정확히 일치하는 숫자만 강조한다. 근사 매칭은 숫자 왜곡 위험이 있다.
    text = escape(interpretation)
    matches: list[tuple[int, int]] = []
    for token in _display_tokens(ratios, evidence):
        escaped = escape(token)
        start = 0
        while True:
            index = text.find(escaped, start)
            if index < 0:
                break
            end = index + len(escaped)
            if not any(index < used_end and end > used_start for used_start, used_end in matches):
                matches.append((index, end))
            start = end
    if not matches:
        return text
    chunks: list[str] = []
    cursor = 0
    for start, end in sorted(matches):
        chunks.append(text[cursor:start])
        chunks.append(f'<b class="vfr-hl-num">{text[start:end]}</b>')
        cursor = end
    chunks.append(text[cursor:])
    return "".join(chunks)


def _anchor_id(metric: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", metric).strip("-")
    return f"vfr-ev-{slug or 'metric'}"


def _css() -> str:
    return """
<style>
.vfr-report {
  --vfr-bg:#f6f7f9;
  --vfr-panel:#ffffff;
  --vfr-panel-soft:#f7f8fa;
  --vfr-text:#161922;
  --vfr-subtle:#3a4051;
  --vfr-muted:#6b7385;
  --vfr-border:#eef0f4;
  --vfr-accent:#2563eb;
  --vfr-accent-soft:#e8f0ff;
  --vfr-ink-300:#cbd0db;
  --vfr-ink-400:#9aa1b2;
  --vfr-pos:#0ea371;
  --vfr-neg:#ef3e6a;
  --vfr-code:#0d9488;
  --vfr-code-soft:rgba(13,148,136,.09);
  --vfr-llm:#7c3aed;
  --vfr-llm-soft:rgba(124,58,237,.045);
  --vfr-up:#ef3e6a;
  --vfr-down:#2451e6;
  --vfr-warn:#b7791f;
  --vfr-shadow:0 1px 2px rgba(22,25,34,.04),0 1px 3px rgba(22,25,34,.06);
  color:var(--vfr-text);
  background:var(--vfr-bg);
  max-width:960px;
  margin:0 auto;
  font-family:Pretendard,-apple-system,"Segoe UI",system-ui,sans-serif;
  font-size:14px;
  line-height:1.6;
  padding:32px 18px;
}
.vfr-report * { box-sizing:border-box; }
.vfr-report .vfr-num, .vfr-report strong, .vfr-report td { font-variant-numeric:tabular-nums; }
.vfr-topbar { display:flex; justify-content:space-between; gap:16px; align-items:center; margin:0 2px 18px; color:var(--vfr-muted); font-size:13px; }
.vfr-breadcrumb { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.vfr-brand { color:var(--vfr-text); font-weight:900; }
.vfr-brand span { color:var(--vfr-accent); }
.vfr-chevron { width:13px; height:13px; color:var(--vfr-ink-400); }
.vfr-top-actions { display:flex; gap:8px; flex-wrap:wrap; }
.vfr-action { border:1px solid var(--vfr-border); border-radius:999px; padding:8px 12px; background:var(--vfr-panel); color:var(--vfr-subtle); font-size:13px; font-weight:800; box-shadow:var(--vfr-shadow); }
.vfr-card-shell { background:var(--vfr-panel); border:1px solid var(--vfr-border); border-radius:24px; box-shadow:var(--vfr-shadow); overflow:hidden; }
.vfr-shell { display:grid; gap:0; }
.vfr-block { padding:30px 34px; border-top:1px solid var(--vfr-border); }
.vfr-hero { position:relative; padding:34px 34px 28px; overflow:hidden; }
.vfr-hero::after { content:""; position:absolute; top:-120px; right:-90px; width:280px; height:280px; border-radius:999px; background:var(--vfr-accent-soft); opacity:.7; filter:blur(32px); }
.vfr-hero > * { position:relative; z-index:1; }
.vfr-eyebrow { display:inline-flex; align-items:center; gap:7px; color:var(--vfr-accent); background:var(--vfr-accent-soft); border-radius:999px; padding:5px 10px; font-size:12px; font-weight:900; }
.vfr-title { margin:12px 0 4px; font-size:32px; line-height:1.22; font-weight:900; }
.vfr-title span { color:#c3c9d4; font-size:25px; font-weight:700; }
.vfr-period { margin:0; color:var(--vfr-muted); font-size:13px; }
.vfr-hero-grid { display:grid; grid-template-columns:minmax(220px,.8fr) minmax(280px,1.2fr); gap:28px; align-items:center; margin-top:28px; }
.vfr-score-wrap { display:flex; flex-direction:column; align-items:center; }
.vfr-score-label { color:var(--vfr-muted); font-size:12px; font-weight:800; }
.vfr-badges { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.vfr-badge { display:inline-flex; align-items:center; border:1px solid var(--vfr-border); border-radius:999px; padding:5px 10px; background:var(--vfr-panel); color:var(--vfr-subtle); font-size:12px; font-weight:700; }
.vfr-label-strong { color:var(--vfr-pos); background:rgba(14,163,113,.10); border-color:rgba(14,163,113,.20); }
.vfr-label-moderate { color:var(--vfr-muted); background:rgba(107,115,133,.10); border-color:rgba(107,115,133,.20); }
.vfr-label-weak { color:var(--vfr-neg); background:rgba(239,62,106,.10); border-color:rgba(239,62,106,.20); }
.vfr-label-insufficient { color:var(--vfr-muted); background:rgba(107,115,133,.10); border-color:rgba(107,115,133,.20); }
.vfr-hero-cards { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.vfr-hero-card { border:1px solid var(--vfr-border); border-radius:16px; background:rgba(255,255,255,.78); padding:16px; box-shadow:var(--vfr-shadow); }
.vfr-hero-card-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:12px; }
.vfr-hero-card-head strong { font-size:14px; color:var(--vfr-text); }
.vfr-hero-card-note { margin:10px 0 0; color:var(--vfr-muted); font-size:12px; line-height:1.5; }
.vfr-mini-list { display:grid; gap:9px; }
.vfr-mini-row { display:grid; gap:5px; }
.vfr-mini-row-top { display:flex; justify-content:space-between; gap:10px; color:var(--vfr-subtle); font-size:12px; font-weight:800; }
.vfr-progress { display:block; height:7px; overflow:hidden; border-radius:999px; background:var(--vfr-border); }
.vfr-progress i { display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,var(--vfr-code),var(--vfr-accent)); }
.vfr-bar-w0 { width:0%; }
.vfr-bar-w1 { width:10%; }
.vfr-bar-w2 { width:20%; }
.vfr-bar-w3 { width:30%; }
.vfr-bar-w4 { width:40%; }
.vfr-bar-w5 { width:50%; }
.vfr-bar-w6 { width:60%; }
.vfr-bar-w7 { width:70%; }
.vfr-bar-w8 { width:80%; }
.vfr-bar-w9 { width:90%; }
.vfr-bar-w10 { width:100%; }
.vfr-check-list { list-style:none; display:grid; gap:9px; margin:0; padding:0; }
.vfr-check-list li { display:flex; justify-content:space-between; gap:10px; border-bottom:1px solid var(--vfr-border); padding-bottom:7px; color:var(--vfr-muted); font-size:12px; }
.vfr-check-list li:last-child { border-bottom:0; padding-bottom:0; }
.vfr-check-list strong { color:var(--vfr-text); text-align:right; }
.vfr-gauge { width:100%; max-width:250px; height:auto; overflow:visible; }
.vfr-gauge-track { fill:none; stroke:var(--vfr-border); stroke-width:16; stroke-linecap:round; }
.vfr-gauge-seg { fill:none; stroke-width:12; stroke-linecap:round; }
.vfr-gauge-seg-weak { stroke:rgba(239,62,106,.78); }
.vfr-gauge-seg-mid { stroke:var(--vfr-ink-300); }
.vfr-gauge-seg-strong { stroke:rgba(14,163,113,.82); }
.vfr-gauge-needle { stroke:var(--vfr-text); stroke-width:3; stroke-linecap:round; }
.vfr-gauge-pin { fill:var(--vfr-text); }
.vfr-gauge-score { fill:var(--vfr-accent); font-size:34px; font-weight:900; }
.vfr-gauge-label { fill:var(--vfr-muted); font-size:12px; font-weight:900; }
.vfr-gauge-tick { fill:var(--vfr-muted); font-size:10px; font-weight:800; }
.vfr-gauge.vfr-label-strong .vfr-gauge-score, .vfr-gauge.vfr-label-strong .vfr-gauge-label { fill:var(--vfr-pos); }
.vfr-gauge.vfr-label-weak .vfr-gauge-score, .vfr-gauge.vfr-label-weak .vfr-gauge-label { fill:var(--vfr-neg); }
.vfr-gauge.vfr-gauge-insufficient .vfr-gauge-score, .vfr-gauge.vfr-gauge-insufficient .vfr-gauge-label { fill:var(--vfr-muted); }
.vfr-summary-card { border:1px solid var(--vfr-border); border-radius:18px; padding:20px; background:var(--vfr-panel); }
.vfr-tldr { margin:0; color:var(--vfr-text); font-size:16px; font-weight:900; line-height:1.55; }
.vfr-tldr-sub { margin:10px 0 0; color:var(--vfr-muted); font-size:13px; }
.vfr-section { background:transparent; }
.vfr-section-head { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:16px; }
.vfr-section-title { margin:0; font-size:19px; line-height:1.35; font-weight:900; }
.vfr-section-kicker { color:var(--vfr-muted); font-size:12px; font-weight:800; }
.vfr-section-chip { display:inline-flex; align-items:center; white-space:nowrap; border-radius:999px; padding:5px 10px; font-size:12px; font-weight:900; }
.vfr-section-chip-code { color:var(--vfr-code); background:var(--vfr-code-soft); }
.vfr-section-chip-llm { color:var(--vfr-llm); background:var(--vfr-llm-soft); }
.vfr-section-chip-verify { color:var(--vfr-pos); background:rgba(14,163,113,.10); }
.vfr-card-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; }
.vfr-card { background:var(--vfr-panel); border:1px solid var(--vfr-border); border-radius:16px; padding:18px; box-shadow:none; }
.vfr-card-meta { color:var(--vfr-ink-400); font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.vfr-card-row { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-top:6px; }
.vfr-card-name { color:var(--vfr-text); font-size:14px; font-weight:800; }
.vfr-card-value { text-align:right; font-size:18px; line-height:1.25; font-weight:900; }
.vfr-card-reason { margin:8px 0 0; color:var(--vfr-subtle); font-size:12px; line-height:1.45; }
.vfr-tone-positive { color:var(--vfr-pos); }
.vfr-tone-negative { color:var(--vfr-neg); }
.vfr-tone-up { color:var(--vfr-up); }
.vfr-tone-down { color:var(--vfr-down); }
.vfr-tone-caution { color:var(--vfr-warn); }
.vfr-tone-muted { color:var(--vfr-text); }
.vfr-panel { background:var(--vfr-panel); border:1px solid var(--vfr-border); border-radius:16px; padding:20px; box-shadow:none; }
.vfr-role-line { margin:0 0 12px; color:var(--vfr-muted); font-size:13px; line-height:1.65; }
.vfr-role-code { color:var(--vfr-code); font-weight:900; }
.vfr-role-llm { color:var(--vfr-llm); font-weight:900; }
.vfr-llm-panel { border-left:3px solid var(--vfr-llm); background:var(--vfr-llm-soft); }
.vfr-llm-head { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px; }
.vfr-verified { display:inline-flex; align-items:center; border-radius:999px; padding:4px 8px; color:var(--vfr-code); background:var(--vfr-code-soft); font-size:11px; font-weight:900; }
.vfr-hl-num { color:var(--vfr-text); font-weight:950; background:rgba(36,81,230,.08); border-radius:6px; padding:0 3px; }
.vfr-evidence-links { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.vfr-evidence-jump { border:1px solid var(--vfr-border); border-radius:999px; padding:6px 10px; background:var(--vfr-panel); color:var(--vfr-accent); font-size:12px; font-weight:900; text-decoration:none; }
.vfr-body { margin:0; color:var(--vfr-subtle); font-size:15px; line-height:1.82; }
.vfr-chart { width:100%; height:auto; min-height:240px; display:block; background:var(--vfr-panel-soft); border:1px solid var(--vfr-border); border-radius:10px; }
.vfr-chart text { font-family:Pretendard,-apple-system,"Segoe UI",system-ui,sans-serif; }
.vfr-table-wrap { overflow:auto; border:1px solid var(--vfr-border); border-radius:10px; background:var(--vfr-panel); }
.vfr-table { width:100%; border-collapse:collapse; min-width:0; font-size:12px; }
.vfr-table caption { text-align:left; padding:10px 12px 0; color:var(--vfr-muted); font-size:11px; }
.vfr-table th, .vfr-table td { padding:9px 12px; border-bottom:1px solid var(--vfr-border); text-align:left; vertical-align:top; }
.vfr-table th { color:var(--vfr-muted); font-weight:800; }
.vfr-list { margin:0; padding-left:18px; color:var(--vfr-subtle); font-size:13px; }
.vfr-link { color:var(--vfr-accent); text-decoration:none; font-weight:700; }
.vfr-score-note { margin:0; color:var(--vfr-subtle); font-size:13px; line-height:1.65; }
.vfr-evidence-grid { display:grid; gap:10px; }
.vfr-evidence-card { border:1px solid var(--vfr-border); border-radius:16px; padding:16px; background:var(--vfr-panel); transition:border-color .16s ease, box-shadow .16s ease, transform .16s ease; scroll-margin-top:18px; }
.vfr-evidence-card:hover { border-color:rgba(36,81,230,.35); box-shadow:var(--vfr-shadow); transform:translateY(-1px); }
.vfr-evidence-card:target { border-color:var(--vfr-accent); box-shadow:0 0 0 3px rgba(36,81,230,.16); }
.vfr-evidence-top { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }
.vfr-evidence-title { margin:0; color:var(--vfr-text); font-size:14px; font-weight:900; }
.vfr-evidence-value { color:var(--vfr-accent); font-size:15px; font-weight:900; white-space:nowrap; }
.vfr-evidence-claim { margin:8px 0 0; color:var(--vfr-subtle); font-size:13px; line-height:1.65; }
.vfr-evidence-meta { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; color:var(--vfr-muted); font-size:12px; }
.vfr-evidence-chip { border:1px solid var(--vfr-border); border-radius:999px; padding:4px 8px; background:var(--vfr-panel-soft); }
.vfr-method-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; }
.vfr-method-step { border:1px solid var(--vfr-border); border-radius:14px; padding:14px; }
.vfr-method-step b { display:block; color:var(--vfr-ink-300); font-size:11px; }
.vfr-method-step strong { display:block; margin-top:5px; color:var(--vfr-text); font-size:13px; }
.vfr-method-step span { display:block; margin-top:3px; color:var(--vfr-muted); font-size:11.5px; line-height:1.45; }
.vfr-method-tag { color:var(--vfr-accent); font-weight:900; }
.vfr-flag-list { display:flex; flex-wrap:wrap; gap:8px; margin:0; padding:0; list-style:none; }
.vfr-flag-list li { border:1px solid var(--vfr-border); border-radius:999px; padding:7px 10px; background:var(--vfr-panel-soft); color:var(--vfr-subtle); font-size:12px; }
.vfr-notice { display:flex; gap:12px; align-items:flex-start; background:var(--vfr-panel-soft); border:1px solid var(--vfr-border); border-radius:16px; padding:16px; color:var(--vfr-subtle); }
.vfr-notice svg { flex:0 0 auto; width:20px; height:20px; color:var(--vfr-accent); }
.vfr-notice p { margin:0; font-size:13px; line-height:1.65; }
.vfr-footer { padding:18px; text-align:center; color:var(--vfr-muted); font-size:12px; font-weight:800; }
.vfr-debug { border-style:dashed; }
.vfr-debug summary { cursor:pointer; color:var(--vfr-accent); font-weight:900; }
.vfr-debug pre { margin:12px 0 0; white-space:pre-wrap; overflow:auto; border:1px solid var(--vfr-border); border-radius:8px; padding:12px; background:var(--vfr-panel-soft); color:var(--vfr-subtle); font-size:11px; line-height:1.45; }
@media (prefers-color-scheme: dark) {
  .vfr-report {
    --vfr-bg:#0f141b;
    --vfr-panel:#171d26;
    --vfr-panel-soft:#111821;
    --vfr-text:#f3f6fb;
    --vfr-subtle:#c4ccd8;
    --vfr-muted:#9aa6b8;
    --vfr-border:#303948;
    --vfr-accent:#74a7ff;
    --vfr-accent-soft:#14233a;
    --vfr-ink-300:#586477;
    --vfr-ink-400:#8e9aad;
    --vfr-pos:#5bd6a2;
    --vfr-neg:#ff7a95;
    --vfr-code:#4fd1c5;
    --vfr-code-soft:rgba(79,209,197,.12);
    --vfr-llm:#b794f4;
    --vfr-llm-soft:rgba(183,148,244,.10);
    --vfr-up:#ff7a95;
    --vfr-down:#74a7ff;
    --vfr-warn:#ffd166;
    --vfr-shadow:none;
  }
  .vfr-hero-card { background:rgba(23,29,38,.82); }
}
@media (max-width:640px) {
  .vfr-report { padding:18px 10px; }
  .vfr-topbar { align-items:flex-start; flex-direction:column; }
  .vfr-hero, .vfr-block { padding:22px 18px; }
  .vfr-hero-grid { grid-template-columns:1fr; gap:14px; }
  .vfr-score-wrap { align-items:flex-start; }
  .vfr-hero-cards { grid-template-columns:1fr; }
  .vfr-card-grid { grid-template-columns:1fr; }
  .vfr-method-grid { grid-template-columns:1fr; }
  .vfr-table-wrap { border:0; background:transparent; overflow:visible; }
  .vfr-table, .vfr-table tbody, .vfr-table tr, .vfr-table td { display:block; width:100%; }
  .vfr-table thead, .vfr-table caption { display:none; }
  .vfr-table tr { margin-bottom:10px; border:1px solid var(--vfr-border); border-radius:10px; background:var(--vfr-panel); overflow:hidden; }
  .vfr-table td { display:flex; justify-content:space-between; gap:12px; border-bottom:1px solid var(--vfr-border); }
  .vfr-table td::before { content:attr(data-label); color:var(--vfr-muted); font-weight:800; }
}
@media print {
  .vfr-report { border:0; max-width:none; background:#fff; }
  .vfr-card, .vfr-panel, .vfr-debug, .vfr-section { break-inside:avoid; page-break-inside:avoid; box-shadow:none; }
  .vfr-link { color:#111827; text-decoration:none; }
}
</style>
"""


def _ratio_cards(ratios: dict[str, Any]) -> str:
    cards = []
    for metric, item in ratios.items():
        reason = item.get("reason")
        cards.append(
            f"""
      <article class="vfr-card">
        <div class="vfr-card-meta">{escape(str(item.get("category", "")))}</div>
        <div class="vfr-card-row">
          <strong class="vfr-card-name">{escape(str(item.get("label", metric)))}</strong>
          <span class="vfr-card-value vfr-num {_value_tone_class(metric, item)}">{escape(_item_display(item))}</span>
        </div>
        {f'<p class="vfr-card-reason">{escape(str(reason))}</p>' if reason else ''}
      </article>
"""
        )
    return "".join(cards)


def _trend_display(trend: dict[str, Any], key: str, idx: int, value: Any, unit: str) -> str:
    display = trend.get("display") or {}
    values = display.get(key) or []
    if idx < len(values) and values[idx] not in (None, ""):
        return str(values[idx])
    return _fmt(value, unit)


def _scale(value: float, low: float, high: float, top: float, bottom: float) -> float:
    if high == low:
        return (top + bottom) / 2
    return bottom - ((value - low) / (high - low)) * (bottom - top)


def _trend_chart_svg(trend: dict[str, Any]) -> str:
    years = trend.get("years", [])
    labels = trend.get("period_labels") or years
    revenue = trend.get("revenue", [])
    op_income = trend.get("op_income", [])
    roe = trend.get("roe", [])
    count = len(years)
    if not count:
        return ""

    width, height = 960, 390
    left, right = 72, 44
    bar_top, bar_bottom = 58, 230
    spark_top, spark_bottom = 286, 348
    plot_width = width - left - right
    step = plot_width / max(count, 1)
    bar_width = min(34, max(16, step * 0.18))
    money_values = [float(value) for value in [*revenue, *op_income] if isinstance(value, (int, float))]
    roe_values = [float(value) for value in roe if isinstance(value, (int, float))]
    if not money_values:
        return ""
    money_low = min(0.0, min(money_values))
    money_high = max(money_values)
    if money_low == money_high:
        money_high = money_low + 1
    roe_low = min(roe_values or [0.0])
    roe_high = max(roe_values or [0.0])
    if roe_low == roe_high:
        roe_low -= 1
        roe_high += 1

    parts = [
        '<svg class="vfr-chart" viewBox="0 0 960 390" role="img" aria-label="매출, 영업이익, ROE 추세 차트">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>',
        f'<text x="{left}" y="28" fill="currentColor" font-size="13" font-weight="800">매출·영업이익 추세</text>',
        f'<circle cx="{left + 122}" cy="24" r="5" fill="var(--vfr-accent)"/><text x="{left + 134}" y="28" fill="var(--vfr-muted)" font-size="11">매출</text>',
        f'<circle cx="{left + 184}" cy="24" r="5" fill="var(--vfr-warn)"/><text x="{left + 196}" y="28" fill="var(--vfr-muted)" font-size="11">영업이익</text>',
        f'<text x="{left}" y="268" fill="currentColor" font-size="13" font-weight="800">ROE</text>',
    ]
    for index in range(4):
        y = bar_top + (bar_bottom - bar_top) / 3 * index
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="var(--vfr-border)" stroke-width="1"/>')
    parts.append(f'<line x1="{left}" y1="{bar_bottom}" x2="{width - right}" y2="{bar_bottom}" stroke="var(--vfr-border)" stroke-width="1.2"/>')

    line_points = []
    for idx in range(count):
        center = left + step * idx + step / 2
        label = escape(str(labels[idx] if idx < len(labels) else years[idx]))
        if idx < len(revenue) and isinstance(revenue[idx], (int, float)):
            value = float(revenue[idx])
            y = _scale(value, money_low, money_high, bar_top, bar_bottom)
            top = min(y, bar_bottom)
            h = max(abs(bar_bottom - y), 3)
            display = escape(_trend_display(trend, "revenue", idx, value, "원"))
            parts.append(f'<rect x="{center - bar_width - 3:.1f}" y="{top:.1f}" width="{bar_width:.1f}" height="{h:.1f}" rx="5" fill="var(--vfr-accent)"><title>{label} 매출 {display}</title></rect>')
            parts.append(f'<text x="{center - bar_width / 2 - 3:.1f}" y="{max(top - 6, 46):.1f}" fill="var(--vfr-muted)" font-size="10" text-anchor="middle">{display}</text>')
        if idx < len(op_income) and isinstance(op_income[idx], (int, float)):
            value = float(op_income[idx])
            y = _scale(value, money_low, money_high, bar_top, bar_bottom)
            top = min(y, bar_bottom)
            h = max(abs(bar_bottom - y), 3)
            color = "var(--vfr-warn)" if value >= 0 else "var(--vfr-neg)"
            display = escape(_trend_display(trend, "op_income", idx, value, "원"))
            parts.append(f'<rect x="{center + 3:.1f}" y="{top:.1f}" width="{bar_width:.1f}" height="{h:.1f}" rx="5" fill="{color}"><title>{label} 영업이익 {display}</title></rect>')
        if idx < len(roe) and isinstance(roe[idx], (int, float)):
            value = float(roe[idx])
            y = _scale(value, roe_low, roe_high, spark_top, spark_bottom)
            line_points.append((center, y, value))
        parts.append(f'<text x="{center:.1f}" y="252" fill="var(--vfr-muted)" font-size="11" text-anchor="middle">{label}</text>')

    if line_points:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in line_points)
        parts.append(f'<polyline points="{points}" fill="none" stroke="var(--vfr-pos)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for idx, (x, y, value) in enumerate(line_points):
            color = "var(--vfr-pos)" if value >= 0 else "var(--vfr-neg)"
            display = escape(_trend_display(trend, "roe", idx, value, "%"))
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}" stroke="var(--vfr-panel)" stroke-width="2"><title>ROE {display}</title></circle>')
            parts.append(f'<text x="{x:.1f}" y="{spark_bottom + 24}" fill="var(--vfr-muted)" font-size="10" text-anchor="middle">{display}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _trend_rows(trend: dict[str, Any]) -> str:
    years = trend.get("years", [])
    labels = trend.get("period_labels") or years
    revenue = trend.get("revenue", [])
    op_income = trend.get("op_income", [])
    roe = trend.get("roe", [])
    rows = []
    for idx, year in enumerate(years):
        label = labels[idx] if idx < len(labels) else year
        rows.append(
            "<tr>"
            f'<td data-label="기간">{escape(str(label))}</td>'
            f'<td data-label="매출">{escape(_fmt(revenue[idx] if idx < len(revenue) else None, "원"))}</td>'
            f'<td data-label="영업이익">{escape(_fmt(op_income[idx] if idx < len(op_income) else None, "원"))}</td>'
            f'<td data-label="ROE">{escape(_fmt(roe[idx] if idx < len(roe) else None, "%"))}</td>'
            "</tr>"
        )
    return "".join(rows)


def _evidence_rows(evidence: list[Evidence]) -> str:
    return "".join(
        "<tr>"
        f'<td data-label="metric">{escape(item.metric)}</td>'
        f'<td data-label="value">{escape(_item_display({"display_value": item.display_value, "value": item.value, "unit": item.unit}))}</td>'
        f'<td data-label="year">{escape(item.fiscal_year)}</td>'
        f'<td data-label="account_ids">{escape(", ".join(item.account_ids))}</td>'
        f'<td data-label="DART"><a class="vfr-link" href="{escape(item.source_url)}" target="_blank" rel="noopener">{escape(item.rcept_no)}</a></td>'
        "</tr>"
        for item in evidence
    )


def _insight_metric(label: str, value: Any, unit: str = "") -> str:
    text = _fmt(value, unit) if isinstance(value, (int, float)) else (str(value) if value else "-")
    return f'<div><div class="vfr-card-meta">{escape(label)}</div><strong class="vfr-num">{escape(text)}</strong></div>'


def _has_insight_value(data: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(data.get(key) not in (None, "", "-") for key in keys)


def _insight_section(insights: dict[str, Any]) -> str:
    if not insights:
        return ""
    dividend = insights.get("dividend") or {}
    major = insights.get("major_holder") or {}
    minor = insights.get("minor_holder") or {}
    audit = insights.get("audit") or {}
    cards = []
    if _has_insight_value(dividend, ("dps_common", "dividend_yield_common", "payout_ratio", "dart_eps")):
        cards.append(
            f'<article class="vfr-card"><div class="vfr-card-meta">배당</div><div class="vfr-card-grid">'
            f'{_insight_metric("보통주 DPS", dividend.get("dps_common"), "원")}'
            f'{_insight_metric("배당수익률", dividend.get("dividend_yield_common"), "%")}'
            f'{_insight_metric("배당성향", dividend.get("payout_ratio"), "%")}'
            f'{_insight_metric("DART EPS", dividend.get("dart_eps"), "원")}</div></article>'
        )
    if _has_insight_value(major, ("name", "ratio")) or _has_insight_value(minor, ("held_ratio", "shareholders")):
        cards.append(
            f'<article class="vfr-card"><div class="vfr-card-meta">주주 구성</div><div class="vfr-card-grid">'
            f'{_insight_metric("최대주주", major.get("name"))}'
            f'{_insight_metric("최대주주 지분율", major.get("ratio"), "%")}'
            f'{_insight_metric("소액주주 지분율", minor.get("held_ratio"), "%")}'
            f'{_insight_metric("소액주주 수", minor.get("shareholders"), "명")}</div></article>'
        )
    if _has_insight_value(audit, ("auditor", "opinion")):
        cards.append(
            f'<article class="vfr-card"><div class="vfr-card-meta">감사의견</div>'
            f'{_insight_metric("감사인", audit.get("auditor"))}{_insight_metric("의견", audit.get("opinion"))}</article>'
        )
    if not cards:
        return ""
    return (
        '<section class="vfr-block">'
        '<div class="vfr-section-head"><h3 class="vfr-section-title">DART 추가 인사이트</h3>'
        '<span class="vfr-section-kicker">주주 · 배당 · 감사</span></div>'
        f'<div class="vfr-card-grid">{"".join(cards)}</div></section>'
    )


def _verification_debug(meta: dict[str, Any]) -> str:
    summary = meta.get("verification_summary") or {}
    if not summary:
        return ""
    return f'<details class="vfr-panel vfr-debug"><summary>내부 검수용 · Verification Gate</summary><pre>{escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></details>'


def _source_policy_debug(meta: dict[str, Any]) -> str:
    summary = meta.get("retrieval_summary") or {}
    if not summary:
        return ""
    return f'<details class="vfr-panel vfr-debug"><summary>내부 검수용 · DART Source Policy</summary><pre>{escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></details>'


def _storage_debug(meta: dict[str, Any]) -> str:
    payload = meta.get("erd_payload") or {}
    if not payload:
        return ""
    report = payload.get("fundamental_report") or {}
    preview = {
        "report_id": report.get("id"),
        "data_status": report.get("data_status"),
        "ratio_rows": len(payload.get("report_ratios") or []),
        "evidence_rows": len(payload.get("report_evidence") or []),
        "verification": (payload.get("report_verification") or {}).get("outcome"),
    }
    return f'<details class="vfr-panel vfr-debug"><summary>내부 검수용 · 저장 계약</summary><pre>{escape(json.dumps(preview, ensure_ascii=False, indent=2))}</pre></details>'


def _analyst_plan_debug(analyst_plan: dict[str, Any]) -> str:
    if not analyst_plan:
        return ""
    return f'<details class="vfr-panel vfr-debug"><summary>내부 검수용 · Analyst Frame</summary><pre>{escape(json.dumps(analyst_plan, ensure_ascii=False, indent=2))}</pre></details>'


def _mermaid_id(value: str) -> str:
    return "n_" + "".join(char if char.isalnum() else "_" for char in value)


def _mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def _evidence_graph_debug(evidence_graph: dict[str, Any]) -> str:
    nodes = evidence_graph.get("nodes") or []
    edges = evidence_graph.get("edges") or []
    if not nodes or not edges:
        return ""
    labels = {
        str(node.get("id")): str(
            node.get("label")
            or node.get("account_nm")
            or node.get("rcept_no")
            or node.get("metric")
            or node.get("type")
            or node.get("id")
        )
        for node in nodes
        if node.get("id")
    }
    lines = ["graph TD"]
    for node_id, label in labels.items():
        lines.append(f'  {_mermaid_id(node_id)}["{_mermaid_label(label)}"]')
    for edge in edges[:100]:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source and target:
            relation = _mermaid_label(str(edge.get("relation") or "relates_to"))
            lines.append(f"  {_mermaid_id(source)} -- {relation} --> {_mermaid_id(target)}")
    return f'<details class="vfr-panel vfr-debug"><summary>내부 검수용 · Evidence Graph Mermaid</summary><pre>{escape(chr(10).join(lines))}</pre></details>'


def _debug_sections(meta: dict[str, Any], analyst_plan: dict[str, Any], evidence_graph: dict[str, Any]) -> str:
    return "".join(
        [
            _analyst_plan_debug(analyst_plan),
            _verification_debug(meta),
            _source_policy_debug(meta),
            _evidence_graph_debug(evidence_graph),
            _storage_debug(meta),
        ]
    )


def _risk_flags_section(risk_flags: list[str]) -> str:
    flag_items = "".join(
        f"<li><strong>{escape(flag)}</strong> · {escape(FLAG_DESCRIPTIONS.get(flag, '추적용 리스크 플래그입니다.'))}</li>"
        for flag in risk_flags
    ) or "<li>특이 플래그 없음</li>"
    return (
        '<section class="vfr-block">'
        '<div class="vfr-section-head"><h3 class="vfr-section-title">데이터 한계</h3>'
        f'{_section_chip("검증 플래그", "verify")}</div>'
        f'<div class="vfr-panel"><ul class="vfr-flag-list">{flag_items}</ul></div></section>'
    )


def _notice_section() -> str:
    return """
    <section class="vfr-block">
      <div class="vfr-notice">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l7 3v5c0 4.7-2.9 8.8-7 10-4.1-1.2-7-5.3-7-10V6l7-3z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 12l2 2 4-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <p>이 리포트는 재무 지표 요약이며 <strong>투자 권유가 아닙니다.</strong> 모든 수치는 DART 원문 공시에 연결되어 검증됩니다.</p>
      </div>
    </section>
"""


def _metric_label(metric: str, ratios: dict[str, Any]) -> str:
    item = ratios.get(metric) or {}
    return str(item.get("label") or metric)


def _account_summary(item: Evidence) -> str:
    names = []
    for account in item.accounts:
        if account.account_nm and account.account_nm not in names:
            names.append(account.account_nm)
    if names:
        return ", ".join(names[:3])
    if item.account_ids:
        return ", ".join(item.account_ids[:2])
    return "DART 공시 계정"


def _evidence_links(evidence: list[Evidence], ratios: dict[str, Any]) -> str:
    links = []
    seen: set[str] = set()
    for index, item in enumerate(evidence, start=1):
        if item.metric in seen:
            continue
        seen.add(item.metric)
        label = _metric_label(item.metric, ratios)
        links.append(
            f'<a class="vfr-evidence-jump" href="#{escape(_anchor_id(item.metric))}">#{index} {escape(label)}</a>'
        )
        if len(links) >= 8:
            break
    if not links:
        return ""
    return f'<div class="vfr-evidence-links" aria-label="근거 지표 바로가기">{"".join(links)}</div>'


def _evidence_cards(evidence: list[Evidence], ratios: dict[str, Any]) -> str:
    if not evidence:
        return '<p class="vfr-score-note">표시할 원문 근거가 없습니다.</p>'
    cards = []
    seen: set[str] = set()
    for item in evidence:
        if item.metric in seen:
            continue
        seen.add(item.metric)
        label = _metric_label(item.metric, ratios)
        display = item.display_value or _fmt(item.value, item.unit)
        cards.append(
            f"""
        <article class="vfr-evidence-card" id="{escape(_anchor_id(item.metric))}">
          <div class="vfr-evidence-top">
            <h4 class="vfr-evidence-title">{escape(label)}</h4>
            <strong class="vfr-evidence-value vfr-num">{escape(display)}</strong>
          </div>
          <p class="vfr-evidence-claim">{escape(item.claim)}</p>
          <div class="vfr-evidence-meta">
            <span class="vfr-evidence-chip">{escape(item.fiscal_year)}년 공시</span>
            <span class="vfr-evidence-chip">{escape(_account_summary(item))}</span>
            <a class="vfr-evidence-chip vfr-link" href="{escape(item.source_url)}" target="_blank" rel="noopener">DART 원문 {escape(item.rcept_no)}</a>
          </div>
        </article>
"""
        )
        if len(cards) >= 8:
            break
    return "".join(cards)


def _evidence_section(evidence: list[Evidence], ratios: dict[str, Any], audience: Audience) -> str:
    raw_table = (
        f"""
      <details class="vfr-panel vfr-debug">
        <summary>내부 검수용 · 원문 계정 테이블</summary>
        <div class="vfr-table-wrap">
          <table class="vfr-table">
            <caption>계산 지표와 연결된 DART 계정 및 접수번호</caption>
            <thead><tr><th scope="col">metric</th><th scope="col">value</th><th scope="col">year</th><th scope="col">account_ids</th><th scope="col">DART</th></tr></thead>
            <tbody>{_evidence_rows(evidence)}</tbody>
          </table>
        </div>
      </details>
"""
        if audience == "debug"
        else ""
    )
    return f"""
    <section class="vfr-block">
      <div class="vfr-section-head">
        <h3 class="vfr-section-title">근거 요약</h3>
        {_section_chip("DART 원문 연결", "code")}
      </div>
      <div class="vfr-evidence-grid">{_evidence_cards(evidence, ratios)}</div>
      {raw_table}
    </section>
"""


def _method_section(confidence: float, meta: dict[str, Any]) -> str:
    report_mode = meta.get("report_mode") or "annual"
    fresh = "실시간 재조회" if meta.get("fresh_dart") else "캐시 검증"
    return f"""
    <section class="vfr-block">
      <div class="vfr-section-head">
        <h3 class="vfr-section-title">분석 방법</h3>
        <div>{_section_chip("계산 검증 · 재현 가능", "verify")} <span class="vfr-section-kicker">신뢰도 {confidence:.2f}</span></div>
      </div>
      <div class="vfr-method-grid">
        <div class="vfr-method-step"><b>01</b><strong>DART 수집</strong><span>{escape(fresh)} · {escape(str(report_mode))} 모드</span><span class="vfr-method-tag">공시 원문</span></div>
        <div class="vfr-method-step"><b>02</b><strong>지표 계산</strong><span>ROE, 수익성, 안정성, 성장성은 코드가 결정론적으로 산출</span><span class="vfr-method-tag">코드 계산</span></div>
        <div class="vfr-method-step"><b>03</b><strong>LLM 해석</strong><span>LLM은 숫자를 만들지 않고 계산 결과만 설명</span><span class="vfr-method-tag">근거 서술</span></div>
        <div class="vfr-method-step"><b>04</b><strong>검증 게이트</strong><span>허용 숫자, 금지 표현, 라벨 안정성을 재검사</span><span class="vfr-method-tag">자동 검수</span></div>
        <div class="vfr-method-step"><b>05</b><strong>저장·근거 연결</strong><span>JSON 응답과 HTML 표현을 같은 근거 ID로 연결</span><span class="vfr-method-tag">서비스 연동</span></div>
      </div>
    </section>
"""


def build_report_html(
    corp_name: str,
    ticker: str,
    score: int,
    label: str,
    confidence: float,
    ratios: dict[str, Any],
    trend: dict[str, Any],
    interpretation: str,
    evidence: list[Evidence],
    risk_flags: list[str],
    insights: dict[str, Any] | None = None,
    score_breakdown: dict[str, Any] | None = None,
    analyst_plan: dict[str, Any] | None = None,
    evidence_graph: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    audience: Audience = "user",
) -> str:
    # report_html은 검수용 fragment다. 프론트/백엔드의 주 계약은 FundamentalResponse JSON이다.
    insights = insights or {}
    score_breakdown = score_breakdown or {}
    analyst_plan = analyst_plan or {}
    evidence_graph = evidence_graph or {}
    meta = meta or {}
    period = meta.get("period_basis") or {}
    report_name = period.get("report_name") or meta.get("reprt_name") or "사업보고서"
    period_description = period.get("description") or f"{report_name} 기준"
    period_badge = "분기 기준" if period.get("is_interim") else "연간 기준"
    peer_text = ""
    if meta.get("peer_rank") and meta.get("peer_count"):
        peer_group = meta.get("peer_group_label") or meta.get("peer_group", "동종군")
        peer_text = f"{peer_group} {meta['peer_rank']}/{meta['peer_count']} · {meta.get('peer_label', '')}"
    percentile = meta.get("peer_percentile")
    score_note = score_breakdown.get("score_explanation", "")
    summary_line = _label_summary(label, risk_flags)
    debug = audience == "debug"
    chevron = '<svg class="vfr-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    verified_badge = '<span class="vfr-verified">검증됨</span>' if _verification_passed(meta) else ""

    return f"""
{_css()}
<section class="vfr-report" data-audience="{escape(audience)}">
  <div class="vfr-topbar">
    <div class="vfr-breadcrumb">
      <span class="vfr-brand">veri<span>θ</span></span>
      {chevron}
      <span>집중 리포트</span>
      {chevron}
      <strong>재무·펀더멘털</strong>
    </div>
    <div class="vfr-top-actions">
      <span class="vfr-action">JSON 연동</span>
      <span class="vfr-action">DART 기반</span>
    </div>
  </div>
  <article class="vfr-card-shell">
    <header class="vfr-hero">
      <div class="vfr-eyebrow">Fundamental Worker</div>
      <h2 class="vfr-title">{escape(corp_name)} <span>· {escape(ticker)}</span></h2>
      <p class="vfr-period">DART 공시 기반 재무 분석 · {escape(str(period_description))}</p>
      <div class="vfr-hero-grid">
        <div class="vfr-score-wrap">
          <div class="vfr-score-label">절대 재무점수</div>
          {_score_gauge_svg(score, label)}
          <div class="vfr-badges">
            <span class="vfr-badge {_label_tone_class(label)}">{escape(LABELS.get(label, label))}</span>
            <span class="vfr-badge">{escape(period_badge)}</span>
            {f'<span class="vfr-badge">동종군 백분위 {escape(str(percentile))}점</span>' if percentile is not None else ''}
          </div>
        </div>
        <div class="vfr-hero-cards">
          {_score_composition_card(score_breakdown)}
          {_data_confidence_card(meta, trend, risk_flags)}
        </div>
      </div>
      <div class="vfr-summary-card">
          <p class="vfr-tldr">{escape(summary_line)}</p>
          <p class="vfr-tldr-sub">{escape(peer_text or score_note or "결정론적 지표와 DART 원문 근거만 사용했습니다.")}</p>
      </div>
    </header>
    <div class="vfr-shell">
    <section class="vfr-block">
      <div class="vfr-section-head">
        <h3 class="vfr-section-title">핵심 재무지표</h3>
        {_section_chip("코드 계산 · 결정론", "code")}
      </div>
      <div class="vfr-card-grid">{_ratio_cards(ratios)}</div>
    </section>
    <section class="vfr-block">
      <div class="vfr-section-head">
        <h3 class="vfr-section-title">{len(trend.get("years", []))}개 기간 추세</h3>
        <span class="vfr-section-kicker">매출 · 영업이익 · ROE</span>
      </div>
      {_trend_chart_svg(trend)}
      <div class="vfr-table-wrap">
        <table class="vfr-table">
          <caption>DART 공시 기준 기간별 매출, 영업이익, ROE</caption>
          <thead><tr><th scope="col">기간</th><th scope="col">매출</th><th scope="col">영업이익</th><th scope="col">ROE</th></tr></thead>
          <tbody>{_trend_rows(trend)}</tbody>
        </table>
      </div>
    </section>
    <section class="vfr-block">
      <div class="vfr-section-head">
        <h3 class="vfr-section-title">신호 흐름 요약</h3>
        {_section_chip("LLM 생성 · 근거 연결", "llm")}
      </div>
      <p class="vfr-role-line"><span class="vfr-role-code">판정·수치·점수는 코드가 계산</span>하고, <span class="vfr-role-llm">설명 문장은 LLM이 그 값을 해석</span>합니다. LLM은 판정을 바꿀 수 없으며, 검증을 통과한 문장만 표시됩니다.</p>
      <div class="vfr-panel vfr-llm-panel">
        <div class="vfr-llm-head">{_section_chip("LLM 서술", "llm")}{verified_badge}</div>
        <p class="vfr-body">{_highlight_interpretation(interpretation, ratios, evidence)}</p>
        {_evidence_links(evidence, ratios)}
      </div>
    </section>
    {_insight_section(insights)}
    {_evidence_section(evidence, ratios, audience)}
    {_method_section(confidence, meta)}
    {_risk_flags_section(risk_flags)}
    {_notice_section()}
    {_debug_sections(meta, analyst_plan, evidence_graph) if debug else ''}
    </div>
  </article>
  <footer class="vfr-footer">veriθ · Evidence-based AI Stock Research</footer>
</section>
""".strip()
