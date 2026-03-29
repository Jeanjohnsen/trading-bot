from datetime import UTC, datetime, timedelta

from app.domain.models import AppMode, MarketQuote, OpportunityCandidate, StrategyType
from app.risk.validate_risk import RiskEngine, RiskState


def sample_runtime_config() -> dict:
    return {
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
        },
    }


def sample_quote() -> MarketQuote:
    return MarketQuote(
        market_id="m1",
        question="Test market",
        category="finance",
        yes_price=0.47,
        no_price=0.48,
        yes_ask=0.47,
        no_ask=0.48,
        liquidity=5000,
        volume_24h=12000,
        last_updated=datetime.now(UTC),
    )


def sample_opportunity() -> OpportunityCandidate:
    return OpportunityCandidate(
        strategy_type=StrategyType.SUM_TO_ONE,
        market_id="m1",
        question="Test market",
        category="finance",
        gross_edge=0.05,
        net_edge=0.03,
        fill_adjusted_edge=0.03,
        depth_weighted_edge=0.02,
        expected_profit=3.0,
        capital_at_risk=95.0,
        executable_size=100.0,
        fill_confidence=0.8,
        liquidity_score=0.8,
        expected_holding_minutes=5,
        rationale="Test",
    )


def test_kill_switch_blocks_trade() -> None:
    engine = RiskEngine(sample_runtime_config(), live_enabled=False, kill_switch_active=True)
    decision = engine.evaluate(sample_opportunity(), sample_quote(), RiskState(), AppMode.PAPER, data_age_seconds=1, estimated_slippage=0.005)
    assert not decision.approved
    assert "kill_switch" in decision.blocked_by


def test_stale_data_blocks_trade() -> None:
    engine = RiskEngine(sample_runtime_config(), live_enabled=False, kill_switch_active=False)
    decision = engine.evaluate(sample_opportunity(), sample_quote(), RiskState(), AppMode.PAPER, data_age_seconds=120, estimated_slippage=0.005)
    assert not decision.approved
    assert "stale_data" in decision.blocked_by


def test_slippage_blocks_trade() -> None:
    engine = RiskEngine(sample_runtime_config(), live_enabled=False, kill_switch_active=False)
    decision = engine.evaluate(sample_opportunity(), sample_quote(), RiskState(), AppMode.PAPER, data_age_seconds=1, estimated_slippage=0.02)
    assert not decision.approved
    assert "slippage" in decision.blocked_by

