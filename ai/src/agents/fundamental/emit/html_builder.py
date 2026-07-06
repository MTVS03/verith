import json
from html import escape
from typing import Any

from ..core.contract import Evidence
from ..report.formatting import format_metric_value

LABELS = {
    "strong": "양호",
    "moderate": "중립",
    "weak": "주의",
    "insufficient_data": "데이터 제한",
}

FLAG_DESCRIPTIONS = {
    "MISSING_BPS": "DART 주식의 총수 현황에서 발행주식수를 안정적으로 확보하지 못해 총자본 기준 BPS를 산출하지 않았습니다.",
    "NOT_MEANINGFUL_OPERATING_INCOME_GROWTH": "전기 흑자에서 당기 적자로 전환되어 영업이익 성장률을 퍼센트로 표시하지 않았습니다.",
    "NOT_MEANINGFUL_REVENUE_GROWTH": "전기 또는 당기 매출 기준이 음수라 매출 성장률을 퍼센트로 표시하지 않았습니다.",
    "LLM_FALLBACK_OPENAI": "Qwen 호출 실패 또는 검증 실패로 OpenAI fallback 경로를 사용했습니다.",
    "LLM_FALLBACK_TEMPLATE": "LLM 해석을 사용하지 않고 규칙 기반 문장 템플릿으로 안전 착지했습니다.",
    "DERIVED_LIABILITIES": "부채총계가 누락되어 자본과부채총계에서 자본총계를 차감해 파생 계산했습니다.",
    "STALE_DART_CACHE_FALLBACK": "DART 최신 재조회가 실패하여 기존 캐시 원문으로 리포트를 생성했습니다.",
    "VERDICT_STABILITY_GUARDED": "LLM 결론 문구가 점수 라벨과 완전히 일치하지 않아 검증 플래그를 남겼습니다.",
}


def _fmt(value: Any, unit: str) -> str:
    return format_metric_value(value, unit)


def _item_display(item: dict[str, Any], unit: str | None = None) -> str:
    display_value = item.get("display_value")
    if display_value not in (None, ""):
        return str(display_value)
    return _fmt(item.get("value"), unit if unit is not None else item.get("unit", ""))


def _tone(metric: str, value: float | int | None) -> str:
    if value is None:
        return "#6b7385"
    if metric == "current_ratio":
        return "#0ea371" if value >= 100 else "#e08a00" if value >= 80 else "#f0436b"
    if metric in {"roe", "operating_margin", "net_margin", "revenue_growth", "operating_income_growth"}:
        return "#0ea371" if value >= 0 else "#f0436b"
    if metric == "debt_ratio":
        return "#0ea371" if value <= 120 else "#e08a00" if value <= 200 else "#f0436b"
    if metric == "eps":
        return "#f0436b" if value < 0 else "#2451e6"
    return "#2451e6"


def _confidence_tone(confidence: float) -> str:
    if confidence >= 0.8:
        return "#0ea371"
    if confidence >= 0.65:
        return "#e08a00"
    return "#f0436b"


def _ratio_cards(ratios: dict[str, Any]) -> str:
    cards = []
    for metric, item in ratios.items():
        value = item.get("value")
        unit = item.get("unit", "")
        reason = item.get("reason")
        color = _tone(metric, value)
        cards.append(
            f"""
      <article style="border:1px solid #e2e5ec;border-radius:10px;padding:14px;background:#fff">
        <div style="font-size:12px;color:#6b7385;margin-bottom:6px">{escape(item.get('category', ''))}</div>
        <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
          <strong style="font-size:14px;color:#262b38">{escape(item.get('label', metric))}</strong>
          <span style="font-size:16px;font-weight:800;color:{color};text-align:right">{escape(_item_display(item, unit))}</span>
        </div>
        {f'<p style="margin:8px 0 0;font-size:12px;line-height:1.45;color:#6b7385">{escape(reason)}</p>' if reason else ''}
      </article>
"""
        )
    return "".join(cards)


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
            f"<tr><td>{escape(str(label))}</td><td>{escape(_fmt(revenue[idx] if idx < len(revenue) else None, '원'))}</td>"
            f"<td>{escape(_fmt(op_income[idx] if idx < len(op_income) else None, '원'))}</td>"
            f"<td>{escape(_fmt(roe[idx] if idx < len(roe) else None, '%'))}</td></tr>"
        )
    return "".join(rows)


