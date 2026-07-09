"""Render a research-report.v1 payload into a standalone report HTML."""

from .render import (
    ReportPayloadError,
    TEMPLATE_PATH,
    render_payload_file,
    render_report_html,
    validate_payload,
)

__all__ = [
    "ReportPayloadError",
    "TEMPLATE_PATH",
    "render_payload_file",
    "render_report_html",
    "validate_payload",
]
