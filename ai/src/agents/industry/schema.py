"""The fixed graph schema (CLAUDE.md): node labels and relationship types.

Single source of truth so extraction (Step 3), ingestion (Step 4), and the
Cypher retrieval chain (Step 5) all agree on the schema. Kept dependency-free on
purpose — importing it must not drag in the extraction stack (pandas, langchain,
the LLM/DART factories), so a DB-only script like ``ingest.py`` can import the
schema cheaply.

Do not add node/relationship types here without also updating CLAUDE.md and the
``SYSTEM_PROMPT`` in ``extract.py`` (see the schema section of CLAUDE.md).
"""

from __future__ import annotations

from typing import Literal, get_args

NodeType = Literal["Company", "Industry", "Product", "Policy", "Person"]
RelType = Literal["SUPPLIES", "COMPETES_WITH", "OWNS_STAKE", "BELONGS_TO", "BENEFITS_FROM"]

# Runtime allowlists derived from the Literal types above. Any label/rel-type
# interpolated into Cypher must be a member of these sets.
NODE_LABELS = frozenset(get_args(NodeType))
REL_TYPES = frozenset(get_args(RelType))

REL_SHAPES = frozenset(
    {
        ("Company", "SUPPLIES", "Company"),
        ("Company", "COMPETES_WITH", "Company"),
        ("Company", "OWNS_STAKE", "Company"),
        ("Company", "BELONGS_TO", "Industry"),
        ("Company", "BENEFITS_FROM", "Policy"),
    }
)


# Schema exposed to the Cypher-generation LLM. This intentionally excludes
# provenance/vector-storage implementation details such as :Chunk and
# :FROM_FILING, which may exist in the live Neo4j database after vectorization.
CYPHER_SCHEMA = """\
Node labels:
- Company(name)
- Industry(name)
- Product(name)
- Policy(name)
- Person(name)

Relationship types and directions:
- (:Company)-[:SUPPLIES {origins: list, evidences: list}]->(:Company)
- (:Company)-[:COMPETES_WITH {origins: list, evidences: list}]-(:Company)
- (:Company)-[:OWNS_STAKE {origins: list, evidences: list, qota_rt: float}]->(:Company)
- (:Company)-[:BELONGS_TO {origins: list, evidences: list}]->(:Industry)
- (:Company)-[:BENEFITS_FROM {origins: list, evidences: list}]->(:Policy)
"""
