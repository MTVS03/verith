"""Inject a research-report.v1 payload into the report HTML template.

The template (``report_template.html``) already knows how to read a payload: it
looks up ``<script id="research-report-data">`` and maps it onto its view model.
When that element is missing it silently falls back to hardcoded mockup data, so
this module validates the payload before injecting it -- a rejected payload must
raise rather than produce a report that looks fine but shows the mockup.

This module deliberately depends on nothing but the standard library. Importing
it must never pull in LangGraph or Neo4j, so a backend can turn a stored payload
into HTML without the agent runtime.

Run:
    uv run python -m src.agents.industry.make_report report.json --out report.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parent / "report_template.html"
SUPPORT_TAG = '<script src="./support.js"></script>'
DATA_SCRIPT_ID = "research-report-data"

# After booting from the DOM, support.js re-fetches location.href and re-extracts the
# template by scanning the raw source for the first `<x-dc>` with a regex. Once support.js
# is inlined, its own source is part of that raw text -- and it contains the literal string
# "<x-dc> block" inside an error message, which the regex matches first. The runtime then
# renders 8KB of its own source instead of the report. Setting __resources makes it trust
# the DOM it already parsed and skip the refetch. It is otherwise a CDN URL override map,
# so an empty object leaves React loading unchanged.
SKIP_SELF_REFETCH = "window.__resources = window.__resources || {};"


class ReportPayloadError(ValueError):
    """The payload violates the research-report.v1 schema."""


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for value in ids:
        if value in seen and value not in dupes:
            dupes.append(value)
        seen.add(value)
    return dupes


def validate_payload(payload: Any) -> None:
    """Raise ``ReportPayloadError`` listing every schema violation at once."""
    if not isinstance(payload, dict):
        raise ReportPayloadError(f"payload must be a JSON object, got {type(payload).__name__}")

    problems: list[str] = []

    for key in ("schemaVersion", "metrics", "evidence"):
        if key not in payload:
            problems.append(f"missing required key: {key}")
    if not _as_dict(payload.get("question")).get("text"):
        problems.append("missing required key: question.text")
    for key in ("headline", "body", "tags"):
        if not _as_dict(payload.get("answer")).get(key):
            problems.append(f"missing required key: answer.{key}")
    if "graph" not in payload:
        problems.append("missing required key: graph")

    graph = _as_dict(payload.get("graph"))
    nodes = _as_list(graph.get("nodes"))
    edges = _as_list(graph.get("edges"))
    evidence = _as_list(payload.get("evidence"))

    node_ids = [str(node.get("id")) for node in nodes if _as_dict(node).get("id")]
    edge_ids = [str(edge.get("id")) for edge in edges if _as_dict(edge).get("id")]
    evidence_ids = [str(item.get("id")) for item in evidence if _as_dict(item).get("id")]

    if len(node_ids) != len(nodes):
        problems.append("every graph.nodes[] entry needs an id")
    if len(edge_ids) != len(edges):
        problems.append("every graph.edges[] entry needs an id")
    if len(evidence_ids) != len(evidence):
        problems.append("every evidence[] entry needs an id")

    for name, ids in (("graph.nodes", node_ids), ("graph.edges", edge_ids), ("evidence", evidence_ids)):
        for duplicate in _duplicates(ids):
            problems.append(f"duplicate {name} id: {duplicate}")

    known_nodes = set(node_ids)
    known_edges = set(edge_ids)
    known_evidence = set(evidence_ids)

    for edge in edges:
        edge = _as_dict(edge)
        edge_id = edge.get("id", "?")
        for end in ("source", "target"):
            ref = edge.get(end)
            if ref and str(ref) not in known_nodes:
                problems.append(f"edge {edge_id}: {end} references unknown node {ref}")
            elif not ref:
                problems.append(f"edge {edge_id}: missing {end}")
        for ref in _as_list(edge.get("evidenceIds")):
            if str(ref) not in known_evidence:
                problems.append(f"edge {edge_id}: evidenceIds references unknown evidence {ref}")

    for item in evidence:
        item = _as_dict(item)
        edge_ref = item.get("edgeId")
        if edge_ref and str(edge_ref) not in known_edges:
            problems.append(f"evidence {item.get('id', '?')}: edgeId references unknown edge {edge_ref}")

    metrics = _as_dict(payload.get("metrics"))
    for key, actual in (("graphNodes", len(nodes)), ("graphEdges", len(edges)), ("citations", len(evidence))):
        if key in metrics and metrics[key] != actual:
            problems.append(f"metrics.{key} is {metrics[key]} but the payload has {actual}")

    if problems:
        raise ReportPayloadError(
            "invalid research-report payload:\n" + "\n".join(f"  - {p}" for p in problems)
        )


def render_report_html(
    payload: dict[str, Any],
    template_path: Path = TEMPLATE_PATH,
    *,
    validate: bool = True,
) -> str:
    """Return standalone report HTML with ``payload`` embedded."""
    if validate:
        validate_payload(payload)

    has_template = template_path.exists()
    if has_template:
        template = template_path.read_text(encoding="utf-8")
    else:
        template = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>산업/거시 보고서</title></head><body></body></html>'

    support_path = template_path.parent / "support.js"
    if support_path.exists():
        support_js = support_path.read_text(encoding="utf-8").replace("</script", "<\\/script")
        template = template.replace(
            SUPPORT_TAG,
            f"<script>\n{SKIP_SELF_REFETCH}\n{support_js}\n</script>",
            1,
        )

    data = json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")
    script = f'<script id="{DATA_SCRIPT_ID}" type="application/json">\n{data}\n</script>\n'
    if not has_template:
        script += _fallback_report_script()

    marker = "</body>"
    if marker not in template:
        return template + "\n" + script
    return template.replace(marker, script + marker, 1)


def render_payload_file(
    json_path: Path,
    out_path: Path,
    template_path: Path = TEMPLATE_PATH,
    *,
    validate: bool = True,
) -> Path:
    """Read a payload JSON file and write the rendered report to ``out_path``."""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    html = render_report_html(payload, template_path, validate=validate)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _fallback_report_script() -> str:
    """Plain HTML renderer used when the DC/React runtime cannot boot."""
    return r"""<script>
