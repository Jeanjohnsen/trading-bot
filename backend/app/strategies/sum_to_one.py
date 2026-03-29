from __future__ import annotations

from app.domain.models import MarketQuote, OpportunityCandidate, StrategyType


def direct_sum_to_one_opportunity(
    quote: MarketQuote,
    fee_rate: float,
    slippage_buffer: float,
    execution_risk_buffer: float,
) -> OpportunityCandidate | None:
    yes_entry = quote.yes_ask or quote.yes_price
    no_entry = quote.no_ask or quote.no_price
    if yes_entry <= 0 or no_entry <= 0:
        return None

    gross_arb = 1.0 - (yes_entry + no_entry)
    net_arb = gross_arb - fee_rate - slippage_buffer - execution_risk_buffer
    if net_arb <= 0:
        return None

    executable_size = max(1.0, min(quote.liquidity / 20.0 if quote.liquidity else 25.0, 250.0))
    capital_at_risk = (yes_entry + no_entry) * executable_size
    expected_profit = net_arb * executable_size
    fill_confidence = max(0.25, min(0.95, quote.liquidity_score + 0.2))

    return OpportunityCandidate(
        strategy_type=StrategyType.SUM_TO_ONE,
        market_id=quote.market_id,
        question=quote.question,
        category=quote.category,
        gross_edge=round(gross_arb, 6),
        net_edge=round(net_arb, 6),
        fill_adjusted_edge=round(expected_profit / max(capital_at_risk, 1e-6), 6),
        depth_weighted_edge=round(net_arb * fill_confidence, 6),
        expected_profit=round(expected_profit, 4),
        capital_at_risk=round(capital_at_risk, 4),
        executable_size=round(executable_size, 4),
        fill_confidence=round(fill_confidence, 4),
        liquidity_score=quote.liquidity_score,
        expected_holding_minutes=15.0,
        rationale="YES and NO asks sum to less than 1.00 after deterministic buffers.",
        evidence={
            "yes_entry": yes_entry,
            "no_entry": no_entry,
            "formula": "1 - (yes_entry + no_entry) - fees - slippage - execution_buffer",
        },
    )

