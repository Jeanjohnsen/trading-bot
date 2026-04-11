from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
import logging
from collections import Counter

from app.agents.claude_client import ClaudeClient
from app.agents.claude_explainer_agent import ClaudeExplainerAgent
from app.agents.claude_orchestrator import ClaudeOrchestrator
from app.agents.claude_postmortem_agent import ClaudePostmortemAgent
from app.analytics.drawdown import max_drawdown
from app.analytics.pnl import realized_pnl, unrealized_pnl
from app.analytics.sharpe import sharpe_ratio
from app.core.settings import Settings
from app.domain.models import (
    AccountSnapshot,
    AgentNote,
    AppMode,
    BankrollSource,
    DashboardSummary,
    ForecastSnapshot,
    MarketQuote,
    MarketResolution,
    NotificationLevel,
    NotificationMessage,
    OpportunityCandidate,
    OrderReport,
    PositionState,
    PositionSummary,
    StrategyType,
    TradeSizeMode,
    TradeSizeProfile,
    trade_size_key,
)
from app.execution.fill_monitor import classify_fill_outcome
from app.execution.intent_builder import build_execution_intent
from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBroker
from app.execution.polymarket_client import PolymarketClient
from app.notifications.dispatcher import NotificationDispatcher
from app.risk.kill_switch import KillSwitch
from app.risk.validate_risk import RiskEngine, RiskState
from app.services.demo_data import build_demo_books, build_demo_quotes
from app.services.scanner import ScannerService
from app.strategies.research_signal import research_signal_metrics
from app.storage.repositories import Repository

logger = logging.getLogger(__name__)