setTimeout(() => {
  if (document.getElementById('dc-root')) return;
  const dataEl = document.getElementById('research-report-data');
  if (!dataEl) return;
  let payload;
  try { payload = JSON.parse(dataEl.textContent || '{}'); } catch { return; }
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const answer = payload.answer || {};
  const question = payload.question || {};
  const metrics = payload.metrics || {};
  const nodes = ((payload.graph || {}).nodes || []).slice(0, 40);
  const edges = ((payload.graph || {}).edges || []).slice(0, 80);
  const evidence = (payload.evidence || []).slice(0, 80);
  const tags = (answer.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
  const edgeRows = edges.map(e => `<tr><td>${esc(e.label || e.relation)}</td><td>${esc(e.source)}</td><td>${esc(e.target)}</td></tr>`).join('');
  const evRows = evidence.map(ev => {
    const src = ev.source || {};
    const url = src.textFragmentUrl || src.url || '';
    const link = url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">원문</a>` : '';
    return `<article class="evidence"><b>[${esc(ev.ref || ev.id)}] ${esc(ev.title)}</b><p>${esc(ev.quote)}</p><small>${esc(src.name || src.reportName || 'GraphRAG 결과')} ${link}</small></article>`;
  }).join('');
  document.body.innerHTML = `
    <style>
      body{margin:0;background:#eceef3;color:#1b1e26;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
      main{max-width:1120px;margin:0 auto;padding:32px 22px 56px}
      section{background:#fff;border:1px solid rgba(20,26,40,.08);border-radius:18px;padding:24px;margin-top:16px;box-shadow:0 8px 28px rgba(20,30,60,.07)}
      h1{font-size:34px;margin:0 0 10px} h2{font-size:18px;margin:0 0 14px}
      .meta,.muted{color:#6a7280;font-size:13px}.tag{display:inline-block;margin:4px;padding:7px 11px;border:1px solid #d9deea;border-radius:999px;font-weight:700;font-size:13px}
      .metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.metric{background:#f7f9fc;border-radius:12px;padding:14px}.metric b{display:block;font-size:24px}
      table{width:100%;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #edf0f5;padding:9px;text-align:left;vertical-align:top}
      .evidence{border:1px solid #edf0f5;border-radius:12px;padding:14px;margin:10px 0;background:#fbfcfe}.evidence p{white-space:pre-line;line-height:1.6}
      a{color:#2b53c0;text-decoration:none}
    </style>
    <main>
      <div class="meta">GraphRAG · ${esc(payload.schemaVersion || 'research-report.v1')} · fallback renderer</div>
      <section><h1>산업/거시 보고서</h1><p>${esc(question.text || '')}</p><p class="meta">${esc(payload.createdAt || '')} · ${esc(question.label || question.type || '')}</p></section>
      <section><h2>답변 요약</h2><h3>${esc(answer.headline || '분석 결과')}</h3><p style="white-space:pre-line;line-height:1.75">${esc(answer.body || '')}</p><div>${tags}</div></section>
      <section><h2>지표</h2><div class="metrics"><div class="metric">조회 행<b>${esc(metrics.rows || 0)}</b></div><div class="metric">노드<b>${esc(metrics.graphNodes || nodes.length)}</b></div><div class="metric">엣지<b>${esc(metrics.graphEdges || edges.length)}</b></div><div class="metric">근거<b>${esc(metrics.citations || evidence.length)}</b></div></div></section>
      <section><h2>관계 그래프 데이터</h2><table><thead><tr><th>관계</th><th>출발</th><th>도착</th></tr></thead><tbody>${edgeRows}</tbody></table></section>
      <section><h2>근거</h2>${evRows || '<p class="muted">근거 없음</p>'}</section>
    </main>`;
}, 1000);
</script>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a research-report.v1 payload JSON into standalone report HTML."
    )
    parser.add_argument("payload", type=Path, help="Path to the payload JSON file.")
    parser.add_argument("--out", type=Path, help="Output HTML path. Prints to stdout when omitted.")
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH, help="Report HTML template path.")
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip schema validation. The template falls back to mockup data on a bad payload.",
    )
    args = parser.parse_args()

    try:
        if args.out:
            render_payload_file(args.payload, args.out, args.template, validate=not args.no_validate)
            return
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        html = render_report_html(payload, args.template, validate=not args.no_validate)
    except ReportPayloadError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        sys.stdout.write(html)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(html.encode("utf-8"))
