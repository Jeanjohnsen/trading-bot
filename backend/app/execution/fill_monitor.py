from __future__ import annotations

from app.domain.models import OrderReport


def classify_fill_outcome(report: OrderReport) -> str:
    if report.status == "filled":
        return "correct_arb_capture"
    if report.status == "partial":
        return "leg_risk"
    return "missed_fill"

