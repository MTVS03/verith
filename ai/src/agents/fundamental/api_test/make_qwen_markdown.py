"""Create a UTF-8 Markdown note from the latest sample payload.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.make_qwen_markdown

The output file is written in UTF-8. Open it in VS Code or paste it into Notion;
avoid `type`/`more` in legacy CMD because Korean text may look broken there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..report.formatting import format_metric_value


SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
SAMPLE_JSON = SAMPLES_DIR / "fundamental_response_sample.json"
OUT_MD = SAMPLES_DIR / "qwen_output_sample.md"


def ratio_line(name: str, item: dict[str, Any]) -> str:
    value = item.get("value")
    unit = item.get("unit", "")
    year = item.get("fiscal_year", "")
    display = format_metric_value(value, unit)
    reason = item.get("reason", "")
    return f"| `{name}` | {display} | {year} | {reason} |"


def main() -> int:
    if not SAMPLE_JSON.exists():
        print(f"missing sample json: {SAMPLE_JSON}")
        print("run: python -m src.agents.fundamental.api_test.make_sample_payload")
        return 2

    data = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    ratios = data.get("ratios", {})
    evidence = data.get("evidence", [])
    meta = data.get("meta", {})
    flags = data.get("risk_flags", [])

    lines = [
        "# Fundamental Agent Qwen 출력 샘플",
        "",
        "## 실행 명령어",
        "",
        "```bat",
        "cd C:\\verith\\ai",
        "C:\\verith\\.venv\\Scripts\\python.exe -m src.agents.fundamental.api_test.make_sample_payload",
        "```",
        "",
        "## 실행 결과 요약",
        "",
        f"- 기업: {data.get('corp_name')} (`{data.get('ticker')}`)",
        f"- LLM provider: `{meta.get('llm_provider')}`",
        f"- LLM model: `{meta.get('llm_model')}`",
        f"- score: `{data.get('score')}`",
        f"- verdict_label: `{data.get('verdict_label')}`",
        f"- confidence: `{data.get('confidence')}`",
        f"- risk_flags: {', '.join(f'`{flag}`' for flag in flags) if flags else '없음'}",
        "",
        "## Qwen 생성 문장",
        "",
        "### Verdict",
        "",
        data.get("verdict", ""),
        "",
        "### Interpretation",
        "",
        data.get("interpretation", ""),
        "",
        "## 주요 재무 지표",
        "",
        "| metric | value | fiscal_year | 산출불가 사유 |",
        "| --- | ---: | --- | --- |",
    ]
    lines.extend(ratio_line(name, item) for name, item in ratios.items())

    lines.extend(
        [
            "",
            "## Evidence / DART 출처",
            "",
            "| metric | value | fiscal_year | rcept_no | account_ids |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for item in evidence:
        account_ids = ", ".join(f"`{account_id}`" for account_id in item.get("account_ids", []))
        display = format_metric_value(item.get("value"), item.get("unit", ""))
        lines.append(
            f"| `{item.get('metric')}` | {display} | "
            f"{item.get('fiscal_year')} | `{item.get('rcept_no')}` | {account_ids} |"
        )

    lines.extend(
        [
            "",
            "## 프론트/백엔드 연동 참고 필드",
            "",
            "- `ratios`: 비율 그리드 렌더링",
            "- `trend`: 차트 렌더링",
            "- `evidence`: DART 원문 링크와 수치 출처",
            "- `report_html`: 격리 삽입용 financial HTML block",
            "- `meta.llm_provider`: Qwen/OpenAI/template 사용 여부 확인",
            "",
        ]
    )

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_MD}")
    print("open this file in VS Code or paste it into Notion. Do not use legacy CMD type/more for Korean text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
