from __future__ import annotations

from app.agents.claude_client import ClaudeClient
from app.domain.models import OpportunityCandidate, RiskDecision


class ClaudeOrchestrator:
    def __init__(self, client: ClaudeClient) -> None:
        self.client = client

    async def daily_summary(self, payload: dict) -> str:
        mode = payload.get("mode", "unknown")
        kill_switch_active = bool(payload.get("kill_switch_active", False))
        live_execution_enabled = bool(payload.get("live_execution_enabled", False))
        using_demo_data = bool(payload.get("using_demo_data", False))
        top_blockers = payload.get("top_blockers", [])

        top_blocker_text = ", ".join(f"{name} ({count})" for name, count in top_blockers[:3]) or "none recorded"
        operating_state = []
        if using_demo_data:
            operating_state.append("demo data active")
        if kill_switch_active:
            operating_state.append("kill switch active")
        if mode == "live" and not live_execution_enabled:
            operating_state.append("live mode selected but execution gate disabled")
        if mode in {"paper", "backtest"}:
            operating_state.append(f"{mode} mode")
        state_text = ", ".join(operating_state) if operating_state else "normal operation"

        if not self.client.enabled:
            return (
                f"Operator summary: mode {mode}, state {state_text}. "
                f"Trades {payload.get('trade_count', 0)}, approved {payload.get('approved_opportunities', 0)}, "
                f"blocked {payload.get('blocked_opportunities', 0)}, realized PnL {payload.get('realized_pnl', 0):.2f}, "
                f"unrealized PnL {payload.get('unrealized_pnl', 0):.2f}. "
                f"Top blockers: {top_blocker_text}."
            )
        system_prompt = (
            "You are Claude producing an operator summary for a prediction-market arbitrage system. "
            "Highlight trades, missed opportunities, PnL, fill quality, recurring issues, and next actions. "
            "Stay concise and operational. "
            "Important: do not describe zero fills as a critical incident if the payload shows paper mode, backtest mode, demo/bootstrap data, "
            "an active kill switch, or a disabled live execution gate. In those cases, frame the system as intentionally watch-only or safety-blocked. "
            "Only call it an execution incident when the payload indicates trading should have been live and unblocked."
        )
        response = await self.client.complete(system_prompt, f"payload={payload}")
        return response["text"]

    async def execution_brief(self, opportunity: OpportunityCandidate, risk: RiskDecision, mode: str) -> str:
        if not self.client.enabled:
            return (
                f"Deterministic execution brief: {opportunity.strategy_type.value} at {opportunity.net_edge:.2%} net edge, "
                f"size source {risk.sizing.size_source}, notional {risk.sizing.notional:.2f}, mode {mode}."
            )

        system_prompt = (
            "You are Claude assisting a deterministic arbitrage engine just before execution. "
            "Summarize why the trade is being taken, the sizing source, expected profit, and the main operational risk. "
            "Do not suggest bypassing hard risk rules or altering deterministic sizing."
        )
        user_prompt = (
            f"mode={mode}\n"
            f"opportunity={opportunity.model_dump_json(indent=2)}\n"
            f"risk={risk.model_dump_json(indent=2)}"
        )
        response = await self.client.complete(system_prompt, user_prompt)
        return response["text"]
