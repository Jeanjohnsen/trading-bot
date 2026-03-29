import asyncio

import httpx

from app.core.settings import Settings
from app.data.market_ingestion import PolymarketMarketIngestion
from app.domain.models import BankrollSource
from app.execution.polymarket_client import PolymarketClient


class MockResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("request failed", request=None, response=None)
        return None

    def json(self):
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
    assert quotes[0].related_group is None


def test_market_ingestion_filters_expired_and_closed_markets(monkeypatch) -> None:
    async def fake_get(self, url, params=None):  # noqa: ARG001
        return MockResponse(
            [
                {
                    "id": "event_1",
                    "slug": "fed-cuts",
                    "category": "macro",
                    "markets": [
                        {
                            "id": "expired_market",
                            "question": "Expired market",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[0.1, 0.9]",
                            "endDate": "2025-01-01T00:00:00Z",
                        },
                        {
                            "id": "closed_market",
                            "question": "Closed market",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[0.4, 0.6]",
                            "closed": True,
                            "endDate": "2026-05-01T00:00:00Z",
                        },
                        {
                            "id": "active_market",
                            "question": "Active market",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[0.52, 0.46]",
                            "groupItemTitle": "Rate path",
                            "endDate": "2026-05-01T00:00:00Z",
                        },
                    ],
                }
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    ingestion = PolymarketMarketIngestion(Settings())

    quotes = asyncio.run(ingestion.fetch_active_markets(max_markets=3))

    assert [quote.market_id for quote in quotes] == ["active_market"]
    assert quotes[0].related_group == "event_1:rate-path"


def test_market_ingestion_keeps_resolution_metadata_for_closed_fetch(monkeypatch) -> None:
    async def fake_get(self, url, params=None):  # noqa: ARG001
        return MockResponse(
            [
                {
                    "id": "event_1",
                    "slug": "btc-range",
                    "category": "crypto",
                    "closed": True,
                    "markets": [
                        {
                            "id": "resolved_market",
                            "question": "Did BTC close above 100k?",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[1.0, 0.0]",
                            "closed": True,
                            "resolved": True,
                            "endDate": "2026-03-01T00:00:00Z",
                        }
                    ],
                }
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    ingestion = PolymarketMarketIngestion(Settings())

    quotes = asyncio.run(ingestion.fetch_closed_markets(max_markets=1))

    assert len(quotes) == 1
    assert quotes[0].metadata["closed"] is True
    assert quotes[0].metadata["resolved_outcome"] == 1


def test_polymarket_client_fetches_venue_synced_account_snapshot(monkeypatch) -> None:
    wallet_address = "0x1111111111111111111111111111111111111111"
    proxy_wallet = "0x2222222222222222222222222222222222222222"

    async def fake_get(self, url, params=None):  # noqa: ARG001
        if url.endswith("/public-profile"):
            return MockResponse({"proxyWallet": proxy_wallet})
        if url.endswith("/value"):
            assert params == {"user": proxy_wallet}
            return MockResponse([{"user": proxy_wallet, "value": 7.5}])
        raise AssertionError(f"Unexpected GET url: {url}")

    async def fake_post(self, url, json=None):  # noqa: ARG001
        assert json["method"] == "eth_call"
        return MockResponse({"result": hex(20_000_000)})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    settings = Settings(_env_file=None, POLYMARKET_RELAYER_API_KEY_ADDRESS=wallet_address)
    client = PolymarketClient(settings)

    snapshot = asyncio.run(client.fetch_account_snapshot())

    assert snapshot.source is BankrollSource.VENUE_SYNCED
    assert snapshot.wallet_address == wallet_address
    assert snapshot.proxy_wallet == proxy_wallet
    assert snapshot.available_cash == 20.0
    assert snapshot.positions_value == 7.5
    assert snapshot.total_equity == 27.5
    assert snapshot.active_bankroll == 20.0
    assert snapshot.synced is True


def test_polymarket_client_returns_unavailable_snapshot_without_wallet_address() -> None:
    snapshot = asyncio.run(
        PolymarketClient(
            Settings(
                _env_file=None,
                POLYMARKET_WALLET_ADDRESS="",
                POLYMARKET_RELAYER_API_KEY_ADDRESS="",
            )
        ).fetch_account_snapshot()
    )

    assert snapshot.source is BankrollSource.VENUE_UNAVAILABLE
    assert snapshot.synced is False
    assert "POLYMARKET_WALLET_ADDRESS" in (snapshot.sync_error or "")


def test_polymarket_client_falls_back_across_polygon_rpcs(monkeypatch) -> None:
    wallet_address = "0x1111111111111111111111111111111111111111"
    rpc_attempts: list[str] = []

    async def fake_get(self, url, params=None):  # noqa: ARG001
        if url.endswith("/public-profile"):
            return MockResponse({})
        if url.endswith("/value"):
            return MockResponse([{"user": wallet_address, "value": 0.0}])
        raise AssertionError(f"Unexpected GET url: {url}")

    async def fake_post(self, url, json=None):  # noqa: ARG001
        rpc_attempts.append(url)
        if len(rpc_attempts) == 1:
            return MockResponse({"error": {"message": "Unauthorized"}}, status_code=401)
        return MockResponse({"result": hex(5_000_000)})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    settings = Settings(_env_file=None, POLYMARKET_RELAYER_API_KEY_ADDRESS=wallet_address, POLYGON_RPC_URL="https://polygon-rpc.com")
    snapshot = asyncio.run(PolymarketClient(settings).fetch_account_snapshot())

    assert snapshot.source is BankrollSource.VENUE_SYNCED
    assert snapshot.available_cash == 5.0
    assert rpc_attempts[0] == "https://polygon-rpc.com"
    assert len(rpc_attempts) >= 2
