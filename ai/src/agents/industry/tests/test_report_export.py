from src.agents.industry.report_export import (
    build_graph_and_evidence,
    build_report_payload,
    parse_answer,
)


def test_parse_answer_removes_citations_and_unsupported_block():
    answer = (
        "에코프로에서 시작된 공급은 SK온까지 이어집니다. ⚠️미검증\n\n"
        "⚠️ 검증되지 않은 진술 1건:\n"
        "- \"에코프로에서 시작된 공급은 SK온까지 이어집니다.\"\n\n"
        "근거\n"
        "[G1] 에코프로-[SUPPLIES]->에코프로비엠: \"quote\" [↗원문](http://example.com)"
    )

    parsed = parse_answer(answer)

    assert "근거" not in parsed["body"]
    assert "검증되지 않은 진술" not in parsed["body"]
    assert parsed["faithfulness"]["status"] == "warning"
    assert parsed["faithfulness"]["unsupportedClaims"] == [
        {
            "sentence": "에코프로에서 시작된 공급은 SK온까지 이어집니다.",
            "reason": "The faithfulness gate marked this claim as unsupported.",
        }
    ]


def test_build_graph_and_evidence_from_rows():
    rows = [
        {
            "chain": ["에코프로", "에코프로비엠", "SK온"],
            "evidence_edges": [
                {
                    "source": "에코프로",
                    "relation": "SUPPLIES",
                    "target": "에코프로비엠",
                    "evidences": ["원료를 자회사에 공급"],
                    "origins": ["086520"],
                },
                {
                    "source": "에코프로비엠",
                    "relation": "SUPPLIES",
                    "target": "SK온",
                    "evidences": ["주요 매출처는 SK온"],
                    "origins": ["247540"],
                },
            ],
        }
    ]

    nodes, edges, evidence = build_graph_and_evidence(rows, [])

    node_ids = {node["id"] for node in nodes}
    evidence_ids = {item["id"] for item in evidence}
    assert len(nodes) == 3
    assert len(edges) == 2
    assert len(evidence) == 2
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in edges)
    assert all(ev_id in evidence_ids for edge in edges for ev_id in edge["evidenceIds"])
    assert evidence[0]["kind"] == "graph"
    assert evidence[0]["ref"] == "G1"


def test_vector_chunks_become_vector_evidence():
    chunk = {
        "company": "엔켐",
        "section": "사업의 개요",
        "report_nm": "사업보고서 (2025.12)",
        "bsns_year": "2025",
        "score": 0.8123,
        "source_url": "http://example.com/report",
        "text": "전해액 사업 설명",
    }

    _nodes, _edges, evidence = build_graph_and_evidence([], [chunk])

    assert evidence == [
        {
            "id": "ev:V1",
            "ref": "V1",
            "kind": "vector",
            "edgeId": "",
            "relation": "",
            "title": "엔켐 · 사업의 개요 · 사업보고서 (2025.12)",
            "quote": "전해액 사업 설명",
            "score": 0.8123,
            "source": {
                "name": "엔켐",
                "publisher": "DART",
                "reportName": "사업보고서 (2025.12)",
                "stockCode": "",
                "section": "사업의 개요",
                "bsnsYear": "2025",
                "url": "http://example.com/report",
                "textFragmentUrl": "http://example.com/report",
            },
        }
    ]


def test_graph_evidence_does_not_repeat_the_report_name():
    """The report joins source.name and source.reportName, so they must not be equal."""
    rows = [
        {
            "evidence_edges": [
                {
                    "source": "에코프로",
                    "relation": "SUPPLIES",
                    "target": "에코프로비엠",
                    "evidences": ["원료를 자회사에 공급"],
                    "origins": ["086520"],
                }
            ]
        }
    ]

    _nodes, _edges, evidence = build_graph_and_evidence(rows, [])

    source = evidence[0]["source"]
    assert not (source["name"] and source["name"] == source["reportName"])


def test_build_report_payload_has_resolvable_references():
    final_state = {
        "question": "에코프로 공급 경로는?",
        "label": "relational",
        "cypher": "MATCH path = ...",
        "attempts": 1,
        "rows": [
            {
                "evidence_edges": [
                    {
                        "source": "에코프로",
                        "relation": "SUPPLIES",
                        "target": "에코프로비엠",
                        "evidences": ["원료 공급"],
                        "origins": [],
                    }
                ]
            }
        ],
        "chunks": [],
        "answer": "에코프로는 에코프로비엠으로 공급합니다.\n\n근거\n[G1] x",
    }

    payload = build_report_payload(
        final_state,
        graph_snapshot={"nodes": {"Company": 2}, "relationships": {"SUPPLIES": 1}},
        created_at="2026-07-07T13:52:00+09:00",
    )

    node_ids = {node["id"] for node in payload["graph"]["nodes"]}
    evidence_ids = {item["id"] for item in payload["evidence"]}
    assert payload["schemaVersion"] == "research-report.v1"
    assert payload["metrics"]["graphNodes"] == len(payload["graph"]["nodes"])
    assert payload["metrics"]["graphEdges"] == len(payload["graph"]["edges"])
    assert payload["metrics"]["citations"] == len(payload["evidence"])
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids
        for edge in payload["graph"]["edges"]
    )
    assert all(
        evidence_id in evidence_ids
        for edge in payload["graph"]["edges"]
        for evidence_id in edge["evidenceIds"]
    )
