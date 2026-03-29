import asyncio

import httpx

from app.agents.claude_orchestrator import ClaudeOrchestrator
from app.agents.claude_client import ClaudeClient
from app.core.settings import Settings
from app.domain.models import OpportunityCandidate, RiskDecision, StrategyType


class ErrorResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(self.status_code, request=request, text=self.text)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    def json(self) -> dict:
        return {}


def test_claude_client_falls_back_on_http_400(monkeypatch) -> None:
    async def fake_post(self, url, headers=None, json=None):  # noqa: ARG001
        return ErrorResponse(400, '{"error":{"message":"Your credit balance is too low to access the Anthropic API."}}')

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    settings = Settings(ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="bad-model", ENABLE_CLAUDE_AGENT=True)
    client = ClaudeClient(settings)
    response = asyncio.run(client.complete("system", "user"))

    assert "deterministic local fallback" in response["text"].lower()
    assert response["error"]["status_code"] == 400
    assert client.connection_status()["state"] == "billing_blocked"


def test_claude_client_is_disabled_by_runtime_demo_mode() -> None:
    settings = Settings(ANTHROPIC_API_KEY="test-key", ENABLE_CLAUDE_AGENT=True)
    client = ClaudeClient(settings)
    client.set_runtime_access(
        allowed=False,
        state="disabled_demo_mode",
        message="Claude is disabled while demo/bootstrap market data is active.",
    )

    response = asyncio.run(client.complete("system", "user"))

    assert response["error"]["message"] == "Claude is disabled while demo/bootstrap market data is active."
    assert client.connection_status()["state"] == "disabled_demo_mode"


def test_claude_client_is_disabled_by_explicit_flag() -> None:
    settings = Settings(ANTHROPIC_API_KEY="test-key", ENABLE_CLAUDE_AGENT=False)
    client = ClaudeClient(settings)

    response = asyncio.run(client.complete("system", "user"))

    assert response["error"]["message"] == "Claude runtime toggle is off."
    assert client.connection_status()["state"] == "disabled_by_operator"


def test_execution_brief_falls_back_without_claude() -> None:
    settings = Settings(ANTHROPIC_API_KEY="test-key", ENABLE_CLAUDE_AGENT=False)
    orchestrator = ClaudeOrchestrator(ClaudeClient(settings))
    opportunity = OpportunityCandidate(
        strategy_type=StrategyType.SUM_TO_ONE,
        market_id="m1",
        question="Will test resolve yes?",
        category="finance",
        gross_edge=0.05,
        net_edge=0.03,
        fill_adjusted_edge=0.02,
        depth_weighted_edge=0.02,
        expected_profit=1.5,
        capital_at_risk=50.0,
        executable_size=50.0,
        fill_confidence=0.9,
        liquidity_score=0.8,
        expected_holding_minutes=5.0,
        rationale="Test rationale",
    )
    risk = RiskDecision(approved=True)
    risk.sizing.notional = 10.0
    risk.sizing.size_source = "auto"

    brief = asyncio.run(orchestrator.execution_brief(opportunity, risk, "paper"))

    assert "Deterministic execution brief" in brief


def test_daily_summary_falls_back_with_operating_context() -> None:
    settings = Settings(ANTHROPIC_API_KEY="test-key", ENABLE_CLAUDE_AGENT=False)
    orchestrator = ClaudeOrchestrator(ClaudeClient(settings))

    summary = asyncio.run(
        orchestrator.daily_summary(
            {
                "trade_count": 0,
                "approved_opportunities": 0,
                "blocked_opportunities": 245,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "mode": "paper",
                "using_demo_data": True,
                "kill_switch_active": True,
                "top_blockers": [("kill_switch", 245), ("stale_data", 245)],
            }
        )
    )

    assert "paper" in summary
    assert "demo data active" in summary
    assert "kill switch active" in summary
    assert "Top blockers" in summary