class TradingRuntime:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.runtime_config = settings.merged_runtime_config()
        self.repository = repository

        self.kill_switch = KillSwitch(settings.storage_path("KILL_SWITCH"))
        self.polymarket_client = PolymarketClient(settings)
        self.paper_broker = PaperBroker()
        self.order_router = OrderRouter(self.paper_broker, self.polymarket_client)
        self.scanner = ScannerService(self.runtime_config)
        self.notifications = NotificationDispatcher(settings, repository)

        self.claude_client = ClaudeClient(settings)
        self.claude_explainer = ClaudeExplainerAgent(self.claude_client)
        self.claude_postmortem = ClaudePostmortemAgent(self.claude_client)
        self.claude_orchestrator = ClaudeOrchestrator(self.claude_client)

        self.quotes: list[MarketQuote] = []
        self.books: dict = {}
        self.opportunities: list[OpportunityCandidate] = []
        self.positions: list[PositionSummary] = []
        self.orders: list[OrderReport] = []
        self.agent_notes: list[AgentNote] = []
        self.current_mode: AppMode = settings.app_mode
        self.using_demo_data: bool = False
        self.last_scan_at: datetime | None = None
        self.paper_bankroll: float = float(settings.paper_bankroll)
        self.live_trading_enabled: bool = bool(settings.enable_live_trading)
        self.research_mode_enabled: bool = bool(settings.enable_research_mode)
        self.market_orders_enabled: bool = bool(settings.enable_market_orders)
        self.auto_execute_enabled: bool = bool(self.runtime_config.get("app", {}).get("enable_auto_execute", False))
        self.venue_account: AccountSnapshot = AccountSnapshot(
            source=BankrollSource.VENUE_UNAVAILABLE,
            label="Venue unavailable",
            active_bankroll=0.0,
            total_equity=0.0,
            synced=False,
            sync_error="Venue sync has not run yet.",
        )
        self.global_trade_size_profile = TradeSizeProfile(mode=TradeSizeMode.AUTO, fraction=None)
        self.manual_trade_size_overrides: dict[str, TradeSizeProfile] = {}
        self.equity_curves: dict[str, list[float]] = {
            AppMode.PAPER.value: [self.paper_bankroll],
            AppMode.BACKTEST.value: [self.paper_bankroll],
            AppMode.LIVE.value: [],
        }
        self.background_task: asyncio.Task | None = None

        self.runtime_config.setdefault("app", {})
        self.runtime_config["app"]["enable_live_trading"] = self.live_trading_enabled
        self.runtime_config["app"]["enable_research_mode"] = self.research_mode_enabled
        self.runtime_config["app"]["enable_market_orders"] = self.market_orders_enabled
        self.runtime_config["app"]["enable_auto_execute"] = self.auto_execute_enabled
        self.runtime_config["app"].setdefault("auto_execute_cooldown_seconds", 900)
        self.polymarket_client.set_live_trading_enabled(self.live_trading_enabled)
        self.polymarket_client.set_market_orders_enabled(self.market_orders_enabled)

    async def startup(self) -> None:
        await self.scan_once()
        self.background_task = asyncio.create_task(self._background_loop())

    async def shutdown(self) -> None:
        if self.background_task:
            self.background_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.background_task

    async def _background_loop(self) -> None:
        refresh_seconds = int(self.runtime_config.get("scanner", {}).get("refresh_seconds", 20))
        while True:
            await asyncio.sleep(refresh_seconds)
            await self.scan_once()

    def _paper_account_snapshot(self) -> AccountSnapshot:
        open_positions = [position for position in self.positions if position.state != PositionState.CLOSED]
        realized = realized_pnl(self.positions)
        available_cash = max(self.paper_bankroll + realized - sum(position.entry_cost for position in open_positions), 0.0)
        positions_value = sum(position.current_value for position in open_positions)
        total_equity = available_cash + positions_value
        return AccountSnapshot(
            source=BankrollSource.SIMULATED,
            label="Simulated",
            available_cash=round(available_cash, 4),
            positions_value=round(positions_value, 4),
            total_equity=round(total_equity, 4),
            active_bankroll=round(available_cash, 4),
            synced=True,
        )

    def _active_account_snapshot(self) -> AccountSnapshot:
        if self.current_mode is AppMode.LIVE:
            if self.venue_account.synced:
                return self.venue_account
            return self.venue_account.model_copy(update={"active_bankroll": 0.0})
        return self._paper_account_snapshot()

    def _account_view(self) -> dict:
        paper = self._paper_account_snapshot()
        active = self._active_account_snapshot()
        return {
            "mode": self.current_mode.value,
            "paper": paper.model_dump(mode="json"),
            "venue": self.venue_account.model_dump(mode="json"),
            "active": active.model_dump(mode="json"),
        }

    def _track_equity_point(self) -> None:
        active = self._active_account_snapshot()
        if self.current_mode is AppMode.LIVE and not self.venue_account.synced:
            return
        equity_point = active.total_equity or active.active_bankroll
        curve = self.equity_curves.setdefault(self.current_mode.value, [])
        if not curve:
            curve.append(equity_point)
            return
        if abs(curve[-1] - equity_point) > 1e-6:
            curve.append(equity_point)

    def _active_equity_curve(self) -> list[float]:
        if self.current_mode is AppMode.LIVE and not self.venue_account.synced:
            return []
        active = self._active_account_snapshot()
        curve = self.equity_curves.setdefault(self.current_mode.value, [])
        if not curve:
            seed_value = active.total_equity or active.active_bankroll or self.paper_bankroll
            curve.append(seed_value)
        return curve

    def _trade_size_presets(self) -> list[float]:
        presets = self.runtime_config.get("risk", {}).get("trade_size_presets", [0.02, 0.05, 0.10])
        return [float(value) for value in presets]

    def _auto_execute_cooldown_seconds(self) -> int:
        raw_value = self.runtime_config.get("app", {}).get("auto_execute_cooldown_seconds", 900)
        with suppress(TypeError, ValueError):
            return max(0, int(raw_value))
        return 900

    def _rescore_opportunities(self) -> None:
        risk_engine = RiskEngine(
            runtime_config=self.runtime_config,
            live_enabled=self.live_trading_enabled,
            kill_switch_active=self.kill_switch.is_active(),
            claude_enabled=self.claude_client.enabled,
        )
        self.opportunities = self.scanner.scan(
            quotes=self.quotes,
            books=self.books,
            mode=self.current_mode,
            risk_state=self._risk_state(),
            risk_engine=risk_engine,
            global_trade_size=self.global_trade_size_profile,
            manual_trade_size_overrides=self.manual_trade_size_overrides,
        )
        self.repository.replace_opportunities(self.opportunities)

    def _normalize_trade_size_profile(self, mode: TradeSizeMode, fraction: float | None) -> TradeSizeProfile:
        if mode is TradeSizeMode.AUTO:
            return TradeSizeProfile(mode=TradeSizeMode.AUTO, fraction=None)
        if fraction is None:
            raise ValueError("Fixed trade-size mode requires a fraction.")
        return TradeSizeProfile(mode=TradeSizeMode.FIXED, fraction=max(0.0, float(fraction)))

    def _opportunity_trade_size_key(self, opportunity: OpportunityCandidate) -> str:
        return trade_size_key(opportunity.strategy_type, opportunity.market_id, opportunity.related_market_ids)

    def _risk_state(self) -> RiskState:
        drawdown = max_drawdown(self._active_equity_curve())
        active_account = self._active_account_snapshot()
        return RiskState(
            bankroll=active_account.active_bankroll,
            bankroll_source=active_account.source,
            venue_sync_ok=self.current_mode is not AppMode.LIVE or self.venue_account.synced,
            realized_pnl_today=realized_pnl(self.positions),
            drawdown_fraction=drawdown,
            open_positions=[position for position in self.positions if position.state != PositionState.CLOSED],
            external_position_value=self.venue_account.positions_value if self.current_mode is AppMode.LIVE and self.venue_account.synced else 0.0,
            api_spend_today=0.0,
            active_executions=0,
        )

    def _sync_claude_runtime_access(self) -> None:
        if self.using_demo_data:
            self.claude_client.set_runtime_access(
                allowed=False,
                state="disabled_demo_mode",
                message="Claude is disabled while demo/bootstrap market data is active.",
            )
        else:
            self.claude_client.set_runtime_access(
                allowed=True,
                state=None,
                message=None,
            )

    async def _load_market_data(self) -> tuple[list[MarketQuote], dict]:
        try:
            quotes = await self.polymarket_client.fetch_markets(max_markets=int(self.runtime_config.get("scanner", {}).get("max_markets", 80)))
            books = await self.polymarket_client.fetch_orderbooks(quotes[:20]) if quotes else {}
            if quotes:
                self.using_demo_data = False
                self._sync_claude_runtime_access()
                return quotes, books
        except Exception as exc:
            logger.warning("live market load failed", extra={"event": "market_load_failed", "error_message": str(exc)})
        if self.settings.bootstrap_demo_data:
            logger.info("using demo market data fallback", extra={"event": "demo_data_fallback"})
            self.using_demo_data = True
            self._sync_claude_runtime_access()
            return build_demo_quotes(), build_demo_books()
        self.using_demo_data = False
        self._sync_claude_runtime_access()
        return [], {}

    async def scan_once(self) -> None:
        (self.quotes, self.books), self.venue_account = await asyncio.gather(
            self._load_market_data(),
            self.polymarket_client.fetch_account_snapshot(),
        )
        self._track_equity_point()
        self._rescore_opportunities()
        self.last_scan_at = datetime.now(UTC)
        self.repository.save_market_snapshots(self.quotes)
        await self._sync_forecast_records()
        await self._refresh_agent_notes()
        await self._maybe_auto_execute()

    def _auto_execute_ready(self) -> bool:
        return (
            self.current_mode is AppMode.LIVE
            and self.live_trading_enabled
            and self.research_mode_enabled
            and self.auto_execute_enabled
            and not self.using_demo_data
            and not self.kill_switch.is_active()
            and self.venue_account.synced
        )

    def _has_open_position_in_market(self, market_id: str) -> bool:
        return any(position.market_id == market_id and position.state != PositionState.CLOSED for position in self.positions)

    @staticmethod
    def _order_created_at(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            with suppress(ValueError):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None

    def _iter_recent_live_orders(self, limit: int = 100) -> list[dict]:
        rows: list[dict] = []
        seen_ids: set[str] = set()
        for order in self.orders:
            if order.mode is not AppMode.LIVE:
                continue
            rows.append(
                {
                    "order_id": order.order_id,
                    "market_id": order.market_id,
                    "mode": order.mode.value,
                    "status": order.status,
                    "created_at": order.created_at,
                }
            )
            seen_ids.add(order.order_id)
        with suppress(Exception):
            for row in self.repository.list_orders(limit=limit):
                order_id = str(row.get("order_id") or "")
                if row.get("mode") != AppMode.LIVE.value or (order_id and order_id in seen_ids):
                    continue
                rows.append(row)
        return rows

    def _has_recent_live_order(self, market_id: str, now: datetime) -> bool:
        cooldown_seconds = self._auto_execute_cooldown_seconds()
        if cooldown_seconds <= 0:
            return False
        cutoff = now - timedelta(seconds=cooldown_seconds)
        suppressing_statuses = {"accepted", "open", "partial", "filled", "matched", "executing"}
        for row in self._iter_recent_live_orders():
            if row.get("market_id") != market_id:
                continue
            if str(row.get("status") or "").lower() not in suppressing_statuses:
                continue
            created_at = self._order_created_at(row.get("created_at"))
            if created_at and created_at >= cutoff:
                return True
        return False

    def _next_auto_execute_candidate(self) -> OpportunityCandidate | None:
        now = datetime.now(UTC)
        for opportunity in self.opportunities:
            if opportunity.strategy_type is not StrategyType.RESEARCH_SIGNAL:
                continue
            if opportunity.status.value != "approved":
                continue
            if not opportunity.risk or not opportunity.risk.approved:
                continue
            if self._has_open_position_in_market(opportunity.market_id):
                continue
            if self._has_recent_live_order(opportunity.market_id, now):
                continue
            return opportunity
        return None

    async def _maybe_auto_execute(self) -> None:
        if not self._auto_execute_ready():
            return
        candidate = self._next_auto_execute_candidate()
        if not candidate:
            return
        try:
            await self.execute_opportunity(candidate.opportunity_id)
        except Exception as exc:
            logger.warning(
                "auto execution failed",
                extra={
                    "event": "auto_execution_failed",
                    "opportunity_id": candidate.opportunity_id,
                    "market_id": candidate.market_id,
                    "error_message": str(exc),
                },
            )
            await self.notifications.dispatch(
                NotificationMessage(
                    level=NotificationLevel.WARNING,
                    title="Auto execution failed",
                    body=str(exc),
                )
            )

    async def _sync_forecast_records(self) -> None:
        if self.research_mode_enabled:
            forecasts = self._build_forecast_snapshots(self.quotes)
            self.repository.save_forecasts(forecasts)
        unresolved_market_ids = set(self.repository.unresolved_forecast_market_ids())
        if not unresolved_market_ids:
            return
        try:
            closed_quotes = await self.polymarket_client.fetch_closed_markets(
                max_markets=max(int(self.runtime_config.get("scanner", {}).get("max_markets", 80)), 200)
            )
        except Exception as exc:
            logger.warning(
                "closed market sync failed",
                extra={"event": "closed_market_sync_failed", "error_message": str(exc)},
            )
            return
        resolutions: list[MarketResolution] = []
        for quote in closed_quotes:
            if quote.market_id not in unresolved_market_ids:
                continue
            outcome = quote.metadata.get("resolved_outcome")
            if outcome is None:
                continue
            resolutions.append(
                MarketResolution(
                    market_id=quote.market_id,
                    question=quote.question,
                    outcome=int(outcome),
                    resolved_at=quote.expiry or quote.last_updated,
                    source="polymarket_closed_feed",
                    label="yes" if int(outcome) == 1 else "no",
                )
            )
        self.repository.upsert_market_resolutions(resolutions)

    def _build_forecast_snapshots(self, quotes: list[MarketQuote]) -> list[ForecastSnapshot]:
        forecasts: list[ForecastSnapshot] = []
        for quote in quotes:
            metrics = research_signal_metrics(quote)
            forecasts.append(
                ForecastSnapshot(
                    market_id=quote.market_id,
                    question=quote.question,
                    category=quote.category,
                    source="deterministic_research_v1",
                    mode=self.current_mode,
                    forecast_probability=float(metrics["forecast_probability"]),
                    market_probability=float(metrics["market_probability"]),
                    confidence=float(metrics["confidence"]),
                    edge=float(metrics["edge"]),
                    rationale="Deterministic research forecast using market-implied probability with bounded momentum/liquidity adjustment.",
                    expires_at=quote.expiry,
                )
            )
        return forecasts

    async def _refresh_agent_notes(self) -> None:
        self.agent_notes = []
        for opportunity in self.opportunities[:3]:
            if not opportunity.risk:
                continue
            explanation = await self.claude_explainer.explain(opportunity, opportunity.risk)
            note = AgentNote(
                note_type="opportunity_summary",
                title=f"{opportunity.strategy_type.value} on {opportunity.market_id}",
                body=explanation,
                related_id=opportunity.opportunity_id,
            )
            self.agent_notes.append(note)
            self.repository.save_agent_note(note)

    async def execute_opportunity(self, opportunity_id: str) -> OrderReport:
        opportunity = next((item for item in self.opportunities if item.opportunity_id == opportunity_id), None)
        if not opportunity or not opportunity.risk or not opportunity.risk.approved:
            raise ValueError("Opportunity is not executable.")
        if self.current_mode is AppMode.LIVE and opportunity.strategy_type is not StrategyType.RESEARCH_SIGNAL:
            raise ValueError("Live execution currently supports only research_signal opportunities.")

        quote = next((item for item in self.quotes if item.market_id == opportunity.market_id), None)
        if not quote:
            raise ValueError("Market quote missing.")

        execution_brief = await self.claude_orchestrator.execution_brief(
            opportunity=opportunity,
            risk=opportunity.risk,
            mode=self.current_mode.value,
        )
        self.repository.save_agent_note(
            AgentNote(
                note_type="execution_brief",
                title=f"Execution brief {opportunity.opportunity_id}",
                body=execution_brief,
                related_id=opportunity.opportunity_id,
            )
        )

        intent = build_execution_intent(
            opportunity=opportunity,
            quote=quote,
            mode=self.current_mode,
            notes=execution_brief,
            target_notional=opportunity.risk.sizing.notional,
        )
        report = await self.order_router.route(intent, self.books)
        self.orders.insert(0, report)
        self.repository.save_order_report(report)

        classification = classify_fill_outcome(report)
        review = await self.claude_postmortem.review(report, classification)
        self.repository.save_failure(classification, report.message, review, market_id=report.market_id)
        self.repository.save_agent_note(AgentNote(note_type="postmortem", title=f"Postmortem {report.order_id}", body=review, related_id=report.order_id))

        if report.fills:
            entry_cost = sum(fill.price * fill.quantity for fill in report.fills)
            current_value = sum(fill.quantity for fill in report.fills)
            pnl = max(0.0, current_value - entry_cost)
            position = PositionSummary(
                market_id=quote.market_id,
                question=quote.question,
                category=quote.category,
                state=PositionState.PARTIAL if report.status == "partial" else PositionState.OPEN,
                size=sum(fill.quantity for fill in report.fills),
                entry_cost=entry_cost,
                current_value=current_value,
                unrealized_pnl=pnl,
                notes=report.message,
            )
            self.positions.insert(0, position)
            self.repository.save_position(position)
            self._track_equity_point()

        await self.notifications.dispatch(
            NotificationMessage(
                level=NotificationLevel.INFO if report.fills else NotificationLevel.WARNING,
                title=f"Execution {report.status}",
                body=report.message,
            )
        )
        return report

    async def toggle_kill_switch(self, active: bool) -> dict:
        if active:
            self.kill_switch.activate()
        else:
            self.kill_switch.clear()
        await self.notifications.dispatch(
            NotificationMessage(
                level=NotificationLevel.CRITICAL if active else NotificationLevel.INFO,
                title="Kill switch changed",
                body=f"Kill switch set to {active}.",
            )
        )
        return {"active": self.kill_switch.is_active()}

    async def set_app_mode(self, mode: AppMode, actor: str = "dashboard") -> dict:
        previous_mode = self.current_mode
        self.current_mode = mode
        self.runtime_config.setdefault("app", {})
        self.runtime_config["app"]["mode"] = mode.value
        if previous_mode != mode:
            self.repository.save_config_change(actor=actor, key="app.mode", previous_value=previous_mode.value, new_value=mode.value)
            await self.notifications.dispatch(
                NotificationMessage(
                    level=NotificationLevel.WARNING if mode is AppMode.LIVE else NotificationLevel.INFO,
                    title="App mode changed",
                    body=f"Application mode changed from {previous_mode.value} to {mode.value}.",
                )
            )
            await self.scan_once()
        return {
            "mode": self.current_mode.value,
            "live_execution_enabled": self.live_trading_enabled,
        }

    async def _set_app_runtime_flag(self, key: str, enabled: bool, actor: str = "dashboard") -> dict:
        app_cfg = self.runtime_config.setdefault("app", {})
        previous = bool(app_cfg.get(key, False))
        app_cfg[key] = bool(enabled)

        if key == "enable_live_trading":
            self.live_trading_enabled = bool(enabled)
            self.polymarket_client.set_live_trading_enabled(enabled)
        elif key == "enable_research_mode":
            self.research_mode_enabled = bool(enabled)
        elif key == "enable_market_orders":
            self.market_orders_enabled = bool(enabled)
            self.polymarket_client.set_market_orders_enabled(enabled)
        elif key == "enable_auto_execute":
            self.auto_execute_enabled = bool(enabled)

        if previous != bool(enabled):
            self.repository.save_config_change(
                actor=actor,
                key=f"app.{key}",
                previous_value=str(previous).lower(),
                new_value=str(bool(enabled)).lower(),
            )
            await self.notifications.dispatch(
                NotificationMessage(
                    level=NotificationLevel.WARNING if key == "enable_live_trading" and enabled else NotificationLevel.INFO,
                    title="Runtime setting changed",
                    body=f"{key} changed from {previous} to {bool(enabled)}.",
                )
            )
            if key in {"enable_live_trading", "enable_research_mode"}:
                self._rescore_opportunities()
                await self._refresh_agent_notes()
        return self.get_settings_view()["app"]

    async def set_live_trading_enabled(self, enabled: bool, actor: str = "dashboard") -> dict:
        return await self._set_app_runtime_flag("enable_live_trading", enabled, actor)

    async def set_research_mode_enabled(self, enabled: bool, actor: str = "dashboard") -> dict:
        return await self._set_app_runtime_flag("enable_research_mode", enabled, actor)

    async def set_market_orders_enabled(self, enabled: bool, actor: str = "dashboard") -> dict:
        return await self._set_app_runtime_flag("enable_market_orders", enabled, actor)

    async def set_auto_execute_enabled(self, enabled: bool, actor: str = "dashboard") -> dict:
        return await self._set_app_runtime_flag("enable_auto_execute", enabled, actor)

    async def set_claude_agent_enabled(self, enabled: bool, actor: str = "dashboard") -> dict:
        previous_enabled = self.claude_client.operator_enabled
        self.claude_client.set_operator_enabled(enabled)
        if previous_enabled != enabled:
            self.repository.save_config_change(
                actor=actor,
                key="claude.agent_enabled",
                previous_value=str(previous_enabled).lower(),
                new_value=str(enabled).lower(),
            )
            await self.notifications.dispatch(
                NotificationMessage(
                    level=NotificationLevel.INFO,
                    title="Claude agent changed",
                    body=f"Claude agent runtime toggle changed from {previous_enabled} to {enabled}.",
                )
            )
        return self.claude_client.connection_status()

    async def set_trade_size_profile(self, mode: TradeSizeMode, fraction: float | None, actor: str = "dashboard") -> dict:
        previous = self.global_trade_size_profile.model_dump(mode="json")
        self.global_trade_size_profile = self._normalize_trade_size_profile(mode, fraction)
        current = self.global_trade_size_profile.model_dump(mode="json")
        if previous != current:
            self.repository.save_config_change(
                actor=actor,
                key="risk.trade_size_profile",
                previous_value=str(previous),
                new_value=str(current),
            )
            self._rescore_opportunities()
            await self._refresh_agent_notes()
        return self.get_settings_view()["trade_sizing"]

    async def set_research_thresholds(self, research_signal_min_net_edge: float, actor: str = "dashboard") -> dict:
        risk_cfg = self.runtime_config.setdefault("risk", {})
        previous = float(risk_cfg.get("research_signal_min_net_edge", risk_cfg.get("min_net_edge", 0.015)))
        current = max(0.0, float(research_signal_min_net_edge))
        risk_cfg["research_signal_min_net_edge"] = current

        if abs(previous - current) > 1e-9:
            self.repository.save_config_change(
                actor=actor,
                key="risk.research_signal_min_net_edge",
                previous_value=str(previous),
                new_value=str(current),
            )
            await self.notifications.dispatch(
                NotificationMessage(
                    level=NotificationLevel.INFO,
                    title="Research threshold changed",
                    body=f"research_signal_min_net_edge changed from {previous} to {current}.",
                )
            )
            self._rescore_opportunities()
            await self._refresh_agent_notes()
        return self.get_settings_view()["risk"]

    async def set_opportunity_trade_size(
        self,
        opportunity_id: str,
        mode: TradeSizeMode,
        fraction: float | None,
        actor: str = "dashboard",
    ) -> dict:
        opportunity = next((item for item in self.opportunities if item.opportunity_id == opportunity_id), None)
        if not opportunity:
            raise ValueError("Opportunity is not available.")

        override_key = self._opportunity_trade_size_key(opportunity)
        previous = self.manual_trade_size_overrides.get(override_key, TradeSizeProfile(mode=TradeSizeMode.AUTO)).model_dump(mode="json")
        if mode is TradeSizeMode.AUTO:
            self.manual_trade_size_overrides.pop(override_key, None)
            current_profile = TradeSizeProfile(mode=TradeSizeMode.AUTO)
        else:
            current_profile = self._normalize_trade_size_profile(mode, fraction)
            self.manual_trade_size_overrides[override_key] = current_profile

        current = current_profile.model_dump(mode="json")
        if previous != current:
            self.repository.save_config_change(
                actor=actor,
                key=f"risk.trade_size_override.{override_key}",
                previous_value=str(previous),
                new_value=str(current),
            )
            self._rescore_opportunities()
            await self._refresh_agent_notes()
        return {
            "opportunity_id": opportunity_id,
            "override": current,
        }

    def get_health(self) -> dict:
        return {
            "status": "ok",
            "mode": self.current_mode.value,
            "last_scan_at": self.last_scan_at,
            "using_demo_data": self.using_demo_data,
            "kill_switch": self.kill_switch.is_active(),
            "claude_enabled": self.claude_client.enabled,
            "claude": self.claude_client.connection_status(),
            "account": self._account_view(),
        }

    def get_overview(self) -> DashboardSummary:
        active_account = self._active_account_snapshot()
        blocked = sum(1 for item in self.opportunities if item.status.value == "blocked")
        return DashboardSummary(
            bankroll=active_account.active_bankroll,
            bankroll_source=active_account.source,
            realized_pnl=realized_pnl(self.positions),
            unrealized_pnl=unrealized_pnl(self.positions),
            active_positions=sum(1 for item in self.positions if item.state != PositionState.CLOSED),
            blocked_trades=blocked,
            kill_switch=self.kill_switch.is_active(),
            mode=self.current_mode,
            concurrent_positions=sum(1 for item in self.positions if item.state != PositionState.CLOSED),
        )

    def get_markets(self) -> list[dict]:
        return [quote.model_dump(mode="json") for quote in self.quotes]

    def get_opportunities(self) -> list[dict]:
        return [opportunity.model_dump(mode="json") for opportunity in self.opportunities]

    def get_positions(self) -> list[dict]:
        return [position.model_dump(mode="json") for position in self.positions]

    def get_orders(self) -> list[dict]:
        return [order.model_dump(mode="json") for order in self.orders] or self.repository.list_orders()

    def get_risk(self) -> dict:
        active_account = self._active_account_snapshot()
        open_positions = [position for position in self.positions if position.state != PositionState.CLOSED]
        category_exposure: dict[str, float] = {}
        for position in open_positions:
            category_exposure[position.category] = category_exposure.get(position.category, 0.0) + position.entry_cost
        with suppress(Exception):
            open_risk_checks = [item["title"] for item in self.repository.list_notifications(limit=5)]
            return {
                "bankroll": active_account.active_bankroll,
                "bankroll_source": active_account.source.value,
                "drawdown_fraction": max_drawdown(self._active_equity_curve()),
                "daily_loss": realized_pnl(self.positions),
                "category_exposure": category_exposure,
                "kill_switch": self.kill_switch.is_active(),
                "open_risk_checks": open_risk_checks,
                "account": self._account_view(),
            }
        return {
            "bankroll": active_account.active_bankroll,
            "bankroll_source": active_account.source.value,
            "drawdown_fraction": max_drawdown(self._active_equity_curve()),
            "daily_loss": realized_pnl(self.positions),
            "category_exposure": category_exposure,
            "kill_switch": self.kill_switch.is_active(),
            "open_risk_checks": [],
            "account": self._account_view(),
        }

    async def get_agent_summary(self) -> dict:
        blocked_reason_counts = Counter()
        approved_count = 0
        blocked_count = 0
        for opportunity in self.opportunities:
            if opportunity.risk and opportunity.risk.approved:
                approved_count += 1
            if opportunity.status.value == "blocked":
                blocked_count += 1
            if opportunity.risk:
                blocked_reason_counts.update(opportunity.risk.blocked_by)

        summary = await self.claude_orchestrator.daily_summary(
            {
                "trade_count": len(self.orders),
                "missed_opportunities": blocked_count,
                "realized_pnl": realized_pnl(self.positions),
                "unrealized_pnl": unrealized_pnl(self.positions),
                "mode": self.current_mode.value,
                "using_demo_data": self.using_demo_data,
                "kill_switch_active": self.kill_switch.is_active(),
                "live_execution_enabled": self.live_trading_enabled,
                "research_mode_enabled": self.research_mode_enabled,
                "market_orders_enabled": self.market_orders_enabled,
                "auto_execute_enabled": self.auto_execute_enabled,
                "claude_enabled": self.claude_client.enabled,
                "venue_synced": self.venue_account.synced,
                "venue_cash": self.venue_account.available_cash,
                "active_bankroll": self._active_account_snapshot().active_bankroll,
                "approved_opportunities": approved_count,
                "blocked_opportunities": blocked_count,
                "top_blockers": blocked_reason_counts.most_common(5),
            }
        )
        return {
            "summary": summary,
            "notes": [note.model_dump(mode="json") for note in self.agent_notes] or self.repository.latest_agent_notes(),
            "claude": self.claude_client.connection_status(),
        }

    def get_postmortems(self) -> list[dict]:
        return [note for note in self.repository.latest_agent_notes(limit=10) if note["note_type"] == "postmortem"]

    def get_analytics(self) -> dict:
        equity_curve = self._active_equity_curve()
        returns = [0.0]
        for index in range(1, len(equity_curve)):
            previous = equity_curve[index - 1]
            current = equity_curve[index]
            returns.append((current - previous) / max(previous, 1e-6))
        forecasting = self.repository.forecast_metrics()
        return {
            "realized_pnl": realized_pnl(self.positions),
            "unrealized_pnl": unrealized_pnl(self.positions),
            "max_drawdown": max_drawdown(equity_curve),
            "sharpe": sharpe_ratio(returns),
            "brier": forecasting.get("brier_score"),
            "forecasting": forecasting,
            "equity_curve": equity_curve,
        }

    def get_settings_view(self) -> dict:
        risk_cfg = self.runtime_config.get("risk", {})
        return {
            "app": self.runtime_config.get("app", {}),
            "scanner": self.runtime_config.get("scanner", {}),
            "risk": risk_cfg,
            "current_mode": self.current_mode.value,
            "using_demo_data": self.using_demo_data,
            "available_modes": [mode.value for mode in AppMode],
            "preset_files": ["all", "weather", "crypto", "finance", "politics", "sports"],
            "secrets": {
                "polymarket_relayer_key_present": bool(self.settings.polymarket_relayer_api_key),
                "polymarket_private_key_present": bool(self.settings.polymarket_private_key),
                "claude_key_present": bool(self.settings.anthropic_api_key),
                "claude_agent_default": self.settings.enable_claude_agent,
            },
            "claude": self.claude_client.connection_status(),
            "account": self._account_view(),
            "trade_sizing": {
                "global": self.global_trade_size_profile.model_dump(mode="json"),
                "presets": self._trade_size_presets(),
                "hard_cap": float(risk_cfg.get("max_position_bankroll_fraction", 0.05)),
                "estimated_claude_cost_per_trade_usd": float(risk_cfg.get("estimated_claude_cost_per_trade_usd", 0.0)),
            },
        }

    async def manual_refresh(self) -> dict:
        await self.scan_once()
        return {"status": "refreshed", "at": self.last_scan_at}

    async def daily_recap(self) -> dict:
        summary = await self.get_agent_summary()
        self.repository.save_daily_summary(
            summary_date=date.today().isoformat(),
            realized_pnl=realized_pnl(self.positions),
            unrealized_pnl=unrealized_pnl(self.positions),
            body=summary["summary"],
            win_rate=1.0 if self.orders else 0.0,
            fill_rate=len([order for order in self.orders if order.fills]) / max(len(self.orders), 1),
        )
        return summary
