from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

import httpx

from app.core.settings import Settings
from app.data.market_ingestion import PolymarketMarketIngestion
from app.data.orderbook_ingestion import PolymarketOrderbookIngestion
from app.domain.models import AccountSnapshot, BankrollSource, ExecutionIntent, OrderReport


USDC_E_CONTRACT_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_E_DECIMALS = 6
ERC20_BALANCE_OF_SELECTOR = "70a08231"
POLYGON_RPC_FALLBACKS = (
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.llamarpc.com",
    "https://rpc.ankr.com/polygon",
)

logger = logging.getLogger(__name__)


def _balance_of_call_data(address: str) -> str:
    normalized = address.lower().replace("0x", "")
    return f"0x{ERC20_BALANCE_OF_SELECTOR}{normalized.rjust(64, '0')}"


class PolymarketClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.market_ingestion = PolymarketMarketIngestion(settings)
        self.orderbook_ingestion = PolymarketOrderbookIngestion(settings)
        self.live_trading_enabled = bool(settings.enable_live_trading)
        self.market_orders_enabled = bool(settings.enable_market_orders)

    def set_live_trading_enabled(self, enabled: bool) -> None:
        self.live_trading_enabled = bool(enabled)

    def set_market_orders_enabled(self, enabled: bool) -> None:
        self.market_orders_enabled = bool(enabled)

    async def fetch_markets(self, max_markets: int) -> list:
        return await self.market_ingestion.fetch_active_markets(max_markets=max_markets)

    async def fetch_closed_markets(self, max_markets: int) -> list:
        return await self.market_ingestion.fetch_closed_markets(max_markets=max_markets)

    async def fetch_orderbooks(self, quotes: list) -> dict:
        return await self.orderbook_ingestion.fetch_for_quotes(quotes)

    async def fetch_account_snapshot(self) -> AccountSnapshot:
        wallet_address = self.settings.polymarket_wallet_address or self.settings.polymarket_relayer_api_key_address
        if not wallet_address:
            return AccountSnapshot(
                source=BankrollSource.VENUE_UNAVAILABLE,
                label="Venue unavailable",
                active_bankroll=0.0,
                total_equity=0.0,
                synced=False,
                sync_error="Missing POLYMARKET_WALLET_ADDRESS or POLYMARKET_RELAYER_API_KEY_ADDRESS.",
            )

        proxy_wallet = self.settings.polymarket_proxy_wallet or wallet_address
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                profile = await self._fetch_public_profile(client, wallet_address)
                proxy_wallet = self.settings.polymarket_proxy_wallet or profile.get("proxyWallet") or wallet_address
                positions_value = await self._fetch_positions_value(client, proxy_wallet)
                available_cash = await self._fetch_usdc_balance(client, proxy_wallet)

            total_equity = available_cash + positions_value
            return AccountSnapshot(
                source=BankrollSource.VENUE_SYNCED,
                label="Venue-synced",
                wallet_address=wallet_address,
                proxy_wallet=proxy_wallet,
                available_cash=round(available_cash, 4),
                positions_value=round(positions_value, 4),
                total_equity=round(total_equity, 4),
                active_bankroll=round(available_cash, 4),
                synced=True,
                last_synced_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.warning(
                "polymarket account sync failed",
                extra={"event": "polymarket_account_sync_failed", "error_message": str(exc), "wallet_address": wallet_address},
            )
            return AccountSnapshot(
                source=BankrollSource.VENUE_UNAVAILABLE,
                label="Venue unavailable",
                wallet_address=wallet_address,
                proxy_wallet=proxy_wallet,
                active_bankroll=0.0,
                total_equity=0.0,
                synced=False,
                last_synced_at=datetime.now(UTC),
                sync_error=str(exc),
            )

    async def _fetch_public_profile(self, client: httpx.AsyncClient, address: str) -> dict[str, Any]:
        response = await client.get(f"{self.settings.polymarket_gamma_url}/public-profile", params={"address": address})
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload: Any = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _fetch_positions_value(self, client: httpx.AsyncClient, address: str) -> float:
        response = await client.get(f"{self.settings.polymarket_data_url}/value", params={"user": address})
        response.raise_for_status()
        payload: Any = response.json()
        if isinstance(payload, list) and payload:
            value = payload[0].get("value", 0.0)
            return float(value or 0.0)
        if isinstance(payload, dict):
            return float(payload.get("value", 0.0) or 0.0)
        return 0.0

    async def _fetch_usdc_balance(self, client: httpx.AsyncClient, address: str) -> float:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": USDC_E_CONTRACT_ADDRESS,
                    "data": _balance_of_call_data(address),
                },
                "latest",
            ],
        }
        attempted_urls: list[str] = []
        rpc_urls = [self.settings.polygon_rpc_url, *POLYGON_RPC_FALLBACKS]

        for rpc_url in dict.fromkeys(url for url in rpc_urls if url):
            attempted_urls.append(rpc_url)
            try:
                response = await client.post(rpc_url, json=payload)
                response.raise_for_status()
                body: Any = response.json()
                if isinstance(body, dict) and body.get("error"):
                    message = body["error"].get("message", "Polygon RPC eth_call failed.")
                    raise RuntimeError(message)
                raw_value = body.get("result", "0x0") if isinstance(body, dict) else "0x0"
                return int(raw_value, 16) / (10**USDC_E_DECIMALS)
            except Exception as exc:
                logger.info(
                    "polygon rpc balance lookup failed",
                    extra={"event": "polygon_rpc_balance_failed", "rpc_url": rpc_url, "error_message": str(exc)},
                )

        attempted = ", ".join(attempted_urls)
        raise RuntimeError(
            "Could not read Polygon USDC.e balance from configured/public RPC endpoints. "
            f"Tried: {attempted}. "
            "Set POLYGON_RPC_URL to a working Polygon RPC if needed."
        )

    async def post_limit_order(self, intent: ExecutionIntent) -> OrderReport:
        if not self.live_trading_enabled:
            raise RuntimeError("Live trading is disabled. Use paper broker or explicitly enable live mode.")
        if not self.settings.polymarket_relayer_api_key:
            raise RuntimeError("Missing Polymarket relayer credentials.")
        raise NotImplementedError("Live order posting is intentionally gated until wallet signing is validated.")
