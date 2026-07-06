# verith Fundamental Agent

This package owns the financial/fundamental sub-agent only. It does not mount
FastAPI routes, write to backend storage, or modify supervisor routing.
The entrypoint runs through a LangGraph node workflow under `nodes/`.

## Entrypoint

```python
from src.agents.fundamental.core.contract import FundamentalRequest
from src.agents.fundamental.graph import analyze_fundamental

response = await analyze_fundamental(
    FundamentalRequest(
        request_id="uuid-from-supervisor",
        trace_id="trace-id",
        ticker="373220",
        years=4,
    )
)
```

Supported failures:

| exception | meaning |
| --- | --- |
| `ValueError("UNSUPPORTED_TICKER")` | ticker is outside the fixed 10-company universe |
| `RuntimeError("DART_EMPTY_DATA")` | DART returned no usable rows |
| `DartApiError` | DART returned a non-success status |

## Supported Universe

| ticker | company |
| --- | --- |
| 051910 | LG Chem |
| 373220 | LG Energy Solution |
| 006400 | Samsung SDI |
| 096770 | SK Innovation |
| 086520 | EcoPro |
| 247540 | EcoPro BM |
| 003670 | POSCO Future M |
| 066970 | L&F |
| 348370 | Enchem |
| 361610 | SK IE Technology |

## Environment

| variable | required | note |
| --- | --- | --- |
| `DART_API_KEY` | yes | OpenDART API key |
| `QWEN_API_KEY` | no | Team-standard variable name. It stores the Qwen base URL, e.g. `http://pbd.mtvs2026.work:8000/v1` |
| `QWEN_BASE_URL` | no | Optional local alias for the same value |
| `QWEN_MODEL` | no | Local Qwen model name |
| `OPENAI_API_KEY` | no | Used only when Qwen fails |
| `OPENAI_MODEL` | no | Defaults to `gpt-4o-mini` |
| `LLM_TIMEOUT` | no | Defaults to 20 seconds |

## Response Contract

`FundamentalResponse` returns:

| field | meaning |
| --- | --- |
| `verdict`, `interpretation` | LLM/template prose; numeric facts must come from code output |
| `verdict_label`, `score`, `confidence` | deterministic code output |
| `score_breakdown` | component scores, Korean display label, score explanation, optional peer-relative rank |
| `ratios` | ROE, margins, growth, debt/current ratio, EPS/BPS fields with `display_value` |
| `trend` | chart-ready yearly series plus formatted `display` values |
| `insights` | DART regular-report context: dividend, major/minor holders, audit opinion |
| `evidence` | DART `rcept_no`, account bindings, and `display_value` for each numeric claim |
| `risk_flags` | missing data, fallback, and verification flags |
| `report_html` | self-contained financial section block |
| `meta` | provider/model, corp_code, fs_div, latency, trace_id, retrieval/verification summaries, optional `erd_payload` |

## LLM Policy

The agent calculates all numbers before any LLM call. The LLM only writes
Korean interpretation prose.

Fallback order:

1. Qwen OpenAI-compatible endpoint
2. OpenAI mini model
3. Rule-based template

If Qwen fails 3 consecutive times, the process skips Qwen for 60 seconds.
Template fallback adds `LLM_FALLBACK_TEMPLATE` and reduces confidence.

## Risk Flags

| flag | meaning |
| --- | --- |
| `OFS_FALLBACK` | CFS rows were unavailable and OFS was used |
| `DERIVED_LIABILITIES` | liabilities were derived from equity and total equity/liabilities |
| `MISSING_*` | a metric could not be calculated |
| `LLM_FALLBACK_OPENAI` | Qwen failed and OpenAI path was used or attempted |
| `LLM_FALLBACK_TEMPLATE` | prose came from deterministic template |
| `VERIFY_BALANCE_IDENTITY_FAILED_*` | assets did not match liabilities plus equity |
| `VERIFY_LLM_OUTPUT_REJECTED` | LLM prose failed guard checks after retry |
| `VERDICT_STABILITY_GUARDED` | final verdict text and deterministic label need review |
| `EVIDENCE_UNBOUND_EXCLUDED` | evidence without DART binding was removed |

## Local Checks

From `C:\verith\ai`:

```bat
C:\verith\ai\src\agents\fundamental\api_test\run_checks.bat
```

Individual commands:

```bat
C:\verith\.venv\Scripts\python.exe -m pytest src\agents\fundamental\tests -v
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.check_qwen
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.make_sample_payload
C:\verith\.venv\Scripts\python.exe -m ruff check
```

User-style agent test:

```bat
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --question "LG에너지솔루션 최근 4개년 재무 리포트 만들어줘"
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --latest --ticker 373220 --years 4 LG에너지솔루션 최신 공시 기준 재무 리포트 만들어줘
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent
```

The interactive runner exercises the fundamental sub-agent as a user would:

```text
question -> ticker intent -> LangGraph nodes -> DART/Qwen -> analyst report
```

It writes Markdown and HTML reports under `api_test/out/ask_agent/`.

Freshness modes:

| option | behavior |
| --- | --- |
| default | Uses annual report mode and may reuse local DART cache |
| `--no-cache` | Uses annual report mode but bypasses cache |
| `--latest` | Discovers the newest available DART filing code and bypasses cache |

`api_test/out/` is throwaway batch output. `api_test/samples/` is the stable
handoff payload for backend/frontend integration.

## Score Notes

The 100-point score is deterministic. It is driven by profitability, stability,
and growth ratios:

- profitability: ROE and operating margin
- stability: debt ratio and current ratio
- growth: revenue growth and operating-income growth

Scoring uses anchor-point interpolation rather than step-only buckets. Mild
negative profitability is therefore separated from severe loss cases. If a
metric is unavailable, the score is renormalized over the attainable maximum as
long as at least three core metrics are scoreable. Growth metrics with
`direction=turnaround_positive` receive partial credit; continued loss or
negative turnaround remains explicit zero.

The label cutoffs remain unchanged:

- `strong`: score >= 70
- `moderate`: score >= 45
- `weak`: score < 45
- `insufficient_data`: too few reliable core metrics

Batch demos add a peer-relative layer across the fixed 10-company battery
universe:

- `peer_rank`: score rank within the 10 companies
- `peer_percentile`: relative percentile in that peer group
- `peer_label`: Korean display label such as `동종군 상위권`

The internal contract keeps `verdict_label` as `strong/moderate/weak`, while
HTML and summaries display Korean labels such as `양호/중립/주의`.

## Source Policy

Financial statement retrieval uses `retrieval/source_policy.py`:

- annual mode: 24-hour TTL cache
- latest mode: currently bypasses cache for all analyzed years
- stale cache fallback is allowed when refresh fails
- correction-filing invalidation is not implemented yet; TTL is the current approximation

Generated reports expose this in `meta.retrieval_summary`, Markdown output, and
the HTML DART Source Policy section.

## Frontend Handoff

See `FRONTEND_INTEGRATION.md` for the recommended UI sections, payload fields,
score display rule, and KRW formatting rule.

## Merge Handoff

See `MERGE_HANDOFF.md` for current maturity, merge scope, verification commands,
and the remaining production-agent roadmap.