def _trend_display(trend: dict[str, Any], key: str, idx: int, value: Any, unit: str) -> str:
    display = trend.get("display") or {}
    values = display.get(key) or []
    if idx < len(values) and values[idx] not in (None, ""):
        return str(values[idx])
    return _fmt(value, unit)


def _normalize_points(values: list[float], top: float, bottom: float) -> tuple[float, float, float]:
    low = min(values)
    high = max(values)
    if low == high:
        low -= 1
        high += 1
    span = high - low
    scale = (bottom - top) / span
    return low, high, scale


def _axis_krw(value: float) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 1_000_000_000_000:
        return f"{sign}{absolute / 1_000_000_000_000:.1f}조"
    if absolute >= 100_000_000:
        return f"{sign}{absolute / 100_000_000:,.0f}억"
    return _fmt(value, "원")


def _axis_percent(value: float) -> str:
    return f"{value:.1f}%"


def _trend_chart_svg(trend: dict[str, Any]) -> str:
    years = trend.get("years", [])
    labels = trend.get("period_labels") or years
    revenue = trend.get("revenue", [])
    roe = trend.get("roe", [])
    count = len(years)
    if count == 0:
        return ""

    width = 960
    height = 320
    left = 72
    right = 72
    top = 58
    bottom = 246
    plot_width = width - left - right
    step = plot_width / max(count, 1)
    bar_width = min(46, max(22, step * 0.34))
    revenue_values = [float(value) for value in revenue if isinstance(value, (int, float))]
    roe_values = [float(value) for value in roe if isinstance(value, (int, float))]
    if not revenue_values and not roe_values:
        return ""

    revenue_low = 0.0 if min(revenue_values or [0.0]) >= 0 else min(revenue_values or [0.0])
    revenue_high = max(revenue_values or [0.0])
    if revenue_low == revenue_high:
        revenue_high = revenue_low + 1
    revenue_scale = (bottom - top) / (revenue_high - revenue_low)
    roe_low, roe_high, roe_scale = _normalize_points(roe_values or [0.0], top, bottom)
    chart_parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="매출과 ROE 추세 차트" style="width:100%;height:320px;display:block;margin-bottom:10px;background:#fbfcff;border:1px solid #eef0f4;border-radius:8px">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fbfcff" rx="8"/>',
        f'<text x="{left}" y="28" fill="#262b38" font-size="13" font-weight="700">매출 추세</text>',
        f'<circle cx="{left + 86}" cy="24" r="5" fill="#2451e6"/><text x="{left + 98}" y="28" fill="#6b7385" font-size="11">매출</text>',
        f'<line x1="{left + 142}" y1="24" x2="{left + 154}" y2="24" stroke="#0ea371" stroke-width="3" stroke-linecap="round"/><circle cx="{left + 148}" cy="24" r="4.5" fill="#0ea371" stroke="#fff" stroke-width="1.5"/><text x="{left + 166}" y="28" fill="#6b7385" font-size="11">ROE</text>',
        f'<text x="{width - right}" y="28" fill="#6b7385" font-size="11" text-anchor="end">좌: 매출 · 우: ROE</text>',
    ]
    for index in range(4):
        y = top + (bottom - top) / 3 * index
        chart_parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#edf0f6" stroke-width="1"/>'
        )
    chart_parts.extend(
        [
            f'<line x1="{left}" y1="{bottom}" x2="{width - right}" y2="{bottom}" stroke="#d7dce6" stroke-width="1.2"/>',
            f'<text x="{left}" y="{top - 10}" fill="#7a8394" font-size="10">{escape(_axis_krw(revenue_high))}</text>',
            f'<text x="{left}" y="{bottom + 18}" fill="#7a8394" font-size="10">{escape(_axis_krw(revenue_low))}</text>',
            f'<text x="{width - right}" y="{top - 10}" fill="#7a8394" font-size="10" text-anchor="end">{escape(_axis_percent(roe_high))}</text>',
            f'<text x="{width - right}" y="{bottom + 18}" fill="#7a8394" font-size="10" text-anchor="end">{escape(_axis_percent(roe_low))}</text>',
        ]
    )

    line_points = []
    for idx in range(count):
        x = left + step * idx + step / 2
        if idx < len(revenue) and isinstance(revenue[idx], (int, float)):
            value = float(revenue[idx])
            y = bottom - (value - revenue_low) * revenue_scale
            bar_top = min(max(y, top), bottom)
            bar_height = max(bottom - bar_top, 3)
            color = "#2451e6" if value >= 0 else "#f0436b"
            label = _trend_display(trend, "revenue", idx, value, "원")
            chart_parts.append(
                f'<rect x="{x - bar_width / 2:.1f}" y="{bar_top:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" rx="6" fill="{color}">'
                f'<title>{escape(str(labels[idx] if idx < len(labels) else years[idx]))} 매출 {escape(label)}</title></rect>'
            )
        if idx < len(roe) and isinstance(roe[idx], (int, float)):
            value = float(roe[idx])
            y = bottom - (value - roe_low) * roe_scale
            line_points.append((x, y, value))
        chart_parts.append(
            f'<text x="{x:.1f}" y="{height - 28}" fill="#6b7385" font-size="11" text-anchor="middle">{escape(str(labels[idx] if idx < len(labels) else years[idx]))}</text>'
        )

    if line_points:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in line_points)
        chart_parts.append(f'<polyline points="{points}" fill="none" stroke="#0ea371" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
        for idx, (x, y, value) in enumerate(line_points):
            color = "#0ea371" if value >= 0 else "#f0436b"
            label = _trend_display(trend, "roe", idx, value, "%")
            chart_parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{color}" stroke="#fff" stroke-width="2">'
                f'<title>ROE {escape(label)}</title></circle>'
            )
    chart_parts.append("</svg>")
    return "".join(chart_parts)


