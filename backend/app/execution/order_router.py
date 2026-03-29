from __future__ import annotations

from app.domain.models import AppMode, ExecutionIntent, OrderBookSnapshot, OrderReport
from app.execution.paper_broker import PaperBroker
from app.execution.polymarket_client import PolymarketClient


class OrderRouter:
    def __init__(self, paper_broker: PaperBroker, polymarket_client: PolymarketClient) -> None:
        self.paper_broker = paper_broker
        self.polymarket_client = polymarket_client

    async def route(self, intent: ExecutionIntent, books: dict[str, OrderBookSnapshot]) -> OrderReport:
        if intent.mode is AppMode.PAPER:
            return await self.paper_broker.execute(intent, books)
        if intent.mode is AppMode.LIVE:
            return await self.polymarket_client.post_limit_order(intent)
        return await self.paper_broker.execute(intent, books)
