from __future__ import annotations

from app.domain.models import MarketQuote, OpportunityCandidate, StrategyType


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def research_signal_metrics(quote: MarketQuote) -> dict[str, float | str]:
    market_probability = _clamp(float(quote.yes_price), 0.01, 0.99)
    momentum_adjustment = _clamp(float(quote.recent_move or 0.0) * 0.15, -0.08, 0.08)
    liquidity_adjustment = (quote.liquidity_score - 0.5) * 0.04
    forecast_probability = _clamp(market_probability + momentum_adjustment + liquidity_adjustment, 0.01, 0.99)
    confidence = _clamp(0.35 + (quote.liquidity_score * 0.45), 0.35, 0.9)
    edge = forecast_probability - market_probability
    direction = "yes" if edge >= 0 else "no"
    return {
        "market_probability": round(market_probability, 6),
        "forecast_probability": round(forecast_probability, 6),
        "confidence": round(confidence, 6),
        "edge": round(edge, 6),
        "direction": direction,
    }


def research_signal_opportunity(
    quote: MarketQuote,
    fee_rate: float,
    slippage_buffer: float,
    execution_risk_buffer: float,
    min_signal_edge: float,
) -> OpportunityCandidate | None:
    metrics = research_signal_metrics(quote)
    raw_edge = abs(float(metrics["edge"]))
    net_edge = raw_edge - fee_rate - slippage_buffer - execution_risk_buffer
    if net_edge <= 0 or raw_edge < min_signal_edge:
        return None

    direction = str(metrics["direction"])
    entry_price = (quote.yes_ask or quote.yes_price) if direction == "yes" else (quote.no_ask or quote.no_price)
    if entry_price <= 0:
        return None

    executable_size = max(1.0, min(quote.liquidity / 40.0 if quote.liquidity else 15.0, 100.0))
    capital_at_risk = entry_price * executable_size
    expected_profit = net_edge * executable_size
    fill_confidence = _clamp((float(metrics["confidence"]) + quote.liquidity_score) / 2.0, 0.35, 0.95)

    return OpportunityCandidate(
        strategy_type=StrategyType.RESEARCH_SIGNAL,
        market_id=quote.market_id,
        question=quote.question,
        category=quote.category,
        gross_edge=round(raw_edge, 6),
        net_edge=round(net_edge, 6),
        fill_adjusted_edge=round(expected_profit / max(capital_at_risk, 1e-6), 6),
        depth_weighted_edge=round(net_edge * fill_confidence, 6),
        expected_profit=round(expected_profit, 4),
        capital_at_risk=round(capital_at_risk, 4),
        executable_size=round(executable_size, 4),
        fill_confidence=round(fill_confidence, 4),
        liquidity_score=quote.liquidity_score,
        expected_holding_minutes=90.0,
        rationale="Research forecast diverges from the current market-implied probability after deterministic buffers.",
        evidence={
            "direction": direction,
            "forecast_probability": metrics["forecast_probability"],
            "market_probability": metrics["market_probability"],
            "raw_edge": round(raw_edge, 6),
            "confidence": metrics["confidence"],
            "entry_price": round(entry_price, 6),
            "source": "deterministic_research_v1",
        },
    )