def _insight_metric(label: str, value: Any, unit: str = "") -> str:
    return f"""
        <div>
          <div style="font-size:11px;color:#6b7385">{escape(label)}</div>
          <strong style="display:block;margin-top:3px;font-size:14px;color:#262b38">{escape(_fmt(value, unit) if isinstance(value, (int, float)) else (str(value) if value else '-'))}</strong>
        </div>
"""


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
            f"""
        <article style="border:1px solid #e2e5ec;border-radius:10px;padding:14px;background:#fff">
          <div style="font-size:12px;color:#6b7385;margin-bottom:10px">배당</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            {_insight_metric('보통주 DPS', dividend.get('dps_common'), '원')}
            {_insight_metric('배당수익률', dividend.get('dividend_yield_common'), '%')}
            {_insight_metric('배당성향', dividend.get('payout_ratio'), '%')}
            {_insight_metric('DART EPS', dividend.get('dart_eps'), '원')}
          </div>
        </article>
"""
        )
    if _has_insight_value(major, ("name", "ratio")) or _has_insight_value(minor, ("held_ratio", "shareholders")):
        cards.append(
            f"""
        <article style="border:1px solid #e2e5ec;border-radius:10px;padding:14px;background:#fff">
          <div style="font-size:12px;color:#6b7385;margin-bottom:10px">주주 구성</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            {_insight_metric('최대주주', major.get('name'))}
            {_insight_metric('최대주주 지분율', major.get('ratio'), '%')}
            {_insight_metric('소액주주 지분율', minor.get('held_ratio'), '%')}
            {_insight_metric('소액주주 수', minor.get('shareholders'), '명')}
          </div>
        </article>
"""
        )
    if _has_insight_value(audit, ("auditor", "opinion")):
        cards.append(
            f"""
        <article style="border:1px solid #e2e5ec;border-radius:10px;padding:14px;background:#fff">
          <div style="font-size:12px;color:#6b7385;margin-bottom:10px">감사의견</div>
          <div style="display:grid;gap:10px">
            {_insight_metric('감사인', audit.get('auditor'))}
            {_insight_metric('의견', audit.get('opinion'))}
          </div>
        </article>
"""
        )
    if not cards:
        return ""
    return f"""
    <section>
      <h3 style="font-size:15px;margin:0 0 10px;color:#262b38">DART 추가 인사이트</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px">
        {''.join(cards)}
      </div>
    </section>
"""


