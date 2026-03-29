import asyncio

import httpx

from app.core.settings import Settings
from app.data.market_ingestion import PolymarketMarketIngestion


class MockResponse:
    def __init__(self, payload: list[dict]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict]:
        return self._payload


def test_market_ingestion_normalizes_polymarket_events(monkeypatch) -> None:
    async def fake_get(self, url, params=None):  # noqa: ARG001
        return MockResponse(
            [
                {
                    "id": "event_1",
                    "category": "crypto",
                    "markets": [
                        {
                            "id": "market_1",
                            "question": "Will BTC be above 100k?",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[0.52, 0.46]",
                            "clobTokenIds": "[\"yes_token\", \"no_token\"]"
                        }
                    ],
                }
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    settings = Settings()
    ingestion = PolymarketMarketIngestion(settings)
    quotes = asyncio.run(ingestion.fetch_active_markets(max_markets=1))
    assert len(quotes) == 1
    assert quotes[0].yes_token_id == "yes_token"
    assert quotes[0].no_price == 0.46

