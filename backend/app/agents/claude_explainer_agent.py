from __future__ import annotations

import json

from app.agents.claude_client import ClaudeClient
from app.domain.models import OpportunityCandidate, RiskDecision


class ClaudeExplainerAgent:
    def __init__(self, client: ClaudeClient) -> None:
        self.client = client

    async def explain(self, opportunity: OpportunityCandidate, risk: RiskDecision) -> str:
        if not self.client.enabled:
            if risk.approved:
                return f"{opportunity.strategy_type.value} edge detected with net edge {opportunity.net_edge:.2%}; deterministic risk approved."
            return f"{opportunity.strategy_type.value} edge detected but blocked due to: {', '.join(risk.blocked_by)}."

        system_prompt = (
            "You are Claude, the interpretation layer for a deterministic prediction-market arbitrage engine. "
            "Explain structural opportunities clearly, but never suggest bypassing risk controls, kill switches, or live-mode locks. "
            "If evidence is weak, say so plainly."
        )
        user_prompt = (
            "Summarize this opportunity in plain English.\n\n"
            f"opportunity={opportunity.model_dump_json(indent=2)}\n"
            f"risk={risk.model_dump_json(indent=2)}"
        )
        response = await self.client.complete(system_prompt, user_prompt)
        return response["text"] or json.dumps({"fallback": "empty Claude response"})

