from __future__ import annotations

from app.domain.models import AppMode, ExecutionIntent, FillReport, OrderBookSnapshot, OrderReport


def _simulate_buy(limit_price: float, quantity: float, book: OrderBookSnapshot | None) -> tuple[float, list[tuple[float, float]]]:
    if not book:
        return 0.0, []
    remaining = quantity
    fills: list[tuple[float, float]] = []
    for level in book.asks:
        if level.price > limit_price or remaining <= 0:
            break
        take = min(level.size, remaining)
        fills.append((level.price, take))
        remaining -= take
    return quantity - remaining, fills


class PaperBroker:
    async def execute(self, intent: ExecutionIntent, books: dict[str, OrderBookSnapshot]) -> OrderReport:
        report = OrderReport(
            opportunity_id=intent.opportunity_id,
            market_id=intent.market_id,
            legs=intent.legs,
            mode=AppMode.PAPER,
            status="accepted",
            message="Paper order accepted.",
        )

        for leg in intent.legs:
            book = books.get(f"{intent.market_id}:{leg.outcome.lower()}")
            filled_quantity, fills = _simulate_buy(leg.price, leg.quantity, book)
            if filled_quantity <= 0:
                report.status = "partial" if report.fills else "rejected"
                report.message = f"No executable liquidity for {leg.outcome} within limit."
                continue
            for price, quantity in fills:
                report.fills.append(
                    FillReport(
                        order_id=report.order_id,
                        market_id=intent.market_id,
                        outcome=leg.outcome,
                        side=leg.side,
                        price=price,
                        quantity=quantity,
                    )
                )
            if filled_quantity < leg.quantity:
                report.status = "partial"
                report.message = "Partial fill; residual quantity remains exposed."

        if report.fills and report.status == "accepted":
            report.status = "filled"
            report.message = "All paper legs filled at or better than limit."
        return report

