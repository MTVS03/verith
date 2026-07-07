"""Step 4: load the extracted graph into Neo4j.

Reads ``data/extracted/graph_documents.json`` (the normalized nodes +
relationships produced by Step 3) and ``MERGE``s them into Neo4j. This is a pure
downstream load — normalization already happened in Step 3, so nothing is
re-normalized here.

Critical rules honored (CLAUDE.md):
* Always ``MERGE``, never ``CREATE`` — re-running never duplicates nodes/edges.
* Node labels and relationship types are validated against the fixed schema
  (``NODE_LABELS`` / ``REL_TYPES`` from ``schema.py``) before being interpolated
  into Cypher — labels/rel-types can't be query parameters, so this keeps us on
  the fixed schema and guards against injection.

Usage::

    uv run python -m src.agents.industry.ingest            # merge + verify
    uv run python -m src.agents.industry.ingest --reset    # wipe, then load
    uv run python -m src.agents.industry.ingest --verify-only
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

from .config import EXTRACTED_DIR, get_neo4j_graph
from .schema import NODE_LABELS, REL_TYPES


def load_graph_documents() -> dict:
    """Read the Step 3 output that Step 4 ingests."""
    path = EXTRACTED_DIR / "graph_documents.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run Step 3 first: "
            "uv run python -m src.agents.industry.extract --from-cache"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _label(name: str) -> str:
    """Validate a node label against the fixed schema and backtick-quote it."""
    if name not in NODE_LABELS:
        raise ValueError(f"Unknown node label {name!r}; not in {sorted(NODE_LABELS)}")
    return f"`{name}`"


def _rel(name: str) -> str:
    """Validate a relationship type against the fixed schema and quote it."""
    if name not in REL_TYPES:
        raise ValueError(f"Unknown relationship type {name!r}; not in {sorted(REL_TYPES)}")
    return f"`{name}`"


def _to_float(val) -> float | None:
    """Parse an equity-% string ("31.52") to a float for numeric Cypher filters.

    qota_rt arrives as a string; storing it verbatim makes `e.qota_rt >= 20`
    compare lexicographically ("100" < "20"). Cast here so the property lands as
    a Neo4j Float. Non-numeric values (should not occur post-Step-3) degrade to
    None rather than crashing the whole load.
    """
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def reset(graph) -> None:
    """Delete every relational-graph node (clears stale nodes before a reload).

    Scoped to exclude ``:Chunk`` — those belong to Step 1's vector layer
    (``vectorize.py``), which owns its own lifecycle (scoped per-company
    replace) and is a separate, expensive-to-rebuild (GPU embedding) index.
    A bare ``MATCH (n) DETACH DELETE n`` here previously wiped :Chunk too,
    silently killing vector search until ``vectorize.py`` was rerun.
    """
    graph.query("MATCH (n) WHERE NOT n:Chunk DETACH DELETE n")
    print("Reset: deleted all non-Chunk nodes and relationships.")


def create_constraints(graph) -> None:
    """One uniqueness constraint per node label — enforces no duplicate nodes and
    makes MERGE-by-name fast."""
    for label in sorted(NODE_LABELS):
        graph.query(
            f"CREATE CONSTRAINT IF NOT EXISTS "
            f"FOR (n:{_label(label)}) REQUIRE n.name IS UNIQUE"
        )
    print(f"Constraints ensured on {len(NODE_LABELS)} labels (name IS UNIQUE).")


def ingest_nodes(graph, nodes: list[dict]) -> None:
    """MERGE nodes, batched one query per label."""
    by_label: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        by_label[n["type"]].append({"id": n["id"]})

    total = 0
    for label, rows in sorted(by_label.items()):
        graph.query(
            f"UNWIND $rows AS row MERGE (n:{_label(label)} {{name: row.id}})",
            {"rows": rows},
        )
        total += len(rows)
        print(f"  nodes {label}: {len(rows)}")
    print(f"Merged {total} nodes.")


def ingest_relationships(graph, rels: list[dict]) -> None:
    """MERGE relationships, batched one query per (source_type, rel, target_type).

    Endpoints are MERGEd defensively so an edge never silently drops if a node is
    missing. ``origins`` (provenance) and ``qota_rt`` (equity %, OWNS_STAKE only)
    ride along as edge properties.
    """
    by_shape: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rels:
        key = (r["source_type"], r["type"], r["target_type"])
        by_shape[key].append(
            {
                "source": r["source"],
                "target": r["target"],
                "origins": r.get("origins", []),
                "evidences": r.get("evidences", []),
                "qota_rt": _to_float(r.get("properties", {}).get("qota_rt")),
            }
        )

    total = 0
    for (src_t, rel_t, tgt_t), rows in sorted(by_shape.items()):
        graph.query(
            f"""
            UNWIND $rows AS row
            MERGE (s:{_label(src_t)} {{name: row.source}})
            MERGE (t:{_label(tgt_t)} {{name: row.target}})
            MERGE (s)-[e:{_rel(rel_t)}]->(t)
            SET e.origins = row.origins
            SET e.evidences = row.evidences
            FOREACH (_ IN CASE WHEN row.qota_rt IS NULL THEN [] ELSE [1] END |
                     SET e.qota_rt = row.qota_rt)
            """,
            {"rows": rows},
        )
        total += len(rows)
        print(f"  edges {src_t}-[{rel_t}]->{tgt_t}: {len(rows)}")
    print(f"Merged {total} relationships.")


def verify(graph, data: dict) -> bool:
    """Check the Step 4 Definition of Done and return whether every invariant held.

    Reports counts *and* gates on them: compares what's in the graph against the
    source ``data`` (so silent node/edge loss from a MERGE collapse is caught),
    then asserts 0 isolated nodes and all 5 relation types present. Returns
    ``True`` iff every check passed; ``main`` turns a ``False`` into a non-zero
    exit so re-runs/CI can catch regressions instead of relying on the eye.
    """
    print("\n=== Verification ===")
    failures: list[str] = []

    # Loaded-vs-graph counts — catches silent loss (e.g. two source names
    # collapsing to one node, or a duplicate edge folding under MERGE).
    graph_nodes = graph.query(
        "MATCH (n) WHERE NOT n:Chunk RETURN count(n) AS n"
    )[0]["n"]
    graph_edges = graph.query(
        "MATCH ()-[r]->() WHERE type(r) <> 'FROM_FILING' RETURN count(r) AS n"
    )[0]["n"]
    src_nodes, src_edges = len(data["nodes"]), len(data["relationships"])
    print(f"Nodes:  source {src_nodes} -> graph {graph_nodes} (delta {graph_nodes - src_nodes})")
    print(f"Edges:  source {src_edges} -> graph {graph_edges} (delta {graph_edges - src_edges})")
    if graph_nodes != src_nodes:
        failures.append(f"node count mismatch: source {src_nodes} != graph {graph_nodes}")
    if graph_edges != src_edges:
        failures.append(f"edge count mismatch: source {src_edges} != graph {graph_edges}")

    print("Nodes by label:")
    for row in graph.query(
        "MATCH (n) WHERE NOT n:Chunk "
        "UNWIND labels(n) AS l RETURN l AS label, count(*) AS n "
        "ORDER BY n DESC"
    ):
        print(f"  {row['label']}: {row['n']}")

    print("Relationships by type:")
    rel_rows = graph.query(
        "MATCH ()-[r]->() WHERE type(r) <> 'FROM_FILING' "
        "RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC"
    )
    for row in rel_rows:
        print(f"  {row['rel']}: {row['n']}")
    missing = REL_TYPES - {row["rel"] for row in rel_rows}
    print(f"  all 5 relation types present: {not missing}"
          + (f" (missing {sorted(missing)})" if missing else ""))
    if missing:
        failures.append(f"missing relation types: {sorted(missing)}")

    isolated = graph.query(
        "MATCH (n) WHERE NOT n:Chunk AND NOT (n)--() RETURN count(n) AS n"
    )[0]["n"]
    print(f"Isolated nodes (expect 0): {isolated}")
    if isolated:
        failures.append(f"{isolated} isolated node(s)")

    hub = graph.query(
        "MATCH (n) WHERE NOT n:Chunk RETURN n.name AS name, labels(n)[0] AS label, "
        "count{ (n)--() } AS degree ORDER BY degree DESC LIMIT 1"
    )[0]
    print(f"Top-degree hub: {hub['name']} ({hub['label']}), degree {hub['degree']}")

    two_hop = graph.query(
        """
        MATCH p = (a:Company)-[:SUPPLIES]->(b:Company)-[:SUPPLIES]->(c:Company)
        WHERE a <> c
        RETURN a.name AS a, b.name AS b, c.name AS c LIMIT 3
        """
    )
    print(f"2-hop supply-chain paths (A->B->C) sample: {len(two_hop)} found")
    for row in two_hop:
        print(f"  {row['a']} -> {row['b']} -> {row['c']}")

    # Fallback multi-hop proof if SUPPLIES chains are sparse: any 2-hop path.
    if not two_hop:
        any_two = graph.query(
            "MATCH p = (a)-->(b)-->(c) WHERE a <> c RETURN count(p) AS n"
        )[0]["n"]
        print(f"  (no SUPPLIES chain; total 2-hop paths in graph: {any_two})")

    if failures:
        print("\nFAILED: " + "; ".join(failures))
    else:
        print("\nOK: all invariants hold.")
    return not failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 4: load extracted graph into Neo4j.")
    parser.add_argument("--reset", action="store_true",
                        help="delete all nodes/edges before loading")
    parser.add_argument("--verify-only", action="store_true",
                        help="skip loading; just verify the graph against graph_documents.json")
    args = parser.parse_args()

    graph = get_neo4j_graph()
    try:
        # Loaded either way: --verify-only compares the live graph against the file.
        data = load_graph_documents()

        if not args.verify_only:
            if args.reset:
                reset(graph)
            create_constraints(graph)
            ingest_nodes(graph, data["nodes"])
            ingest_relationships(graph, data["relationships"])

        if not verify(graph, data):
            raise SystemExit(1)
    finally:
        # Release the Neo4j driver's connection pool (the factory is reused by
        # long-running callers in Step 5/6, so don't leak connections).
        graph.close()


if __name__ == "__main__":
    main()
