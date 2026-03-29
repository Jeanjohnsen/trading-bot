from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.settings import Settings
from app.data.normalization import normalize_event_payload
from app.domain.models import MarketQuote

logger = logging.getLogger(__name__)


class PolymarketMarketIngestion:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch_active_markets(self, max_markets: int = 80) -> list[MarketQuote]:
        url = f"{self.settings.polymarket_gamma_url}/events"
        params = {"limit": max_markets, "closed": "false"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload: Any = response.json()

        events = payload if isinstance(payload, list) else payload.get("data", [])
        quotes: list[MarketQuote] = []
        for event in events:
            quotes.extend(normalize_event_payload(event))

        logger.info("fetched polymarket events", extra={"event": "market_ingestion"})
        return quotes

