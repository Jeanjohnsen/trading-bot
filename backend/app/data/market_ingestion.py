from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.settings import Settings
from app.data.normalization import normalize_event_payload
from app.domain.models import MarketQuote

logger = logging.getLogger(__name__)


class PolymarketMarketIngestion:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _fetch_event_quotes(self, max_markets: int, closed: bool) -> list[MarketQuote]:
        url = f"{self.settings.polymarket_gamma_url}/events"
        params = {"limit": max_markets, "closed": "true" if closed else "false"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload: Any = response.json()

        events = payload if isinstance(payload, list) else payload.get("data", [])
        if closed:
            quotes: list[MarketQuote] = []
            for event in events:
                quotes.extend(normalize_event_payload(event))
            return quotes

        scanner_cfg = self.settings.merged_runtime_config().get("scanner", {})
        min_minutes_to_expiry = float(scanner_cfg.get("min_minutes_to_expiry", 30))
        max_days_to_expiry = float(scanner_cfg.get("max_days_to_expiry", 120))
        max_minutes_to_expiry = max_days_to_expiry * 24 * 60
        now = datetime.now(UTC)
        quotes: list[MarketQuote] = []
        for event in events:
            for quote in normalize_event_payload(event):
                if quote.metadata.get("closed") or quote.metadata.get("active") is False:
                    continue
                if quote.expiry:
                    if quote.expiry <= now:
                        continue
                    minutes_to_expiry = quote.minutes_to_expiry
                    if minutes_to_expiry is not None and minutes_to_expiry < min_minutes_to_expiry:
                        continue
                    if minutes_to_expiry is not None and minutes_to_expiry > max_minutes_to_expiry:
                        continue
                quotes.append(quote)

        return quotes

    async def fetch_active_markets(self, max_markets: int = 80) -> list[MarketQuote]:
        quotes = await self._fetch_event_quotes(max_markets=max_markets, closed=False)
        logger.info("fetched polymarket events", extra={"event": "market_ingestion"})
        return quotes

    async def fetch_closed_markets(self, max_markets: int = 200) -> list[MarketQuote]:
        quotes = await self._fetch_event_quotes(max_markets=max_markets, closed=True)
        logger.info("fetched closed polymarket events", extra={"event": "market_ingestion_closed"})
        return quotes
