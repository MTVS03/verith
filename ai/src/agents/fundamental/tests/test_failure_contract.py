import pytest

from src.agents.fundamental.core.contract import FundamentalRequest
from src.agents.fundamental.graph import analyze_fundamental


@pytest.mark.asyncio
async def test_unsupported_ticker_returns_insufficient_data_response() -> None:
    response = await analyze_fundamental(
        FundamentalRequest(
            request_id="req-unsupported",
            trace_id="trace-unsupported",
            ticker="000000",
        )
    )

    assert response.verdict_label == "insufficient_data"
    assert response.score == 0
    assert response.confidence == 0.3
    assert "UNSUPPORTED_TICKER" in response.risk_flags
    assert response.meta["workflow"] == ["collect", "report"]
