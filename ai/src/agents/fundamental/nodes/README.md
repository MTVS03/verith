# Fundamental LangGraph Nodes

The fundamental agent now runs through a LangGraph workflow. Business logic stays
in package modules, while each node adapts that logic to graph state.

## Workflow

```text
collect
  -> normalize
  -> calculate
  -> evidence
  -> interpret
  -> verify
  -> report
```

| node | role |
| --- | --- |
| `collect_node.py` | Resolve ticker, fetch DART financial rows, fetch share count and regular-disclosure insights |
| `normalize_node.py` | Explicit split point for future evidence normalization and GraphRAG enrichment |
| `calc_node.py` | Calculate ratios, evidence, trend, score, and deterministic risk flags |
| `evidence_node.py` | Build Evidence Graph, Analyst Plan, and retrieval context for Qwen |
| `interpret_node.py` | Call Qwen/OpenAI/template interpretation |
| `verify_node.py` | Guard LLM output, retry once, and fallback to template when needed |
| `report_node.py` | Attach display fields, build HTML, and assemble `FundamentalResponse` |
| `state.py` | Shared graph state contract |
| `workflow.py` | LangGraph `StateGraph` wiring |

## GraphRAG Slot

GraphRAG here means fundamental evidence grounding, not service integration.
The current `evidence_node.py` builds a deterministic graph-style context from
metrics, filings, account ids, insights, and risk flags. A later version can
replace or enrich this with vector/graph retrieval over filing text.

Recommended future data graph:

```text
company -> filing -> statement -> account -> metric -> evidence -> report claim
```

That graph can support account alias retrieval, filing-section citations, and
reasoned evidence selection before the LLM interpretation step.