def _analyst_plan_section(analyst_plan: dict[str, Any]) -> str:
    briefs = analyst_plan.get("section_briefs") or {}
    order = analyst_plan.get("section_order") or list(briefs)
    if not briefs:
        return ""
    items = []
    for key in order[:6]:
        brief = briefs.get(key)
        if not brief:
            continue
        items.append(
            f"""
        <li style="margin-bottom:7px">
          <strong style="color:#262b38">{escape(str(key))}</strong>
          <span style="color:#4d5566"> — {escape(str(brief))}</span>
        </li>
"""
        )
    if not items:
        return ""
    return f"""
    <section style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:16px">
      <h3 style="font-size:15px;margin:0 0 8px;color:#262b38">Analyst Frame</h3>
      <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.65">{''.join(items)}</ul>
    </section>
"""


def _source_policy_section(meta: dict[str, Any]) -> str:
    summary = meta.get("retrieval_summary") or {}
    if not summary:
        return ""
    sources = summary.get("financial_sources") or []
    network_calls = int(summary.get("financial_network_calls") or 0)
    cache_hits = int(summary.get("financial_cache_hits") or 0)
    stale_refreshes = int(summary.get("financial_stale_refreshes") or 0)
    bypassed = int(summary.get("financial_bypassed_cache") or 0)
    rows = []
    for source in sources[:6]:
        status = str(source.get("cache_status") or "")
        status_color = "#0ea371" if status == "hit" else "#2451e6" if status in {"miss", "bypass"} else "#e08a00"
        rcepts = ", ".join(source.get("rcept_nos") or [])
        rows.append(
            f"<tr>"
            f"<td style=\"padding:8px;border-bottom:1px solid #eef0f4\">{escape(str(source.get('bsns_year', '')))}</td>"
            f"<td style=\"padding:8px;border-bottom:1px solid #eef0f4\">{escape(str(source.get('reprt_code', '')))} / {escape(str(source.get('fs_div', '')))}</td>"
            f"<td style=\"padding:8px;border-bottom:1px solid #eef0f4\"><strong style=\"color:{status_color}\">{escape(status)}</strong></td>"
            f"<td style=\"padding:8px;border-bottom:1px solid #eef0f4\">{escape(str(source.get('row_count', 0)))} rows</td>"
            f"<td style=\"padding:8px;border-bottom:1px solid #eef0f4\">{escape(rcepts or '-')}</td>"
            f"</tr>"
        )
    rows_html = "".join(rows) or "<tr><td colspan=\"5\" style=\"padding:8px;color:#6b7385\">표시할 원문 출처가 없습니다.</td></tr>"
    mode_text = (
        "실시간 재조회 중심"
        if bypassed
        else "TTL 캐시 확인 후 조건부 재조회"
    )
    return f"""
    <section style="background:#fff;border:1px solid #d9e2f5;border-radius:12px;padding:16px">
      <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap">
        <div>
          <h3 style="font-size:15px;margin:0 0 6px;color:#262b38">DART Source Policy</h3>
          <p style="margin:0;color:#6b7385;font-size:12px;line-height:1.55">{escape(mode_text)} · 원문 TTL {escape(str(summary.get('financial_statement_ttl_seconds', '-')))}초</p>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;font-size:12px">
          <span style="border:1px solid #d9e2f5;border-radius:999px;padding:5px 9px;color:#2451e6;background:#f5f8ff">network {network_calls}</span>
          <span style="border:1px solid #d9e2f5;border-radius:999px;padding:5px 9px;color:#0ea371;background:#f6fffb">cache hit {cache_hits}</span>
          <span style="border:1px solid #d9e2f5;border-radius:999px;padding:5px 9px;color:#e08a00;background:#fffaf2">stale {stale_refreshes}</span>
        </div>
      </div>
      <div style="overflow:auto;margin-top:12px">
        <table style="width:100%;border-collapse:collapse;font-size:12px;min-width:680px">
          <caption style="text-align:left;color:#6b7385;font-size:11px;margin-bottom:6px">이번 분석에 사용된 DART 원문 조회/캐시 상태</caption>
          <thead><tr style="color:#6b7385;text-align:left"><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">연도</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">보고서/fs</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">상태</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">원문 행</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">접수번호</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </section>
"""


