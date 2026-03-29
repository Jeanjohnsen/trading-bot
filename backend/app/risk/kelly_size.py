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
) -> ProposedSize:
    concentration_penalty = max(0.0, min(0.8, concentration_penalty))
    edge_scaled_fraction = max(0.0, opportunity.net_edge) * max(0.1, opportunity.fill_confidence) * 3.0
    raw_fraction = edge_scaled_fraction * fractional_kelly * (1.0 - concentration_penalty)
    capped_fraction = min(raw_fraction, max_position_fraction)
    notional = min(bankroll * capped_fraction, opportunity.capital_at_risk or bankroll * capped_fraction)
    units = 0.0 if opportunity.capital_at_risk <= 0 else notional / max(opportunity.capital_at_risk, 1e-6) * opportunity.executable_size
    return ProposedSize(
        bankroll_fraction=raw_fraction,
        notional=round(notional, 4),
        units=round(units, 4),
        kelly_fraction=round(raw_fraction, 6),
        capped_fraction=round(capped_fraction, 6),
    )

