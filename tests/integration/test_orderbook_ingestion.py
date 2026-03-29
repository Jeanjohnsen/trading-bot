import asyncio

import httpx

from app.core.settings import Settings
from app.data.orderbook_ingestion import PolymarketOrderbookIngestion
from app.domain.models import MarketQuote


class Mock404Response:
    status_code = 404

    def raise_for_status(self) -> None:
        request = httpx.Request("GET", "https://clob.polymarket.com/book")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    def json(self) -> dict:
        return {}


def test_orderbook_ingestion_skips_missing_books(monkeypatch) -> None:
    async def fake_get(self, url, params=None):  # noqa: ARG001
        return Mock404Response()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    ingestion = PolymarketOrderbookIngestion(Settings())
    quotes = [
        MarketQuote(
            market_id="m1",
            question="Test market",
            category="finance",
            yes_price=0.47,
            no_price=0.48,
            yes_token_id="yes_token",
            no_token_id="no_token",
        )
    ]

    books = asyncio.run(ingestion.fetch_for_quotes(quotes))
    assert books == {}
