from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

import httpx

from app.core.settings import Settings
from app.data.market_ingestion import PolymarketMarketIngestion
from app.data.orderbook_ingestion import PolymarketOrderbookIngestion
from app.domain.models import AccountSnapshot, AppMode, BankrollSource, ExecutionIntent, OrderBookSnapshot, OrderReport


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


def _price_precision(tick_size: float) -> int:
    text = f"{tick_size:.10f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".", maxsplit=1)[1])


def _round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return price
    precision = _price_precision(tick_size)
    scaled = round(price / tick_size)
    return round(scaled * tick_size, precision)


class PolymarketClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.market_ingestion = PolymarketMarketIngestion(settings)
        self.orderbook_ingestion = PolymarketOrderbookIngestion(settings)
        self.live_trading_enabled = bool(settings.enable_live_trading)
        self.market_orders_enabled = bool(settings.enable_market_orders)
        self._resolved_proxy_wallet = settings.polymarket_proxy_wallet or None
        self._clob_client_components: tuple[Any, Any, Any, Any] | None = None
        self._authenticated_clob_client: Any | None = None

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
                self._resolved_proxy_wallet = proxy_wallet
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

    def _load_clob_client_components(self) -> tuple[Any, Any, Any, Any]:
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
        except ImportError as exc:
            raise RuntimeError(
                "py-clob-client is not installed. Install the official Polymarket Python client to enable live posting."
            ) from exc
        return ClobClient, OrderArgs, OrderType, BUY

    def _get_funder_address(self) -> str:
        funder = (
            self.settings.polymarket_proxy_wallet
            or self._resolved_proxy_wallet
            or self.settings.polymarket_wallet_address
            or self.settings.polymarket_relayer_api_key_address
        )
        if not funder:
            raise RuntimeError(
                "Missing Polymarket funder wallet. Set POLYMARKET_PROXY_WALLET, "
                "POLYMARKET_WALLET_ADDRESS, or POLYMARKET_RELAYER_API_KEY_ADDRESS."
            )
        return funder

    def _create_authenticated_clob_client(self) -> Any:
        if self._authenticated_clob_client is not None:
            return self._authenticated_clob_client

        if not self.settings.polymarket_private_key:
            raise RuntimeError("Missing POLYMARKET_PRIVATE_KEY for live Polymarket posting.")

        funder = self._get_funder_address()
        ClobClient, OrderArgs, OrderType, BUY = self._load_clob_client_components()
        self._clob_client_components = (ClobClient, OrderArgs, OrderType, BUY)

        client = ClobClient(
            self.settings.polymarket_clob_url,
            key=self.settings.polymarket_private_key,
            chain_id=137,
            signature_type=1,
            funder=funder,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        self._authenticated_clob_client = client
        return client

    @staticmethod
    def _normalize_live_response_payload(response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            dumped = response.model_dump()
            if isinstance(dumped, dict):
                return dumped
        if hasattr(response, "dict"):
            dumped = response.dict()
            if isinstance(dumped, dict):
                return dumped
        if hasattr(response, "__dict__"):
            dumped = dict(response.__dict__)
            if isinstance(dumped, dict):
                return dumped
        return {}

    def _normalize_live_order_report(self, intent: ExecutionIntent, response: Any) -> OrderReport:
        payload = self._normalize_live_response_payload(response)
        status = str(payload.get("status") or "accepted").lower()
        message = str(
            payload.get("message")
            or payload.get("errorMsg")
            or payload.get("error")
            or f"Live order {status}."
        )
        report = OrderReport(
            opportunity_id=intent.opportunity_id,
            market_id=intent.market_id,
            legs=intent.legs,
            mode=AppMode.LIVE,
            status=status,
            message=message,
        )
        order_id = payload.get("orderID") or payload.get("orderId") or payload.get("id")
        if order_id:
            report.order_id = str(order_id)
        return report

    async def post_limit_order(self, intent: ExecutionIntent, books: dict[str, OrderBookSnapshot] | None = None) -> OrderReport:
        if not self.live_trading_enabled:
            raise RuntimeError("Live trading is disabled. Use paper broker or explicitly enable live mode.")
        if not self.settings.polymarket_relayer_api_key:
            raise RuntimeError("Missing Polymarket relayer credentials.")
        if not self.settings.polymarket_private_key:
            raise RuntimeError("Missing POLYMARKET_PRIVATE_KEY for live Polymarket posting.")
        if len(intent.legs) != 1:
            raise RuntimeError("Live Polymarket posting currently supports only single-leg research_signal orders.")

        leg = intent.legs[0]
        if not leg.token_id:
            raise RuntimeError("Live Polymarket orders require a token_id.")
        if leg.side.lower() != "buy":
            raise RuntimeError("Live Polymarket posting currently supports only BUY orders.")
        if leg.price <= 0 or leg.quantity <= 0:
            raise RuntimeError("Live Polymarket orders require positive price and quantity.")

        outcome_key = leg.outcome.lower()
        book = (books or {}).get(f"{intent.market_id}:{outcome_key}")
        tick_size = book.tick_size if book else 0.01
        price = _round_to_tick(float(leg.price), tick_size)

        clob_client = self._create_authenticated_clob_client()
        if self._clob_client_components is None:
            self._clob_client_components = self._load_clob_client_components()
        _, OrderArgs, OrderType, BUY = self._clob_client_components

        order_args = OrderArgs(
            token_id=leg.token_id,
            price=price,
            size=float(leg.quantity),
            side=BUY,
        )
        signed_order = clob_client.create_order(order_args)
        response = clob_client.post_order(signed_order, OrderType.GTC)
        return self._normalize_live_order_report(intent, response)
