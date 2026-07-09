# Research Report JSON Schema

This document defines the recommended JSON payload for serving the static
research report UI in `make_report/report_template.html`, which
`make_report/render.py` fills in. The UI can stay mostly the same while the
backend swaps the report data per user question.

## Top-Level Shape

```json
{
  "schemaVersion": "research-report.v1",
  "reportId": "rpt_20260707_ecopro_supply_chain",
  "createdAt": "2026-07-07T13:52:00+09:00",
  "locale": "ko-KR",
  "question": {},
  "answer": {},
  "metrics": {},
  "graph": {
    "nodes": [],
    "edges": []
  },
  "evidence": [],
  "execution": {},
  "graphSnapshot": {}
}
```

## Field Definitions

### `question`

Represents the user question and the pipeline's classification.

```json
{
  "text": "What downstream companies are affected by Ecopro's raw-material supply path?",
  "type": "path_impact_propagation",
  "label": "Path impact propagation"
}
```

Rules:

- `text` is required and should preserve the original user question.
- `type` is a machine-readable classifier label, such as `relational`,
  `qualitative`, `global`, `factual`, `path_impact_propagation`, or a benchmark
  question type.
- `label` is display text for the report.

### `answer`

Contains the user-facing answer and faithfulness metadata.

```json
{
  "headline": "Ecopro's material supply path expands through Ecopro BM into battery-cell and automotive customers.",
  "body": "The graph result shows that Ecopro supplies raw materials to affiliates, and Ecopro BM forms a material-supply axis connected to SK On and SK Innovation.",
  "tags": ["Ecopro", "Ecopro BM", "SK On", "SK Innovation"],
  "faithfulness": {
    "status": "warning",
    "label": "Some claims include verification warnings",
    "unsupportedClaims": [
      {
        "sentence": "The downstream path reaches Volkswagen and Mercedes-Benz.",
        "reason": "The graph path exists, but direct quote evidence is incomplete."
      }
    ]
  }
}
```

Rules:

- `headline`, `body`, and `tags` are required.
- `faithfulness.status` should be one of `verified`, `warning`, `unchecked`, or
  `failed`.
- `unsupportedClaims` should be an empty array when there are no warnings.
- Do not put citation markers directly inside `body`; citations are rendered
  from `evidence`.

### `metrics`

Small numeric summary shown near the top of the report.

```json
{
  "rows": 25,
  "attempts": 1,
  "graphEdges": 8,
  "graphNodes": 6,
  "citations": 8
}
```

Rules:

- `rows` is the number of query result rows before prompt truncation.
- `attempts` is the number of Cypher generation attempts.
- `graphEdges`, `graphNodes`, and `citations` should match the rendered report
  payload, not necessarily the whole Neo4j database.

### `graph.nodes`

Nodes rendered in the relationship graph.

```json
{
  "id": "company:ecopro",
  "label": "Ecopro",
  "type": "Company",
  "role": "Raw-material sourcing",
  "kind": "upstream",
  "position": {
    "x": 115,
    "y": 260
  }
}
```

Rules:

- `id` is required and must be globally unique within the report.
- Use stable ID prefixes such as `company:`, `industry:`, `policy:`, `product:`,
  `person:`, or `aggregate:`.
- `type` should match graph labels when possible: `Company`, `Industry`,
  `Product`, `Policy`, or `Person`.
- `kind` controls node styling. Recommended values are `upstream`, `midstream`,
  `customer`, `downstream`, `policy`, `industry`, or `aggregate`.
- `position` is optional for future auto-layout, but required by the current
  static SVG implementation.

### `graph.edges`

Edges rendered between graph nodes.

```json
{
  "id": "edge:g1",
  "source": "company:ecopro",
  "target": "company:ecoprobm",
  "relation": "SUPPLIES",
  "label": "Raw-material supply",
  "style": "solid",
  "evidenceIds": ["ev:G1"]
}
```

Rules:

- `id` is required and must be globally unique within the report.
- `source` and `target` must reference existing `graph.nodes[].id` values.
- `relation` should use the fixed project schema when applicable:
  `SUPPLIES`, `COMPETES_WITH`, `OWNS_STAKE`, `BELONGS_TO`, or
  `BENEFITS_FROM`.
- Additional report-level relations such as `COMMUNITY` may be used for future
  GDS/community views.
