from __future__ import annotations

from .core.contract import FundamentalRequest, FundamentalResponse
from .nodes.workflow import build_fundamental_workflow


_WORKFLOW = build_fundamental_workflow()


async def analyze_fundamental(request: FundamentalRequest, *, use_cache: bool = True) -> FundamentalResponse:
    state = await _WORKFLOW.ainvoke({"request": request, "use_cache": use_cache})
    return state["response"]
