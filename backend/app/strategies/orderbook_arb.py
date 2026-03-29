from __future__ import annotations

from collections.abc import Iterable

from app.domain.models import MarketQuote, OpportunityCandidate, OrderBookSnapshot, StrategyType


def _depth_cost(levels: Iterable, target_size: float) -> tuple[float, float]:
    remaining = target_size
    spent = 0.0
    filled = 0.0
    for level in levels:
        if remaining <= 0:
            break
        take = min(level.size, remaining)
        spent += take * level.price
        filled += take
        remaining -= take
    return spent, filled


def orderbook_micro_arb(
    quote: MarketQuote,
    yes_book: OrderBookSnapshot | None,
    no_book: OrderBookSnapshot | None,
    fee_rate: float,
    slippage_buffer: float,
    execution_risk_buffer: float,
) -> OpportunityCandidate | None:
    if not yes_book or not no_book or not yes_book.asks or not no_book.asks:
        return None

    max_size = min(sum(level.size for level in yes_book.asks), sum(level.size for level in no_book.asks), 100.0)
    if max_size <= 0:
        return None

    target_size = min(max_size, 25.0)
    yes_cost, yes_filled = _depth_cost(yes_book.asks, target_size)
    no_cost, no_filled = _depth_cost(no_book.asks, target_size)
    fillable_size = min(yes_filled, no_filled)
    if fillable_size <= 0:
        return None

    total_cost = yes_cost + no_cost
    gross_edge = ((1.0 * fillable_size) - total_cost) / max(fillable_size, 1e-6)
    net_edge = gross_edge - fee_rate - slippage_buffer - execution_risk_buffer
    if net_edge <= 0:
        return None

    top_of_book = 1.0 - ((yes_book.best_ask or 0.0) + (no_book.best_ask or 0.0))
    depth_weighted_edge = ((fillable_size - total_cost) / max(total_cost, 1e-6)) - fee_rate - slippage_buffer
    fill_confidence = max(0.35, min(0.98, fillable_size / max(target_size, 1e-6)))

    return OpportunityCandidate(
        strategy_type=StrategyType.ORDERBOOK_ARB,
        market_id=quote.market_id,
        question=quote.question,
        category=quote.category,
        gross_edge=round(gross_edge, 6),
        net_edge=round(net_edge, 6),
        fill_adjusted_edge=round((net_edge * fillable_size) / max(total_cost, 1e-6), 6),
        depth_weighted_edge=round(depth_weighted_edge, 6),
        expected_profit=round(net_edge * fillable_size, 4),
        capital_at_risk=round(total_cost, 4),
        executable_size=round(fillable_size, 4),
        fill_confidence=round(fill_confidence, 4),
        liquidity_score=quote.liquidity_score,
        expected_holding_minutes=5.0,
        rationale="Depth-weighted YES and NO ask stacks remain profitable after execution buffers.",
        evidence={
            "top_of_book_edge": round(top_of_book, 6),
            "depth_weighted_edge": round(depth_weighted_edge, 6),
            "fillable_size": round(fillable_size, 4),
        },
    )

