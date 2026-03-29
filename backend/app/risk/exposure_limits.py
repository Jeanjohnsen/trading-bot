from __future__ import annotations

from app.domain.models import PositionSummary


def current_total_exposure(positions: list[PositionSummary]) -> float:
    return sum(position.entry_cost for position in positions if position.state != "closed")


def exposure_by_category(positions: list[PositionSummary]) -> dict[str, float]:
    buckets: dict[str, float] = {}
    for position in positions:
        buckets[position.category] = buckets.get(position.category, 0.0) + position.entry_cost
    return buckets

