from __future__ import annotations

from collections import defaultdict

from app.domain.models import MarketQuote, OpportunityCandidate, StrategyType


def cross_market_opportunities(quotes: list[MarketQuote], buffer: float) -> list[OpportunityCandidate]:
    grouped: dict[str, list[MarketQuote]] = defaultdict(list)
    for quote in quotes:
        if quote.related_group and quote.metadata.get("cross_market_eligible"):
            grouped[quote.related_group].append(quote)

    opportunities: list[OpportunityCandidate] = []
    for group_key, members in grouped.items():
        if len(members) < 2:
            continue
        event_ids = {member.event_id for member in members if member.event_id}
        if not event_ids:
            continue
        if len(event_ids) > 1:
            continue
        if not all(member.metadata.get("cross_market_eligible") for member in members):
            continue
        expiries = [member.expiry for member in members if member.expiry is not None]
        if len(expiries) >= 2:
            expiry_span_minutes = (max(expiries) - min(expiries)).total_seconds() / 60
            if expiry_span_minutes > 24 * 60:
                continue
        if not any(member.metadata.get("neg_risk") for member in members) and len(members) < 3:
            continue

        summed = sum(member.yes_price for member in members)
        gross_edge = 1.0 - summed
        net_edge = gross_edge - buffer
        if net_edge <= 0:
            continue

        average_liquidity = sum(member.liquidity_score for member in members) / len(members)
        executable_size = max(1.0, min(sum(member.liquidity for member in members) / 200.0, 100.0))
        capital_at_risk = summed * executable_size
        expected_profit = net_edge * executable_size
        joined_questions = " | ".join(member.question for member in members[:3])

        opportunities.append(
            OpportunityCandidate(
                strategy_type=StrategyType.CROSS_MARKET_ARB,
                market_id=members[0].market_id,
                related_market_ids=[member.market_id for member in members[1:]],
                question=f"Cross-market inconsistency: {joined_questions}",
                category=members[0].category,
                gross_edge=round(gross_edge, 6),
                net_edge=round(net_edge, 6),
                fill_adjusted_edge=round(expected_profit / max(capital_at_risk, 1e-6), 6),
                depth_weighted_edge=round(net_edge * average_liquidity, 6),
                expected_profit=round(expected_profit, 4),
                capital_at_risk=round(capital_at_risk, 4),
                executable_size=round(executable_size, 4),
                fill_confidence=round(max(0.3, min(0.9, average_liquidity)), 4),
                liquidity_score=round(average_liquidity, 4),
                expected_holding_minutes=45.0,
                rationale="Related markets imply broken probability mass across a grouped event tree.",
                evidence={
                    "group": group_key,
                    "summed_yes_probability": round(summed, 6),
                    "member_count": len(members),
                    "event_id_count": len(event_ids),
                    "expiry_span_minutes": round((max(expiries) - min(expiries)).total_seconds() / 60, 4) if len(expiries) >= 2 else 0.0,
                },
            )
        )
    return opportunities
