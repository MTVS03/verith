from __future__ import annotations

from ..core.contract import Evidence

EVIDENCE_UNBOUND_FLAG = "EVIDENCE_UNBOUND_EXCLUDED"


def check_evidence_binding(evidence: list[Evidence]) -> tuple[list[Evidence], list[str]]:
    bound: list[Evidence] = []
    excluded = 0
    for item in evidence:
        if item.rcept_no and item.account_ids and item.source_url:
            bound.append(item)
        else:
            excluded += 1
    flags = [EVIDENCE_UNBOUND_FLAG] if excluded else []
    return bound, flags