def _interpretation_title(meta: dict[str, Any]) -> str:
    provider = str(meta.get("llm_provider") or "unknown")
    if provider == "qwen":
        return "Qwen 해석"
    if provider == "openai":
        return "OpenAI 보조 해석"
    if provider == "template":
        return "규칙 기반 안전 해석"
    return "AI 해석"


def _storage_contract_section(meta: dict[str, Any]) -> str:
    payload = meta.get("erd_payload") or {}
    if not payload:
        return ""
    report = payload.get("fundamental_report") or {}
    ratio_count = len(payload.get("report_ratios") or [])
    evidence_count = len(payload.get("report_evidence") or [])
    verification = payload.get("report_verification") or {}
    return f"""
    <details style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:14px">
      <summary style="cursor:pointer;font-size:13px;font-weight:800;color:#2451e6">저장 계약 미리보기</summary>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:12px;font-size:12px;color:#4d5566">
        <div><div style="color:#6b7385">report_id</div><strong style="color:#262b38;word-break:break-all">{escape(str(report.get('id', '-')))}</strong></div>
        <div><div style="color:#6b7385">data_status</div><strong style="color:#262b38">{escape(str(report.get('data_status', '-')))}</strong></div>
        <div><div style="color:#6b7385">ratios</div><strong style="color:#262b38">{ratio_count} rows</strong></div>
        <div><div style="color:#6b7385">evidence</div><strong style="color:#262b38">{evidence_count} rows</strong></div>
        <div><div style="color:#6b7385">verification</div><strong style="color:#262b38">{escape(str(verification.get('outcome', '-')))}</strong></div>
      </div>
    </details>
"""


def _mermaid_id(value: str) -> str:
    return "n_" + "".join(char if char.isalnum() else "_" for char in value)


def _mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def _evidence_graph_section(evidence_graph: dict[str, Any]) -> str:
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
    for edge in edges[:80]:
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source and target:
            relation = _mermaid_label(str(edge.get("relation") or "relates_to"))
            lines.append(f"  {_mermaid_id(source)} -- {relation} --> {_mermaid_id(target)}")
    mermaid = "\n".join(lines)
    return f"""
    <details style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:14px">
      <summary style="cursor:pointer;font-size:13px;font-weight:800;color:#2451e6">Evidence Graph Mermaid</summary>
      <pre style="white-space:pre-wrap;overflow:auto;margin:12px 0 0;background:#f7f8fa;border:1px solid #eef0f4;border-radius:8px;padding:12px;font-size:11px;line-height:1.45;color:#262b38">{escape(mermaid)}</pre>
    </details>
"""


