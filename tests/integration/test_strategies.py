import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.models import AppMode, ExecutionIntent, MarketQuote, OrderBookSnapshot, OrderLeg, PriceLevel
from app.execution.paper_broker import PaperBroker
from app.risk.validate_risk import RiskEngine, RiskState
from app.strategies.orderbook_arb import orderbook_micro_arb
from app.strategies.cross_market_arb import cross_market_opportunities
from app.strategies.sum_to_one import direct_sum_to_one_opportunity


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def quote_from_payload(payload: dict) -> MarketQuote:
    quote = payload["quote"]
    return MarketQuote(
        market_id=quote["market_id"],
        question=quote["question"],
        category=quote["category"],
        yes_price=quote["yes_price"],
        no_price=quote["no_price"],
        yes_ask=quote.get("yes_ask"),
        no_ask=quote.get("no_ask"),
        liquidity=quote["liquidity"],
        volume_24h=quote["volume_24h"],
        last_updated=datetime.now(UTC),
    )


def test_profitable_sum_to_one_fixture_is_detected() -> None:
    quote = quote_from_payload(load_fixture("profitable_sum_to_one.json"))
    opportunity = direct_sum_to_one_opportunity(quote, fee_rate=0.0, slippage_buffer=0.005, execution_risk_buffer=0.004)
    assert opportunity is not None
    assert opportunity.net_edge > 0


def test_fake_top_of_book_is_rejected_after_depth_analysis() -> None:
    payload = load_fixture("fake_top_of_book.json")
    quote = quote_from_payload(payload)
    yes_book = OrderBookSnapshot(
        market_id=quote.market_id,
        token_id="yes",
        outcome="yes",
        asks=[PriceLevel(**level) for level in payload["yes_book"]["asks"]],
    )
    no_book = OrderBookSnapshot(
        market_id=quote.market_id,
        token_id="no",
        outcome="no",
        asks=[PriceLevel(**level) for level in payload["no_book"]["asks"]],
    )
    opportunity = orderbook_micro_arb(quote, yes_book, no_book, fee_rate=0.0, slippage_buffer=0.01, execution_risk_buffer=0.01)
    assert opportunity is None


def test_partial_fill_scenario_is_reported() -> None:
    payload = load_fixture("partial_fill.json")
    books = {
        f"{payload['market_id']}:yes": OrderBookSnapshot(
            market_id=payload["market_id"],
            token_id="yes",
            outcome="yes",
            asks=[PriceLevel(**level) for level in payload["yes_book"]["asks"]],
        ),
        f"{payload['market_id']}:no": OrderBookSnapshot(
            market_id=payload["market_id"],
            token_id="no",
            outcome="no",
            asks=[PriceLevel(**level) for level in payload["no_book"]["asks"]],
        ),
    }
    broker = PaperBroker()
    report = asyncio.run(
        broker.execute(
            ExecutionIntent(
                opportunity_id="opp_partial",
                market_id=payload["market_id"],
                mode=AppMode.PAPER,
                legs=[
                    OrderLeg(outcome="yes", side="buy", price=0.47, quantity=10),
                    OrderLeg(outcome="no", side="buy", price=0.48, quantity=10),
                ],
            ),
            books,
        )
    )
    assert report.status == "partial"
    assert len(report.fills) > 0


def test_cross_market_requires_single_event_coherent_group() -> None:
    now = datetime.now(UTC)
    quotes = [
        MarketQuote(
            market_id="m1",
            event_id="event_1",
            question="Will BTC close above 100k by year end?",
            category="crypto",
            related_group="event_1:event-tree",
            expiry=now + timedelta(days=30),
            yes_price=0.2,
            no_price=0.8,
            metadata={"cross_market_eligible": True, "neg_risk": True},
        ),
        MarketQuote(
            market_id="m2",
            event_id="event_2",
            question="Will ETH ETF launch by year end?",
            category="crypto",
            related_group="event_1:event-tree",
            expiry=now + timedelta(days=30),
            yes_price=0.2,
            no_price=0.8,
            metadata={"cross_market_eligible": True, "neg_risk": True},
        ),
    ]

    opportunities = cross_market_opportunities(quotes, buffer=0.01)

    assert opportunities == []
