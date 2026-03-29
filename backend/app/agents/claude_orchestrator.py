from __future__ import annotations

from app.agents.claude_client import ClaudeClient


class ClaudeOrchestrator:
    def __init__(self, client: ClaudeClient) -> None:
        self.client = client

    async def daily_summary(self, payload: dict) -> str:
        if not self.client.enabled:
            return (
                f"Daily summary: {payload.get('trade_count', 0)} trades, "
                f"realized PnL {payload.get('realized_pnl', 0):.2f}, "
                f"missed opportunities {payload.get('missed_opportunities', 0)}."
            )
        system_prompt = (
            "You are Claude producing an operator summary for a prediction-market arbitrage system. "
            "Highlight trades, missed opportunities, PnL, fill quality, recurring issues, and next actions. "
            "Stay concise and operational."
        )
        response = await self.client.complete(system_prompt, f"payload={payload}")
        return response["text"]
