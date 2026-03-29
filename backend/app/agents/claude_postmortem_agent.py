from __future__ import annotations

from app.agents.claude_client import ClaudeClient
from app.domain.models import OrderReport


class ClaudePostmortemAgent:
    def __init__(self, client: ClaudeClient) -> None:
        self.client = client

    async def review(self, order_report: OrderReport, classification: str) -> str:
        if not self.client.enabled:
            return f"Post-trade classification: {classification}. Review generated locally because Claude is not configured."

        system_prompt = (
            "You are Claude writing a concise post-trade review for an arbitrage trading system. "
            "Classify what happened, what likely caused it, and what deterministic mitigation should be tested next. "
            "Do not recommend bypassing hard risk controls."
        )
        user_prompt = (
            f"classification={classification}\n"
            f"order_report={order_report.model_dump_json(indent=2)}"
        )
        response = await self.client.complete(system_prompt, user_prompt)
        return response["text"]

