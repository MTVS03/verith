from __future__ import annotations

from .core.contract import FundamentalAgentInput, FundamentalRequest, FundamentalResponse
from .core.query_interpreter import to_fundamental_request
from .nodes.workflow import build_fundamental_workflow


_WORKFLOW = build_fundamental_workflow()


async def analyze_fundamental(request: FundamentalRequest, *, use_cache: bool = True) -> FundamentalResponse:
    state = await _WORKFLOW.ainvoke({"request": request, "use_cache": use_cache})
    return state["response"]


async def analyze_fundamental_public(
    public_input: FundamentalAgentInput,
    *,
    use_cache: bool = True,
) -> FundamentalResponse:
    request, interpretation = to_fundamental_request(public_input)
    state = await _WORKFLOW.ainvoke(
        {
            "request": request,
            "use_cache": use_cache,
            "input_interpretation": interpretation.model_dump(),
        }
    )
    return state["response"]
