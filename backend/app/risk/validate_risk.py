from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import BankrollSource, AppMode, MarketQuote, OpportunityCandidate, PositionSummary, ProposedSize, RiskDecision
from app.risk.exposure_limits import current_total_exposure, exposure_by_category
from app.risk.kelly_size import size_arbitrage_position


@dataclass
class RiskState:
    bankroll: float = 10_000.0
    bankroll_source: BankrollSource = BankrollSource.SIMULATED
    venue_sync_ok: bool = True
    realized_pnl_today: float = 0.0
    drawdown_fraction: float = 0.0
    open_positions: list[PositionSummary] = field(default_factory=list)
    external_position_value: float = 0.0
    api_spend_today: float = 0.0
    active_executions: int = 0


class RiskEngine:
    def __init__(self, runtime_config: dict, live_enabled: bool, kill_switch_active: bool, claude_enabled: bool = False) -> None:
        self.runtime_config = runtime_config
        self.live_enabled = live_enabled
        self.kill_switch_active = kill_switch_active
        self.claude_enabled = claude_enabled

    def evaluate(
        self,
        opportunity: OpportunityCandidate,
        quote: MarketQuote,
        state: RiskState,
        mode: AppMode,
        data_age_seconds: float,
        estimated_slippage: float,
        operator_fraction_override: float | None = None,
        size_source: str = "auto",
    ) -> RiskDecision:
        risk_cfg = self.runtime_config.get("risk", {})
        reasons: list[str] = []
        blocked_by: list[str] = []

        min_net_edge = float(risk_cfg.get("min_net_edge", 0.015))
        max_positions = int(risk_cfg.get("max_concurrent_positions", 15))
        max_drawdown = float(risk_cfg.get("max_drawdown_fraction", 0.08))
        daily_loss_limit = float(risk_cfg.get("daily_loss_limit_fraction", 0.03))
        total_exposure_limit = float(risk_cfg.get("total_exposure_fraction", 0.40)) * state.bankroll
        slippage_tolerance = float(risk_cfg.get("slippage_tolerance", 0.01))
        min_liquidity_score = float(risk_cfg.get("min_liquidity_score", 0.35))
        api_budget = float(risk_cfg.get("api_budget_daily_usd", 12.0))
        stale_timeout = float(self.runtime_config.get("scanner", {}).get("stale_data_timeout_seconds", 20))
        max_position_fraction = float(risk_cfg.get("max_position_bankroll_fraction", 0.05))
        fractional_kelly = float(risk_cfg.get("fractional_kelly", 0.25))
        estimated_ai_cost = float(risk_cfg.get("estimated_claude_cost_per_trade_usd", 0.0)) if self.claude_enabled else 0.0

        if self.kill_switch_active:
            blocked_by.append("kill_switch")
            reasons.append("Global kill switch is active.")
        if mode is AppMode.LIVE and not self.live_enabled:
            blocked_by.append("live_mode_lock")
            reasons.append("Live trading is disabled in configuration.")
        if mode is AppMode.LIVE and not state.venue_sync_ok:
            blocked_by.append("venue_balance_sync")
            reasons.append("Live bankroll could not be synced from Polymarket.")
        if opportunity.net_edge < min_net_edge:
            blocked_by.append("edge_threshold")
            reasons.append(f"Net edge {opportunity.net_edge:.4f} is below threshold {min_net_edge:.4f}.")
        if len(state.open_positions) >= max_positions:
            blocked_by.append("concurrency_limit")
            reasons.append("Maximum concurrent positions reached.")
        if state.drawdown_fraction >= max_drawdown:
            blocked_by.append("drawdown_limit")
            reasons.append("Max drawdown exceeded.")
        if abs(min(state.realized_pnl_today, 0.0)) >= state.bankroll * daily_loss_limit:
            blocked_by.append("daily_loss_limit")
            reasons.append("Daily loss limit breached.")
        if opportunity.liquidity_score < min_liquidity_score:
            blocked_by.append("liquidity")
            reasons.append("Liquidity score below minimum.")
        if estimated_slippage > slippage_tolerance:
            blocked_by.append("slippage")
            reasons.append("Estimated slippage exceeds tolerance.")
        if data_age_seconds > stale_timeout:
            blocked_by.append("stale_data")
            reasons.append("Orderbook snapshot is stale.")
        if state.api_spend_today >= api_budget:
            blocked_by.append("api_budget")
            reasons.append("AI/API budget exhausted for today.")

        new_total_exposure = current_total_exposure(state.open_positions) + state.external_position_value + opportunity.capital_at_risk
        if new_total_exposure > total_exposure_limit:
            blocked_by.append("exposure_limit")
            reasons.append("Trade would breach total exposure cap.")

        category_exposure = exposure_by_category(state.open_positions)
        concentration_penalty = category_exposure.get(quote.category, 0.0) / max(state.bankroll, 1.0)
        sizing = size_arbitrage_position(
            opportunity=opportunity,
            bankroll=state.bankroll,
            max_position_fraction=max_position_fraction,
            fractional_kelly=fractional_kelly,
            concentration_penalty=concentration_penalty,
            operator_fraction_override=operator_fraction_override,
            size_source=size_source,
            estimated_ai_cost=estimated_ai_cost,
        )

        if sizing.capped_fraction <= 0:
            blocked_by.append("sizing")
            reasons.append("Sizing engine produced zero allowable notional.")
        if estimated_ai_cost > 0 and sizing.estimated_profit_after_ai_cost <= 0:
            blocked_by.append("ai_profitability")
            reasons.append(
                "Projected trade profit does not clear the configured Claude/API cost floor."
            )

        return RiskDecision(
            approved=not blocked_by,
            reasons=reasons if reasons else ["Trade passed all deterministic checks."],
            blocked_by=blocked_by,
            metrics={
                "net_edge": opportunity.net_edge,
                "fill_confidence": opportunity.fill_confidence,
                "liquidity_score": opportunity.liquidity_score,
                "data_age_seconds": data_age_seconds,
                "estimated_slippage": estimated_slippage,
                "total_exposure_after": round(new_total_exposure, 4),
                "bankroll_source": state.bankroll_source.value,
                "external_position_value": round(state.external_position_value, 4),
                "category_exposure_fraction": round(concentration_penalty, 4),
                "size_source": sizing.size_source,
                "estimated_ai_cost": round(estimated_ai_cost, 4),
            },
            sizing=sizing if isinstance(sizing, ProposedSize) else ProposedSize(),
        )