def _verification_section(meta: dict[str, Any]) -> str:
    summary = meta.get("verification_summary") or {}
    if not summary:
        return ""
    items = [
        ("수치-출처 결속", summary.get("binding_passed")),
        ("단위/일관성", summary.get("consistency_passed")),
        ("LLM guard", summary.get("guard_passed")),
        ("결론 안정성", summary.get("verdict_stable")),
    ]
    cards = []
    for label, ok in items:
        color = "#0ea371" if ok else "#e08a00"
        text = "pass" if ok else "check"
        cards.append(
            f"""
        <div style="border:1px solid #e2e5ec;border-radius:8px;padding:11px;background:#fff">
          <div style="font-size:11px;color:#6b7385">{escape(label)}</div>
          <strong style="display:block;margin-top:4px;color:{color};font-size:15px">{escape(text)}</strong>
        </div>
"""
        )
    reasons = ", ".join(summary.get("reasons") or []) or "특이 사항 없음"
    return f"""
    <section style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:16px">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap">
        <div>
          <h3 style="font-size:15px;margin:0 0 6px;color:#262b38">Verification Gate</h3>
          <p style="margin:0;color:#6b7385;font-size:12px;line-height:1.55">outcome {escape(str(summary.get('outcome', '-')))} · regen {escape(str(summary.get('regen_count', 0)))} · {escape(str(summary.get('initial_provider', '-')))} → {escape(str(summary.get('final_provider', '-')))}</p>
        </div>
        <p style="margin:0;color:#6b7385;font-size:12px;line-height:1.55">reasons: {escape(reasons)}</p>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:12px">{''.join(cards)}</div>
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
) -> str:
    evidence_rows = "".join(
        f"<tr><td>{escape(item.metric)}</td><td>{escape(_fmt(item.value, item.unit))}</td><td>{escape(item.fiscal_year)}</td><td>{escape(', '.join(item.account_ids))}</td><td><a href=\"{escape(item.source_url)}\" target=\"_blank\" rel=\"noopener\">{escape(item.rcept_no)}</a></td></tr>"
        for item in evidence
    )
    flag_items = "".join(
        f"<li><code>{escape(flag)}</code> — {escape(FLAG_DESCRIPTIONS.get(flag, '추적용 리스크 플래그입니다.'))}</li>"
        for flag in risk_flags
    ) or "<li>특이 플래그 없음</li>"
    trend_json = escape(json.dumps(trend, ensure_ascii=False))
    insights = insights or {}
    score_breakdown = score_breakdown or {}
    analyst_plan = analyst_plan or {}
    evidence_graph = evidence_graph or {}
    meta = meta or {}
    period = meta.get("period_basis") or {}
    report_name = period.get("report_name") or meta.get("reprt_name") or "사업보고서"
    period_description = period.get("description") or f"{report_name} 기준"
    period_badge = "분기 기준" if period.get("is_interim") else "연간 기준"
    trend_title = f"{len(trend.get('years', []))}개 기간 추세 데이터"
    trend_chart = _trend_chart_svg(trend)
    confidence_color = _confidence_tone(confidence)
    guard_violations = meta.get("llm_guard_violations") or []
    gate_label = "검증 게이트 통과" if not guard_violations else "검증 게이트 재확인 필요"
    gate_color = "#0ea371" if not guard_violations else "#e08a00"
    peer_text = ""
    peer_score_text = ""
    if meta.get("peer_rank") and meta.get("peer_count"):
        peer_group = meta.get("peer_group_label") or meta.get("peer_group", "동종군")
        peer_text = f"{peer_group} {meta['peer_rank']}/{meta['peer_count']} · {meta.get('peer_label', '')}"
        if meta.get("peer_percentile") is not None:
            peer_score_text = f"동종군 백분위 {meta['peer_percentile']}점"
    score_note = score_breakdown.get("score_explanation", "")
    print_style = """
