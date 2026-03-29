from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, date, datetime
import logging

from app.agents.claude_client import ClaudeClient
from app.agents.claude_explainer_agent import ClaudeExplainerAgent
from app.agents.claude_orchestrator import ClaudeOrchestrator
from app.agents.claude_postmortem_agent import ClaudePostmortemAgent
from app.analytics.brier import brier_score
from app.analytics.drawdown import max_drawdown
from app.analytics.pnl import realized_pnl, unrealized_pnl
from app.analytics.sharpe import sharpe_ratio
from app.core.settings import Settings
from app.domain.models import (
    AgentNote,
    AppMode,
    DashboardSummary,
    ExecutionIntent,
    MarketQuote,
    NotificationLevel,
    NotificationMessage,
    OpportunityCandidate,
    OrderLeg,
    OrderReport,
    PositionState,
    PositionSummary,
)
from app.execution.fill_monitor import classify_fill_outcome
from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBroker
from app.execution.polymarket_client import PolymarketClient
from app.notifications.dispatcher import NotificationDispatcher
from app.risk.kill_switch import KillSwitch
from app.risk.validate_risk import RiskEngine, RiskState
from app.services.demo_data import build_demo_books, build_demo_quotes
from app.services.scanner import ScannerService
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
        self.bankroll: float = 10_000.0
        self.equity_curve: list[float] = [10_000.0]
        self.background_task: asyncio.Task | None = None

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

    def _risk_state(self) -> RiskState:
        drawdown = max_drawdown(self.equity_curve)
        return RiskState(
            bankroll=self.bankroll,
            realized_pnl_today=realized_pnl(self.positions),
            drawdown_fraction=drawdown,
            open_positions=[position for position in self.positions if position.state != PositionState.CLOSED],
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
        self.quotes, self.books = await self._load_market_data()
        risk_engine = RiskEngine(
            runtime_config=self.runtime_config,
            live_enabled=self.settings.enable_live_trading,
            kill_switch_active=self.kill_switch.is_active(),
        )
        self.opportunities = self.scanner.scan(
            quotes=self.quotes,
            books=self.books,
            mode=self.current_mode,
            risk_state=self._risk_state(),
            risk_engine=risk_engine,
        )
        self.last_scan_at = datetime.now(UTC)
        self.repository.save_market_snapshots(self.quotes)
        self.repository.replace_opportunities(self.opportunities)
        await self._refresh_agent_notes()

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

        quote = next((item for item in self.quotes if item.market_id == opportunity.market_id), None)
        if not quote:
            raise ValueError("Market quote missing.")

        unit_cost = (quote.yes_ask or quote.yes_price) + (quote.no_ask or quote.no_price)
        quantity = max(1.0, min(opportunity.executable_size, opportunity.risk.sizing.notional / max(unit_cost, 1e-6)))
        intent = ExecutionIntent(
            opportunity_id=opportunity.opportunity_id,
            market_id=opportunity.market_id,
            mode=self.current_mode,
            legs=[
                OrderLeg(outcome="yes", side="buy", price=quote.yes_ask or quote.yes_price, quantity=quantity, token_id=quote.yes_token_id),
                OrderLeg(outcome="no", side="buy", price=quote.no_ask or quote.no_price, quantity=quantity, token_id=quote.no_token_id),
            ],
            notes="Deterministic arbitrage entry.",
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
            self.equity_curve.append(self.bankroll + realized_pnl(self.positions) + unrealized_pnl(self.positions))

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
            "live_execution_enabled": self.settings.enable_live_trading,
        }

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

    def get_health(self) -> dict:
        return {
            "status": "ok",
            "mode": self.current_mode.value,
            "last_scan_at": self.last_scan_at,
            "using_demo_data": self.using_demo_data,
            "kill_switch": self.kill_switch.is_active(),
            "claude_enabled": self.claude_client.enabled,
            "claude": self.claude_client.connection_status(),
        }

    def get_overview(self) -> DashboardSummary:
        blocked = sum(1 for item in self.opportunities if item.status.value == "blocked")
        return DashboardSummary(
            bankroll=self.bankroll,
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
        open_positions = [position for position in self.positions if position.state != PositionState.CLOSED]
        category_exposure: dict[str, float] = {}
        for position in open_positions:
            category_exposure[position.category] = category_exposure.get(position.category, 0.0) + position.entry_cost
        return {
            "bankroll": self.bankroll,
            "drawdown_fraction": max_drawdown(self.equity_curve),
            "daily_loss": realized_pnl(self.positions),
            "category_exposure": category_exposure,
            "kill_switch": self.kill_switch.is_active(),
            "open_risk_checks": [item["title"] for item in self.repository.list_notifications(limit=5)],
        }

    async def get_agent_summary(self) -> dict:
        summary = await self.claude_orchestrator.daily_summary(
            {
                "trade_count": len(self.orders),
                "missed_opportunities": sum(1 for item in self.opportunities if item.status.value == "blocked"),
                "realized_pnl": realized_pnl(self.positions),
                "unrealized_pnl": unrealized_pnl(self.positions),
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
        returns = [0.0]
        for index in range(1, len(self.equity_curve)):
            previous = self.equity_curve[index - 1]
            current = self.equity_curve[index]
            returns.append((current - previous) / max(previous, 1e-6))
        return {
            "realized_pnl": realized_pnl(self.positions),
            "unrealized_pnl": unrealized_pnl(self.positions),
            "max_drawdown": max_drawdown(self.equity_curve),
            "sharpe": sharpe_ratio(returns),
            "brier": brier_score([0.5, 0.6, 0.55], [1, 0, 1]),
            "equity_curve": self.equity_curve,
        }

    def get_settings_view(self) -> dict:
        return {
            "app": self.runtime_config.get("app", {}),
            "scanner": self.runtime_config.get("scanner", {}),
            "risk": self.runtime_config.get("risk", {}),
            "current_mode": self.current_mode.value,
            "using_demo_data": self.using_demo_data,
            "available_modes": [mode.value for mode in AppMode],
            "preset_files": ["all", "weather", "crypto", "finance", "politics", "sports"],
            "secrets": {
                "polymarket_relayer_key_present": bool(self.settings.polymarket_relayer_api_key),
                "claude_key_present": bool(self.settings.anthropic_api_key),
                "claude_agent_default": self.settings.enable_claude_agent,
            },
            "claude": self.claude_client.connection_status(),
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