- `style` should be `solid` or `dashed`.
- `evidenceIds` must reference existing `evidence[].id` values.

### `evidence`

Citations and source material that support graph edges and answer claims.

```json
{
  "id": "ev:G1",
  "ref": "G1",
  "kind": "graph",
  "edgeId": "edge:g1",
  "relation": "SUPPLIES",
  "title": "Ecopro -> Ecopro BM",
  "quote": "The company has a trading business that supplies key minerals secured through overseas resource-development investments to subsidiaries.",
  "source": {
    "name": "Ecopro annual report",
    "publisher": "DART",
    "reportName": "Annual report (2025.12)",
    "stockCode": "086520",
    "url": "http://dart.fss.or.kr/report/viewer.do?...",
    "textFragmentUrl": "http://dart.fss.or.kr/report/viewer.do?...#:~:text=..."
  }
}
```

Rules:

- `id` is required and should use a stable prefix such as `ev:`.
- `ref` is the short citation label shown to the user, such as `G1` or `V1`.
- `kind` should be one of `graph`, `vector`, `aggregate`, or `manual`.
- `edgeId` is required for graph evidence and should reference
  `graph.edges[].id`.
- `relation` should match the related edge relation when applicable.
- `quote` should be the exact source quote whenever possible.
- `source.url` is the document-level source URL.
- `source.textFragmentUrl` should deep-link to the exact quote when available.

### `execution`

Pipeline and reproducibility details.

```json
{
  "pipeline": [
    {
      "id": "classify",
      "title": "Question classification",
      "status": "done",
      "statusText": "Implemented",
      "body": "The LangGraph classify node separates relational, qualitative, and global questions."
    }
  ],
  "cypher": "MATCH path = (a:Company {name: 'Ecopro'})-[:SUPPLIES*1..5]->(c:Company) RETURN ...",
  "retrievalFlow": "LangGraph classify -> Cypher -> Neo4j rows -> grounded answer -> faithfulness gate"
}
```

Rules:

- `pipeline[].status` should be `done`, `next`, `running`, `failed`, or
  `skipped`.
- `cypher` should be the generated or executed Cypher when the answer used graph
  retrieval.
- If the answer used only vector retrieval, `cypher` may be an empty string and
  `retrievalFlow` should explain the fallback path.

### `graphSnapshot`

Database-level context at the time of report generation.

```json
{
  "nodes": {
    "Company": 371,
    "Industry": 85,
    "Policy": 42
  },
  "relationships": {
    "SUPPLIES": 77,
    "BENEFITS_FROM": 66,
    "COMPETES_WITH": 21,
    "OWNS_STAKE": 300
  }
}
```

Rules:

- This section is informational and should not drive graph rendering.
- Counts should describe the loaded graph snapshot, not only the report subgraph.

## Complete Example