<style>
@media print {
  .verith-financial-report { border:0 !important; max-width:none !important; }
  .verith-financial-report section,
  .verith-financial-report article,
  .verith-financial-report details { break-inside:avoid; page-break-inside:avoid; }
  .verith-financial-report table { page-break-inside:auto; }
  .verith-financial-report a { color:#161922 !important; text-decoration:none; }
}
</style>
"""
    return f"""
{print_style}
<section class="verith-financial-report" style="font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#161922;background:#f7f8fa;border:1px solid #e2e5ec;border-radius:12px;overflow:hidden;max-width:1440px;margin:0 auto">
  <header style="background:#fff;padding:20px 22px;border-bottom:1px solid #e2e5ec">
    <div style="font-size:12px;font-weight:700;color:#2451e6;letter-spacing:.04em;text-transform:uppercase">Fundamental Health</div>
    <h2 style="margin:6px 0 4px;font-size:22px;line-height:1.3;color:#161922">{escape(corp_name)} <span style="color:#6b7385;font-size:16px">({escape(ticker)})</span></h2>
    <p style="margin:0;color:#6b7385;font-size:13px">DART 공시 기반 재무 분석 · {escape(str(period_description))}. 본 분석은 정보 제공 목적이며 투자 권유가 아닙니다.</p>
  </header>
  <div style="padding:20px 22px;display:grid;gap:16px">
    <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">
      <div style="background:#fff;border:1px solid #e2e5ec;border-radius:8px;padding:14px">
        <div style="font-size:12px;color:#6b7385">절대 재무점수</div>
        <strong style="display:block;font-size:36px;line-height:1;color:#2451e6;margin-top:6px">{score}</strong>
        <p style="margin:8px 0 0;font-size:11px;line-height:1.45;color:#2451e6;font-weight:700">{escape(period_badge)}</p>
        {f'<p style="margin:8px 0 0;font-size:11px;line-height:1.45;color:#6b7385">{escape(peer_text)}</p>' if peer_text else ''}
        {f'<p style="margin:4px 0 0;font-size:12px;line-height:1.45;color:#2451e6;font-weight:700">{escape(peer_score_text)}</p>' if peer_score_text else ''}
      </div>
      <div style="background:#fff;border:1px solid #e2e5ec;border-radius:8px;padding:14px">
        <div style="font-size:12px;color:#6b7385">재무 상태</div>
        <strong style="display:block;font-size:20px;color:#161922;margin-top:8px">{escape(LABELS.get(label, label))}</strong>
      </div>
      <div style="background:#fff;border:1px solid #e2e5ec;border-radius:8px;padding:14px">
        <div style="font-size:12px;color:#6b7385">데이터 신뢰도</div>
        <strong style="display:block;font-size:20px;color:{confidence_color};margin-top:8px">{confidence:.2f}</strong>
      </div>
      <div style="background:#fff;border:1px solid #e2e5ec;border-radius:8px;padding:14px">
        <div style="font-size:12px;color:#6b7385">증거 연결</div>
        <strong style="display:block;font-size:20px;color:#161922;margin-top:8px">{len(evidence)}개</strong>
        <p style="margin:8px 0 0;font-size:11px;line-height:1.45;color:{gate_color};font-weight:700">{escape(gate_label)}</p>
      </div>
    </section>
    {f'<section style="background:#fff;border:1px solid #e2e5ec;border-radius:8px;padding:13px 15px"><p style="margin:0;color:#4d5566;font-size:13px;line-height:1.6">{escape(score_note)}</p></section>' if score_note else ''}
    <section>
      <h3 style="font-size:15px;margin:0 0 10px;color:#262b38">핵심 재무지표</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px">{_ratio_cards(ratios)}</div>
    </section>
    <section style="background:#fff;border:1px solid #e2e5ec;border-radius:8px;padding:16px" data-trend="{trend_json}">
      <h3 style="font-size:15px;margin:0 0 10px;color:#262b38">{escape(trend_title)}</h3>
      {trend_chart}
      <details>
        <summary style="cursor:pointer;font-size:12px;font-weight:700;color:#2451e6">표로 보기</summary>
        <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:10px">
          <caption style="text-align:left;color:#6b7385;font-size:11px;margin-bottom:6px">DART 공시 기준 기간별 매출, 영업이익, ROE</caption>
          <thead><tr style="color:#6b7385;text-align:left"><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">기간</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">매출</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">영업이익</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">ROE</th></tr></thead>
          <tbody>{_trend_rows(trend)}</tbody>
        </table>
      </details>
    </section>
    <section style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:16px">
      <h3 style="font-size:15px;margin:0 0 8px;color:#262b38">{escape(_interpretation_title(meta))}</h3>
      <p style="margin:0;line-height:1.7;color:#3a4051;font-size:14px">{escape(interpretation)}</p>
    </section>
    {_analyst_plan_section(analyst_plan)}
    {_verification_section(meta)}
    {_source_policy_section(meta)}
    {_evidence_graph_section(evidence_graph)}
    {_insight_section(insights)}
    <section style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:16px;overflow:auto">
      <h3 style="font-size:15px;margin:0 0 10px;color:#262b38">Evidence & Citations</h3>
      <table style="width:100%;border-collapse:collapse;font-size:12px;min-width:720px">
        <caption style="text-align:left;color:#6b7385;font-size:11px;margin-bottom:6px">계산 지표와 연결된 DART 계정 및 접수번호</caption>
        <thead><tr style="color:#6b7385;text-align:left"><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">metric</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">value</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">year</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">account_ids</th><th scope="col" style="padding:8px;border-bottom:1px solid #eef0f4">DART</th></tr></thead>
        <tbody>{evidence_rows}</tbody>
      </table>
    </section>
    <section style="background:#fff;border:1px solid #e2e5ec;border-radius:12px;padding:16px">
      <h3 style="font-size:15px;margin:0 0 8px;color:#262b38">Risk Flags & Data Limits</h3>
      <ul style="margin:0;padding-left:18px;color:#4d5566;font-size:13px;line-height:1.7">{flag_items}</ul>
    </section>
    {_storage_contract_section(meta)}
  </div>
</section>
""".strip()
