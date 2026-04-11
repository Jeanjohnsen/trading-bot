from __future__ import annotations

from app.domain.models import OpportunityCandidate, ProposedSize


def kelly_fraction(probability: float, payout_multiple: float) -> float:
    if payout_multiple <= 0:
        return 0.0
    q = 1 - probability
    raw = ((payout_multiple * probability) - q) / payout_multiple
    return max(0.0, raw)


def size_arbitrage_position(
    opportunity: OpportunityCandidate,
    bankroll: float,
    max_position_fraction: float,
    fractional_kelly: float,
    concentration_penalty: float = 0.0,
    operator_fraction_override: float | None = None,
    size_source: str = "auto",
    estimated_ai_cost: float = 0.0,
    minimum_notional: float = 0.0,
) -> ProposedSize:
    concentration_penalty = max(0.0, min(0.8, concentration_penalty))
    edge_scaled_fraction = max(0.0, opportunity.net_edge) * max(0.1, opportunity.fill_confidence) * 3.0
    raw_fraction = edge_scaled_fraction * fractional_kelly * (1.0 - concentration_penalty)
    requested_fraction = max(0.0, operator_fraction_override) if operator_fraction_override is not None else raw_fraction
    capped_fraction = min(requested_fraction, max_position_fraction)
    bankroll_cap_notional = bankroll * max_position_fraction
    modeled_capacity_notional = opportunity.capital_at_risk or bankroll_cap_notional
    max_notional = min(bankroll_cap_notional, modeled_capacity_notional)
    notional = min(bankroll * capped_fraction, opportunity.capital_at_risk or bankroll * capped_fraction)
    minimum_notional = max(0.0, minimum_notional)
    raised_to_minimum = False

    if minimum_notional > 0 and bankroll_cap_notional + 1e-9 >= minimum_notional:
        max_notional = max(max_notional, minimum_notional)

    if minimum_notional > 0 and max_notional > 0 and 0 < notional < minimum_notional:
        target_notional = min(minimum_notional, max_notional)
        if target_notional > notional:
            notional = target_notional
            capped_fraction = notional / max(bankroll, 1e-6) if bankroll > 0 else 0.0
            raised_to_minimum = abs(notional - minimum_notional) < 1e-9

    units = 0.0 if opportunity.capital_at_risk <= 0 else notional / max(opportunity.capital_at_risk, 1e-6) * opportunity.executable_size
    estimated_profit = (
        opportunity.expected_profit * (notional / max(opportunity.capital_at_risk, 1e-6))
        if opportunity.capital_at_risk > 0
        else notional * max(0.0, opportunity.net_edge)
    )
    return ProposedSize(
        bankroll_fraction=raw_fraction,
        requested_fraction=round(requested_fraction, 6),
        notional=round(notional, 4),
        units=round(units, 4),
        kelly_fraction=round(raw_fraction, 6),
        capped_fraction=round(capped_fraction, 6),
        size_source=size_source,
        estimated_profit=round(estimated_profit, 4),
        estimated_ai_cost=round(estimated_ai_cost, 4),
        estimated_profit_after_ai_cost=round(estimated_profit - estimated_ai_cost, 4),
        minimum_notional=round(minimum_notional, 4),
        max_notional=round(max_notional, 4),
        meets_minimum_notional=minimum_notional <= 0 or notional + 1e-9 >= minimum_notional,
        raised_to_minimum=raised_to_minimum,
    )
