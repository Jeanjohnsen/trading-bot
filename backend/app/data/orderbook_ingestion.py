from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import logging
from typing import Any

import httpx

from app.core.settings import Settings
from app.domain.models import MarketQuote, OrderBookSnapshot, PriceLevel

logger = logging.getLogger(__name__)


def _parse_levels(levels: list[dict[str, Any]] | None) -> list[PriceLevel]:
    parsed: list[PriceLevel] = []
    for level in levels or []:
        try:
            parsed.append(PriceLevel(price=float(level["price"]), size=float(level["size"])))
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


class PolymarketOrderbookIngestion:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _empty_snapshot(token_id: str, market_id: str, outcome: str) -> OrderBookSnapshot:
        return OrderBookSnapshot(
            market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            timestamp=datetime.now(UTC),
            bids=[],
            asks=[],
            stale=True,
        )

    async def fetch_orderbook(self, token_id: str, market_id: str, outcome: str) -> OrderBookSnapshot:
        url = f"{self.settings.polymarket_clob_url}/book"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params={"token_id": token_id})
            if response.status_code == 404:
                logger.info("missing orderbook for token", extra={"event": "orderbook_missing", "token_id": token_id, "market_id": market_id})
                return self._empty_snapshot(token_id=token_id, market_id=market_id, outcome=outcome)
            response.raise_for_status()
            payload = response.json()
        timestamp = payload.get("timestamp")
        try:
            parsed_timestamp = datetime.fromtimestamp(int(timestamp), tz=UTC)
        except (TypeError, ValueError):
            parsed_timestamp = datetime.now(UTC)
        return OrderBookSnapshot(
            market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            timestamp=parsed_timestamp,
            bids=_parse_levels(payload.get("bids")),
            asks=_parse_levels(payload.get("asks")),
            tick_size=float(payload.get("tick_size") or 0.01),
            min_order_size=float(payload.get("min_order_size") or 1.0),
            last_trade_price=float(payload.get("last_trade_price")) if payload.get("last_trade_price") else None,
        )

    async def fetch_for_quotes(self, quotes: Iterable[MarketQuote]) -> dict[str, OrderBookSnapshot]:
        books: dict[str, OrderBookSnapshot] = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for quote in quotes:
                for outcome, token_id in (("yes", quote.yes_token_id), ("no", quote.no_token_id)):
                    if not token_id:
                        continue
                    response = await client.get(f"{self.settings.polymarket_clob_url}/book", params={"token_id": token_id})
                    if response.status_code == 404:
                        logger.info(
                            "missing orderbook for token",
                            extra={"event": "orderbook_missing", "token_id": token_id, "market_id": quote.market_id},
                        )
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    books[f"{quote.market_id}:{outcome}"] = OrderBookSnapshot(
                        market_id=quote.market_id,
                        token_id=token_id,
                        outcome=outcome,
                        timestamp=datetime.now(UTC),
                        bids=_parse_levels(payload.get("bids")),
                        asks=_parse_levels(payload.get("asks")),
                        tick_size=float(payload.get("tick_size") or 0.01),
                        min_order_size=float(payload.get("min_order_size") or 1.0),
                        last_trade_price=float(payload.get("last_trade_price")) if payload.get("last_trade_price") else None,
                    )
        return books