```json
{
  "schemaVersion": "research-report.v1",
  "reportId": "rpt_20260707_ecopro_supply_chain",
  "createdAt": "2026-07-07T13:52:00+09:00",
  "locale": "ko-KR",
  "question": {
    "text": "에코프로에서 시작된 원료·소재 공급이 어떤 경로로 어떤 기업까지 파급되는가?",
    "type": "path_impact_propagation",
    "label": "Path impact propagation"
  },
  "answer": {
    "headline": "Ecopro's material supply path expands through Ecopro BM into battery-cell and automotive customers.",
    "body": "The graph result shows that Ecopro supplies raw materials to affiliates, and Ecopro BM forms a material-supply axis connected to SK On and SK Innovation.",
    "tags": ["Ecopro", "Ecopro BM", "SK On", "SK Innovation"],
    "faithfulness": {
      "status": "warning",
      "label": "Some claims include verification warnings",
      "unsupportedClaims": []
    }
  },
  "metrics": {
    "rows": 25,
    "attempts": 1,
    "graphEdges": 1,
    "graphNodes": 2,
    "citations": 1
  },
  "graph": {
    "nodes": [
      {
        "id": "company:ecopro",
        "label": "Ecopro",
        "type": "Company",
        "role": "Raw-material sourcing",
        "kind": "upstream",
        "position": { "x": 115, "y": 260 }
      },
      {
        "id": "company:ecoprobm",
        "label": "Ecopro BM",
        "type": "Company",
        "role": "Cathode material manufacturing",
        "kind": "midstream",
        "position": { "x": 325, "y": 260 }
      }
    ],
    "edges": [
      {
        "id": "edge:g1",
        "source": "company:ecopro",
        "target": "company:ecoprobm",
        "relation": "SUPPLIES",
        "label": "Raw-material supply",
        "style": "solid",
        "evidenceIds": ["ev:G1"]
      }
    ]
  },
  "evidence": [
    {
      "id": "ev:G1",
      "ref": "G1",
      "kind": "graph",
      "edgeId": "edge:g1",
      "relation": "SUPPLIES",
      "title": "Ecopro -> Ecopro BM",
      "quote": "The company has a trading business that supplies key minerals secured through overseas resource-development investments to subsidiaries.",
      "source": {
        "name": "Ecopro annual report",
        "publisher": "DART",
        "reportName": "Annual report (2025.12)",
        "stockCode": "086520",
        "url": "http://dart.fss.or.kr/report/viewer.do?...",
        "textFragmentUrl": "http://dart.fss.or.kr/report/viewer.do?...#:~:text=..."
      }
    }
  ],
  "execution": {
    "pipeline": [
      {
        "id": "classify",
        "title": "Question classification",
        "status": "done",
        "statusText": "Implemented",
        "body": "The LangGraph classify node separates relational, qualitative, and global questions."
      }
    ],
    "cypher": "MATCH path = (a:Company {name: 'Ecopro'})-[:SUPPLIES*1..5]->(c:Company) RETURN ...",
    "retrievalFlow": "LangGraph classify -> Cypher -> Neo4j rows -> grounded answer -> faithfulness gate"
  },
  "graphSnapshot": {
    "nodes": {
      "Company": 371,
      "Industry": 85,
      "Policy": 42
    },
    "relationships": {
      "SUPPLIES": 77,
      "BENEFITS_FROM": 66,
      "COMPETES_WITH": 21,
      "OWNS_STAKE": 300
    }
  }
}
```

## Frontend Mapping Notes

The current static UI expects `reportData.nodes`, `reportData.edges`, and
`reportData.evidence`. A service payload can be adapted with a thin mapping
layer:

```js
const reportData = {
  date: payload.createdAt.slice(0, 10),
  questionType: payload.question.type,
  faithfulness: payload.answer.faithfulness.label,
  question: payload.question.text,
  answer: {
    headline: payload.answer.headline,
    body: payload.answer.body,
    tags: payload.answer.tags
  },
  metrics: payload.metrics,
  graphSnapshot: {
    nodes: Object.entries(payload.graphSnapshot.nodes)
      .map(([label, count]) => `${label} ${count}`)
      .join(" · "),
    relationships: Object.entries(payload.graphSnapshot.relationships)
      .map(([type, count]) => `${type} ${count}`)
      .join(" · "),
    retrieval: payload.execution.retrievalFlow
  },
  nodes: payload.graph.nodes.map((node) => ({
    id: node.id,
    label: node.label,
    role: node.role,
    kind: node.kind,
    x: node.position.x,
    y: node.position.y
  })),
  edges: payload.graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    relation: edge.relation,
    label: edge.label,
    dashed: edge.style === "dashed",
    evidence: edge.evidenceIds
  })),
  evidence: payload.evidence.map((item) => ({
    id: item.ref,
    edgeId: item.edgeId,
    relation: item.relation,
    title: item.title,
    quote: item.quote,
    source: item.source.reportName || item.source.name,
    url: item.source.textFragmentUrl || item.source.url
  })),
  cypher: payload.execution.cypher,
  pipeline: payload.execution.pipeline
};
```

## Validation Checklist

- Every `graph.edges[].source` and `graph.edges[].target` exists in
  `graph.nodes[].id`.
- Every `graph.edges[].evidenceIds[]` exists in `evidence[].id`.
- Every graph evidence item with `edgeId` references an existing edge.
- `metrics.graphNodes` equals `graph.nodes.length`.
- `metrics.graphEdges` equals `graph.edges.length`.
- `metrics.citations` equals `evidence.length`.
- `answer.body` contains no hardcoded citation labels.
- `source.url` is present for every externally cited source.
- `schemaVersion` changes when a breaking field rename or semantic change is
  introduced.
