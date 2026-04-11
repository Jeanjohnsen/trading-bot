from __future__ import annotations

from app.domain.models import AppMode, ExecutionIntent, MarketQuote, OpportunityCandidate, OrderLeg, StrategyType


def _bounded_quantity(target_notional: float, entry_price: float, executable_size: float) -> float:
    return max(1.0, min(executable_size, target_notional / max(entry_price, 1e-6)))


def build_execution_intent(
    opportunity: OpportunityCandidate,
    quote: MarketQuote,
    mode: AppMode,
    notes: str,
    target_notional: float,
) -> ExecutionIntent:
    if opportunity.strategy_type is StrategyType.RESEARCH_SIGNAL:
        direction = str(opportunity.evidence.get("direction", "yes")).lower()
        if direction == "no":
            entry_price = quote.no_ask or quote.no_price
            token_id = quote.no_token_id
        else:
            direction = "yes"
            entry_price = quote.yes_ask or quote.yes_price
            token_id = quote.yes_token_id

        if mode is AppMode.LIVE:
            quantity = max(1.0, target_notional / max(entry_price, 1e-6))
        else:
            quantity = _bounded_quantity(target_notional, entry_price, opportunity.executable_size)
        legs = [
            OrderLeg(
                outcome=direction,
                side="buy",
                price=entry_price,
                quantity=quantity,
                token_id=token_id,
            )
        ]
    else:
        unit_cost = (quote.yes_ask or quote.yes_price) + (quote.no_ask or quote.no_price)
        quantity = _bounded_quantity(target_notional, unit_cost, opportunity.executable_size)
        legs = [
            OrderLeg(outcome="yes", side="buy", price=quote.yes_ask or quote.yes_price, quantity=quantity, token_id=quote.yes_token_id),
            OrderLeg(outcome="no", side="buy", price=quote.no_ask or quote.no_price, quantity=quantity, token_id=quote.no_token_id),
        ]

    return ExecutionIntent(
        opportunity_id=opportunity.opportunity_id,
        market_id=opportunity.market_id,
        mode=mode,
        legs=legs,
        notes=notes,
    )
