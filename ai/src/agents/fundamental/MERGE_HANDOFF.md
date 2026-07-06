# Fundamental Agent Merge Handoff

## Current Status

This package is an MVP-quality fundamental sub-agent core focused on report intelligence.
Backend/frontend service integration is out of scope for this workstream.

Completed:

- DART financial statement collection for the fixed 10-company battery universe
- DART regular disclosure enrichment for BPS, dividend, shareholder, and audit-opinion context
- Deterministic ratio calculation, score calculation, confidence, and risk flags
- T7 score model: linear interpolation, negative-value gradients, missing-metric renormalization, and turnaround-aware growth scoring
- Qwen-first interpretation path with OpenAI/template fallback
- LangGraph node workflow under `nodes/`
- Evidence Graph / GraphRAG-style context builder for account, filing, metric, and claim grounding
- Analyst Plan that guides Qwen toward a professional report structure
- LLM output guard against unsupported numbers, investment advice, and unsupported metrics, with batch-visible `guard_violations`
- Evidence binding to DART `rcept_no` and account ids
- Report payload with `report_html`, chart-ready `trend`, `ratios`, `insights`, and account-level `evidence`
- Display-ready values such as `display_value` and `trend.display`
- ERD storage-preview payload under `meta.erd_payload`
- 10-company batch demo with `sector_relative_score` and peer rank
- Verification Gate and DART Source Policy sections in generated HTML/Markdown outputs
- Local tests and demo scripts under `api_test`

Not completed:

- Cross-service backend/frontend integration
- Persistent job queue, scheduler, retry queue, or async worker orchestration
- Production observability dashboards and structured tracing export
- User-facing frontend components in the shared `frontend` folder
- Full analyst-grade peer/sector model beyond the fixed 10-company demo universe
- Multi-turn agent memory or tool-planning loop

## Agent Maturity

What exists now:

```text
request
  -> collect_node
  -> normalize_node
  -> calc_node
  -> evidence_node
  -> interpret_node
  -> verify_node
  -> report_node
```

This is enough for integration testing and frontend prototype work.

What a fully agentized version still needs:

```text
planner node
  -> evidence graph / GraphRAG retrieval over filings and account bindings
  -> analyst role prompt
  -> critic role prompt
  -> final report writer
  -> deterministic guard and fallback
```

## Merge Scope

Prefer merging only:

```text
ai/src/agents/fundamental/
```

Be careful with repository-level changes currently visible in the working tree:

```text
.gitignore
ai/pyproject.toml
ai/uv.lock
ai/src/main.py
docker-compose.yaml
codex-prompt/
```

Those may be team-level or accidental local changes. Do not merge or remove them as part of the fundamental handoff unless the team lead confirms.

## Frontend Contract

Frontend should prefer display-ready fields:

| payload field | purpose |
| --- | --- |
| `ratios[*].display_value` | card/table display |
| `trend.display.revenue` | KRW revenue labels |
| `trend.display.op_income` | KRW operating-income labels |
| `trend.display.roe` | ROE labels |
| `evidence[*].display_value` | evidence table values |
| `meta.sector_relative_score` | peer-relative display score |
| `score` | deterministic absolute financial score |

Raw numeric values should still be used for charts, sorting, and recalculation.

## Source Policy

Financial statement retrieval is mediated by `retrieval/source_policy.py`.

Current behavior:

- Annual mode uses a 24-hour TTL cache for DART financial statement rows.
- Stale cache can be used when refresh fails, with `STALE_DART_CACHE_FALLBACK`.
- Latest mode currently bypasses cache for every analyzed year. T5 is expected to narrow this to the newest year only.
- DART correction-filing invalidation is not implemented yet; the 24-hour TTL is the current approximation.
- `data/latest_report.py` probe calls are not fully represented in `retrieval_summary` yet; T5 will align probe accounting.

Cache keys include `corp_code`, `bsns_year`, `reprt_code`, and `fs_div`.

## Storage Contract Notes

`meta.erd_payload` is a backend-facing preview only. The agent does not write to DB.

- ERD-extra fields such as `request_id`, `verdict_label`, `risk_flags`, ratio `status/reason/display_value`, evidence `currency`, and `retrieval_summary` may be ignored by a backend that only supports the base ERD.
- `report_id` is trace-id based and therefore creates a new row per execution for history preservation.
- If the backend needs only the latest report per ticker/year/report code, dedupe by `(stock_code, bsns_year, reprt_code)`.

## Verification

Run from `C:\verith\ai`:

```bat
C:\verith\.venv\Scripts\python.exe -m pytest src\agents\fundamental\tests -v
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.make_sample_payload
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.make_qwen_markdown
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --latest --ticker 373220 --years 4 LG에너지솔루션 최신 공시 기준 재무 리포트 만들어줘
C:\verith\.venv\Scripts\python.exe -m ruff check
```

Expected recent result:

```text
49 passed
batch_demo done: ok=10 fail=0
T7 batch score distribution: min=17 median=48.5 max=58
```

Generated review files:

```text
ai/src/agents/fundamental/api_test/samples/fundamental_response_sample.json
ai/src/agents/fundamental/api_test/samples/fundamental_report_sample.html
ai/src/agents/fundamental/api_test/samples/qwen_output_sample.md
ai/src/agents/fundamental/api_test/out/summary.md
```

## Next Work

1. Add a planner node that decides which financial dimensions deserve emphasis before Qwen writes.
2. Expand Evidence Graph into a richer GraphRAG layer for filing sections, account aliases, and report citations.
3. Split Qwen into analyst and critic roles: first draft, then critique, then final report.
4. Add deterministic report sections such as executive summary, profitability, stability, growth, valuation basis, risk, and data limits.
5. Expand scoring from absolute financial health to analyst-style sector model if the team wants less conservative report labels.
6. Improve Korean report tone so the final output reads like an analyst memo, not a demo summary.
