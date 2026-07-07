from __future__ import annotations

from typing import Any

from ..core.state import FundamentalAgentState


def normalize_node(state: FundamentalAgentState) -> dict[str, Any]:
    """Compatibility node placeholder.

    The MVP collector already normalizes DART rows year-by-year so this node
    intentionally returns no state changes. Keeping it explicit documents the
    future split point for a richer GraphRAG/evidence-normalization layer.
    """

    return {}
