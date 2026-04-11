import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.settings import Settings
from app.domain.models import (
    AppMode,
    MarketQuote,
    OpportunityCandidate,
    OrderBookSnapshot,
    OrderReport,
    OpportunityStatus,
    PriceLevel,
    ProposedSize,
    RiskDecision,
    StrategyType,
)
from app.services.runtime import TradingRuntime


class FakeRepository:
    def __init__(self, order_rows: list[dict] | None = None) -> None:
        self.order_rows = order_rows or []

    def save_agent_note(self, note) -> None:  # noqa: ANN001
        return None

    def save_order_report(self, report) -> None:  # noqa: ANN001
        return None

    def save_failure(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def save_position(self, position) -> None:  # noqa: ANN001
        return None

    def save_market_snapshots(self, quotes) -> None:  # noqa: ANN001
        return None

    def list_orders(self, limit: int = 100) -> list[dict]:
        return self.order_rows[:limit]


def sample_quote() -> MarketQuote:
    return MarketQuote(
        market_id="live_market",
        question="Will inflation be above 3% next month?",
        category="macro",
        expiry=datetime.now(UTC) + timedelta(days=7),
        yes_token_id="yes-token",
        no_token_id="no-token",
        yes_price=0.40,
        no_price=0.60,
        yes_ask=0.41,
        no_ask=0.62,
        liquidity=10_000,
        volume_24h=50_000,
        recent_move=0.25,
        last_updated=datetime.now(UTC),
    )


def approved_opportunity(strategy_type: StrategyType) -> OpportunityCandidate:
    evidence = {"direction": "yes"} if strategy_type is StrategyType.RESEARCH_SIGNAL else {}
    return OpportunityCandidate(
        strategy_type=strategy_type,
        market_id="live_market",
        question="Will inflation be above 3% next month?",
        category="macro",
        gross_edge=0.05,
        net_edge=0.04,
        fill_adjusted_edge=0.03,
        depth_weighted_edge=0.03,
        expected_profit=2.0,
        capital_at_risk=10.0,
        executable_size=5.0,
        fill_confidence=0.8,
        liquidity_score=0.9,
        expected_holding_minutes=60.0,
        rationale="Test opportunity.",
        status=OpportunityStatus.APPROVED,
        evidence=evidence,
        risk=RiskDecision(
            approved=True,
            reasons=["approved"],
            blocked_by=[],
            sizing=ProposedSize(notional=2.05, units=5.0),
        ),
    )


def test_live_runtime_rejects_non_research_signal_execution(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        APP_MODE="live",
        ENABLE_LIVE_TRADING=True,
        ENABLE_CLAUDE_AGENT=False,
    )
    runtime = TradingRuntime(settings=settings, repository=FakeRepository())
    runtime.current_mode = AppMode.LIVE
    runtime.quotes = [sample_quote()]
    runtime.books = {
        "live_market:yes": OrderBookSnapshot(
            market_id="live_market",
            token_id="yes-token",
            outcome="yes",
            asks=[PriceLevel(price=0.41, size=50.0)],
        )
    }
    runtime.opportunities = [approved_opportunity(StrategyType.SUM_TO_ONE)]

    async def fake_execution_brief(**kwargs):  # noqa: ANN003
        return "brief"

    async def fake_route(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Live route should not run for non-research strategies.")

    monkeypatch.setattr(runtime.claude_orchestrator, "execution_brief", fake_execution_brief)
    monkeypatch.setattr(runtime.order_router, "route", fake_route)

    with pytest.raises(ValueError, match="research_signal"):
        asyncio.run(runtime.execute_opportunity(runtime.opportunities[0].opportunity_id))


def test_live_runtime_executes_research_signal_when_route_succeeds(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        APP_MODE="live",
        ENABLE_LIVE_TRADING=True,
        ENABLE_CLAUDE_AGENT=False,
    )
    runtime = TradingRuntime(settings=settings, repository=FakeRepository())
    runtime.current_mode = AppMode.LIVE
    runtime.quotes = [sample_quote()]
    runtime.opportunities = [approved_opportunity(StrategyType.RESEARCH_SIGNAL)]

    async def fake_execution_brief(**kwargs):  # noqa: ANN003
        return "brief"

    async def fake_route(intent, books):  # noqa: ANN001
        assert intent.mode is AppMode.LIVE
        assert len(intent.legs) == 1
        assert intent.legs[0].token_id == "yes-token"
        return OrderReport(
            order_id="live-order-1",
            opportunity_id=intent.opportunity_id,
            market_id=intent.market_id,
            legs=intent.legs,
            mode=AppMode.LIVE,
            status="accepted",
            message="Live order accepted.",
        )

    async def fake_review(report, classification):  # noqa: ANN001
        return f"{classification}:{report.status}"

    async def fake_dispatch(message):  # noqa: ANN001
        return None

    monkeypatch.setattr(runtime.claude_orchestrator, "execution_brief", fake_execution_brief)
    monkeypatch.setattr(runtime.order_router, "route", fake_route)
    monkeypatch.setattr(runtime.claude_postmortem, "review", fake_review)
    monkeypatch.setattr(runtime.notifications, "dispatch", fake_dispatch)

    report = asyncio.run(runtime.execute_opportunity(runtime.opportunities[0].opportunity_id))

    assert report.mode is AppMode.LIVE
    assert report.order_id == "live-order-1"
    assert report.status == "accepted"


def test_scan_once_triggers_auto_execute_hook(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        APP_MODE="live",
        ENABLE_LIVE_TRADING=True,
        ENABLE_RESEARCH_MODE=True,
        ENABLE_CLAUDE_AGENT=False,
    )
    runtime = TradingRuntime(settings=settings, repository=FakeRepository())

    async def fake_load_market_data():
        return [], {}

    async def fake_account_snapshot():
        return runtime.venue_account

    async def fake_noop() -> None:
        return None

    auto_execute_calls: list[str] = []

    async def fake_auto_execute() -> None:
        auto_execute_calls.append("called")

    monkeypatch.setattr(runtime, "_load_market_data", fake_load_market_data)
    monkeypatch.setattr(runtime.polymarket_client, "fetch_account_snapshot", fake_account_snapshot)
    monkeypatch.setattr(runtime, "_sync_forecast_records", fake_noop)
    monkeypatch.setattr(runtime, "_refresh_agent_notes", fake_noop)
    monkeypatch.setattr(runtime, "_rescore_opportunities", lambda: None)
    monkeypatch.setattr(runtime, "_maybe_auto_execute", fake_auto_execute)

    asyncio.run(runtime.scan_once())

    assert auto_execute_calls == ["called"]


def test_live_runtime_auto_executes_first_approved_research_signal(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        APP_MODE="live",
        ENABLE_LIVE_TRADING=True,
        ENABLE_RESEARCH_MODE=True,
        ENABLE_CLAUDE_AGENT=False,
    )
    runtime = TradingRuntime(settings=settings, repository=FakeRepository())
    runtime.current_mode = AppMode.LIVE
    runtime.live_trading_enabled = True
    runtime.research_mode_enabled = True
    runtime.auto_execute_enabled = True
    runtime.runtime_config.setdefault("app", {})
    runtime.runtime_config["app"]["enable_auto_execute"] = True
    runtime.venue_account.active_bankroll = 25.0
    runtime.venue_account.total_equity = 25.0
    runtime.venue_account.synced = True
    runtime.opportunities = [
        approved_opportunity(StrategyType.SUM_TO_ONE),
        approved_opportunity(StrategyType.RESEARCH_SIGNAL),
    ]

    executed_ids: list[str] = []

    async def fake_execute(opportunity_id: str) -> OrderReport:
        executed_ids.append(opportunity_id)
        return OrderReport(
            order_id="auto-order-1",
            opportunity_id=opportunity_id,
            market_id="live_market",
            legs=[],
            mode=AppMode.LIVE,
            status="accepted",
            message="Auto execution accepted.",
        )

    monkeypatch.setattr(runtime, "execute_opportunity", fake_execute)

    asyncio.run(runtime._maybe_auto_execute())

    assert executed_ids == [runtime.opportunities[1].opportunity_id]


def test_live_runtime_auto_execute_skips_market_with_recent_live_order(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        APP_MODE="live",
        ENABLE_LIVE_TRADING=True,
        ENABLE_RESEARCH_MODE=True,
        ENABLE_CLAUDE_AGENT=False,
    )
    repository = FakeRepository(
        order_rows=[
            {
                "order_id": "recent-live-order",
                "market_id": "live_market",
                "opportunity_id": "opp_old",
                "mode": "live",
                "status": "matched",
                "message": "Already traded.",
                "created_at": datetime.now(UTC),
            }
        ]
    )
    runtime = TradingRuntime(settings=settings, repository=repository)
    runtime.current_mode = AppMode.LIVE
    runtime.live_trading_enabled = True
    runtime.research_mode_enabled = True
    runtime.auto_execute_enabled = True
    runtime.runtime_config.setdefault("app", {})
    runtime.runtime_config["app"]["enable_auto_execute"] = True
    runtime.venue_account.active_bankroll = 25.0
    runtime.venue_account.total_equity = 25.0
    runtime.venue_account.synced = True
    runtime.opportunities = [approved_opportunity(StrategyType.RESEARCH_SIGNAL)]

    async def fake_execute(opportunity_id: str) -> OrderReport:  # noqa: ARG001
        raise AssertionError("Auto execution should skip markets with a recent live order.")

    monkeypatch.setattr(runtime, "execute_opportunity", fake_execute)

    asyncio.run(runtime._maybe_auto_execute())
