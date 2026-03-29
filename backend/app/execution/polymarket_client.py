from __future__ import annotations

from app.core.settings import Settings
from app.data.market_ingestion import PolymarketMarketIngestion
from app.data.orderbook_ingestion import PolymarketOrderbookIngestion
from app.domain.models import ExecutionIntent, OrderReport


class PolymarketClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.market_ingestion = PolymarketMarketIngestion(settings)
        self.orderbook_ingestion = PolymarketOrderbookIngestion(settings)

    async def fetch_markets(self, max_markets: int) -> list:
        return await self.market_ingestion.fetch_active_markets(max_markets=max_markets)

    async def fetch_orderbooks(self, quotes: list) -> dict:
        return await self.orderbook_ingestion.fetch_for_quotes(quotes)

    async def post_limit_order(self, intent: ExecutionIntent) -> OrderReport:
        if not self.settings.enable_live_trading:
            raise RuntimeError("Live trading is disabled. Use paper broker or explicitly enable live mode.")
        if not self.settings.polymarket_relayer_api_key:
            raise RuntimeError("Missing Polymarket relayer credentials.")
        raise NotImplementedError("Live order posting is intentionally gated until wallet signing is validated.")

