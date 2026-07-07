import pytest

from src.agents.fundamental.core.observability import NodeExecutionError, run_traced_node


@pytest.mark.asyncio
async def test_run_traced_node_records_success() -> None:
    async def node(state):
        return {"value": state["value"] + 1}

    result = await run_traced_node("calculate", node, {"value": 1})

    assert result["value"] == 2
    assert result["node_trace"][0]["name"] == "calculate"
    assert result["node_trace"][0]["status"] == "ok"
    assert result["node_trace"][0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_run_traced_node_records_error_trace() -> None:
    def node(_state):
        raise ValueError("boom")

    with pytest.raises(NodeExecutionError) as exc_info:
        await run_traced_node("collect", node, {})

    assert exc_info.value.trace[0]["name"] == "collect"
    assert exc_info.value.trace[0]["status"] == "error"
    assert exc_info.value.trace[0]["error_type"] == "ValueError"
