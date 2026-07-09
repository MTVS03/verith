import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.agents.industry.make_report.render import (
    ReportPayloadError,
    SKIP_SELF_REFETCH,
    TEMPLATE_PATH,
    render_payload_file,
    render_report_html,
    validate_payload,
)

EXAMPLE_PAYLOAD = TEMPLATE_PATH.parent / "example_payload.json"
AI_ROOT = Path(__file__).resolve().parents[4]


def load_example() -> dict:
    return json.loads(EXAMPLE_PAYLOAD.read_text(encoding="utf-8"))


def embedded_payload(html: str) -> dict:
    match = re.search(
        r'<script id="research-report-data" type="application/json">\n(.*?)\n</script>',
        html,
        re.DOTALL,
    )
    assert match, "rendered HTML has no research-report-data block"
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_example_payload_is_valid():
    validate_payload(load_example())


def test_render_embeds_payload_verbatim():
    payload = load_example()

    html = render_report_html(payload)

    assert embedded_payload(html) == payload


def test_render_inlines_support_js():
    html = render_report_html(load_example())

    assert 'src="./support.js"' not in html
    assert "DCLogic" in html


def test_inlined_support_js_cannot_hijack_template_extraction():
    """support.js re-scans the raw page for the first `<x-dc>` unless __resources is set.

    Its own source contains that literal, so without the guard the runtime renders
    its source instead of the report.
    """
    support_js = (TEMPLATE_PATH.parent / "support.js").read_text(encoding="utf-8")
    assert "<x-dc" in support_js, "hazard gone; the guard may no longer be needed"

    html = render_report_html(load_example())

    assert SKIP_SELF_REFETCH in html
    assert html.index(SKIP_SELF_REFETCH) < html.index("<x-dc")


def test_payload_containing_script_tag_does_not_break_out():
    payload = load_example()
    payload["answer"]["body"] = "닫는 태그 </script> 를 포함한 답변"

    html = render_report_html(payload)

    data_block = html.split('<script id="research-report-data" type="application/json">')[1]
    data_block = data_block.split("\n</script>")[0]
    assert "</script>" not in data_block
    assert embedded_payload(html)["answer"]["body"] == payload["answer"]["body"]


def test_edge_referencing_unknown_node_is_rejected():
    payload = load_example()
    payload["graph"]["edges"][0]["target"] = "company:missing"

    with pytest.raises(ReportPayloadError, match="references unknown node company:missing"):
        validate_payload(payload)


def test_edge_referencing_unknown_evidence_is_rejected():
    payload = load_example()
    payload["graph"]["edges"][0]["evidenceIds"] = ["ev:MISSING"]

    with pytest.raises(ReportPayloadError, match="references unknown evidence ev:MISSING"):
        validate_payload(payload)


def test_evidence_referencing_unknown_edge_is_rejected():
    payload = load_example()
    payload["evidence"][0]["edgeId"] = "edge:missing"

    with pytest.raises(ReportPayloadError, match="references unknown edge edge:missing"):
        validate_payload(payload)


def test_metrics_mismatch_is_rejected():
    payload = load_example()
    payload["metrics"]["citations"] = 7

    with pytest.raises(ReportPayloadError, match=r"metrics.citations is 7 but the payload has 1"):
        validate_payload(payload)


def test_duplicate_node_id_is_rejected():
    payload = load_example()
    payload["graph"]["nodes"][1]["id"] = payload["graph"]["nodes"][0]["id"]
    payload["graph"]["edges"][0]["target"] = payload["graph"]["nodes"][0]["id"]

    with pytest.raises(ReportPayloadError, match="duplicate graph.nodes id"):
        validate_payload(payload)


def test_missing_required_keys_are_reported_together():
    with pytest.raises(ReportPayloadError) as excinfo:
        validate_payload({})

    message = str(excinfo.value)
    for expected in ("schemaVersion", "question.text", "answer.headline", "graph", "metrics"):
        assert expected in message


def test_render_report_html_validates_by_default():
    payload = load_example()
    payload["metrics"]["graphNodes"] = 99

    with pytest.raises(ReportPayloadError):
        render_report_html(payload)

    assert render_report_html(payload, validate=False)


def test_render_payload_file_writes_html(tmp_path):
    out = tmp_path / "nested" / "report.html"

    result = render_payload_file(EXAMPLE_PAYLOAD, out)

    assert result == out
    assert embedded_payload(out.read_text(encoding="utf-8")) == load_example()


def test_cli_renders_payload_to_file(tmp_path):
    out = tmp_path / "report.html"

    subprocess.run(
        [sys.executable, "-m", "src.agents.industry.make_report",
         str(EXAMPLE_PAYLOAD), "--out", str(out)],
        cwd=AI_ROOT,
        check=True,
        capture_output=True,
    )

    assert embedded_payload(out.read_text(encoding="utf-8")) == load_example()


def test_cli_rejects_invalid_payload(tmp_path):
    payload = load_example()
    payload["metrics"]["citations"] = 7
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "src.agents.industry.make_report",
         str(bad), "--out", str(tmp_path / "report.html")],
        cwd=AI_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    assert "metrics.citations" in result.stderr
    assert not (tmp_path / "report.html").exists()


def test_renderer_imports_without_agent_runtime():
    """The renderer exists so a backend can render without LangGraph or Neo4j."""
    probe = (
        "import sys;"
        "import src.agents.industry.make_report.render;"
        "heavy=[m for m in sys.modules if m.split('.')[0] in {'langgraph','neo4j','langchain'}];"
        "sys.exit(1) if heavy else None"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=AI_ROOT, capture_output=True, text=True
    )

    assert result.returncode == 0, f"renderer pulled in agent runtime deps: {result.stdout}"
