from __future__ import annotations

from app.domain.models import PositionSummary


def realized_pnl(positions: list[PositionSummary]) -> float:
    return round(sum(position.realized_pnl for position in positions), 4)


def unrealized_pnl(positions: list[PositionSummary]) -> float:
    return round(sum(position.unrealized_pnl for position in positions), 4)


def bankroll_after_pnl(bankroll: float, positions: list[PositionSummary]) -> float:
    return bankroll + realized_pnl(positions) + unrealized_pnl(positions)

