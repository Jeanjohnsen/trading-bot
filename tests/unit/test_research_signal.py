from datetime import UTC, datetime, timedelta

from app.domain.models import AppMode, MarketQuote, OrderBookSnapshot, OpportunityCandidate, PriceLevel, StrategyType
from app.execution.intent_builder import build_execution_intent
from app.risk.validate_risk import RiskEngine, RiskState
from app.services.scanner import ScannerService


def sample_runtime_config(research_enabled: bool = True) -> dict:
    return {
        "app": {"enable_research_mode": research_enabled},
        "scanner": {"stale_data_timeout_seconds": 20},
        "risk": {
            "min_net_edge": 0.01,
            "max_concurrent_positions": 15,
            "max_drawdown_fraction": 0.08,
            "daily_loss_limit_fraction": 0.03,
            "total_exposure_fraction": 0.40,
            "slippage_tolerance": 0.01,
            "min_liquidity_score": 0.30,
            "api_budget_daily_usd": 12.0,
            "max_position_bankroll_fraction": 0.05,
            "fractional_kelly": 0.25,
            "execution_risk_buffer": 0.005,
            "fee_rate": 0.0,
            "latency_buffer": 0.002,
            "estimated_claude_cost_per_trade_usd": 0.0,
        },
    }


def bullish_quote() -> MarketQuote:
    return MarketQuote(
        market_id="research_market",
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


def fresh_books(market_id: str) -> dict[str, OrderBookSnapshot]:
    return {
        f"{market_id}:yes": OrderBookSnapshot(
            market_id=market_id,
            token_id="yes-token",
            outcome="yes",
            asks=[PriceLevel(price=0.41, size=100)],
        ),
        f"{market_id}:no": OrderBookSnapshot(
            market_id=market_id,
            token_id="no-token",
            outcome="no",
            asks=[PriceLevel(price=0.62, size=100)],
        ),
    }


def test_scanner_creates_research_signal_opportunity_when_research_mode_is_enabled() -> None:
    config = sample_runtime_config(research_enabled=True)
    scanner = ScannerService(config)
    engine = RiskEngine(config, live_enabled=False, kill_switch_active=False)

    opportunities = scanner.scan(
        quotes=[bullish_quote()],
        books=fresh_books("research_market"),
        mode=AppMode.PAPER,
        risk_state=RiskState(bankroll=10_000),
        risk_engine=engine,
    )

    research_signal = next((item for item in opportunities if item.strategy_type is StrategyType.RESEARCH_SIGNAL), None)

    assert research_signal is not None
    assert research_signal.risk is not None
    assert research_signal.risk.approved is True
    assert research_signal.evidence["direction"] == "yes"


def test_build_execution_intent_uses_single_directional_leg_for_research_signal() -> None:
    quote = bullish_quote()
    opportunity = OpportunityCandidate(
        strategy_type=StrategyType.RESEARCH_SIGNAL,
        market_id=quote.market_id,
        question=quote.question,
        category=quote.category,
        gross_edge=0.06,
        net_edge=0.05,
        fill_adjusted_edge=0.04,
        depth_weighted_edge=0.04,
        expected_profit=5.0,
        capital_at_risk=41.0,
        executable_size=100.0,
        fill_confidence=0.8,
        liquidity_score=0.8,
        expected_holding_minutes=90.0,
        rationale="Research forecast expects YES to outperform the current market price.",
        evidence={"direction": "yes"},
    )

    intent = build_execution_intent(
        opportunity=opportunity,
        quote=quote,
        mode=AppMode.PAPER,
        notes="directional research trade",
        target_notional=20.5,
    )

    assert len(intent.legs) == 1
    assert intent.legs[0].outcome == "yes"
    assert intent.legs[0].side == "buy"
    assert intent.legs[0].price == 0.41
    assert intent.legs[0].quantity == 50.0
