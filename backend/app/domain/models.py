from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class AppMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class BankrollSource(str, Enum):
    SIMULATED = "simulated"
    VENUE_SYNCED = "venue_synced"
    VENUE_UNAVAILABLE = "venue_unavailable"


class TradeSizeMode(str, Enum):
    AUTO = "auto"
    FIXED = "fixed"


class StrategyType(str, Enum):
    SUM_TO_ONE = "sum_to_one"
    ORDERBOOK_ARB = "orderbook_arb"
    CROSS_MARKET_ARB = "cross_market_arb"
    RESEARCH_SIGNAL = "research_signal"


class OpportunityStatus(str, Enum):
    WATCH = "watch"
    APPROVED = "approved"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    FILLED = "filled"
    EXITED = "exited"


class PositionState(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"
    LEG_RISK = "leg_risk"


class NotificationLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class PriceLevel(BaseModel):
    price: float
    size: float


class OrderBookSnapshot(BaseModel):
    market_id: str
    token_id: str
    outcome: str
    timestamp: datetime = Field(default_factory=utc_now)
    bids: list[PriceLevel] = Field(default_factory=list)
    asks: list[PriceLevel] = Field(default_factory=list)
    tick_size: float = 0.01
    min_order_size: float = 1.0
    last_trade_price: float | None = None
    stale: bool = False

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def executable_ask_size(self) -> float:
        return sum(level.size for level in self.asks)


class MarketQuote(BaseModel):
    market_id: str
    event_id: str | None = None
    slug: str | None = None
    question: str
    category: str = "all"
    related_group: str | None = None
    expiry: datetime | None = None
    yes_token_id: str | None = None
    no_token_id: str | None = None
    yes_price: float
    no_price: float
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    liquidity: float = 0.0
    volume_24h: float = 0.0
    recent_move: float = 0.0
    orderbook_enabled: bool = True
    last_updated: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def liquidity_score(self) -> float:
        raw = (self.liquidity / 1_000.0) + (self.volume_24h / 5_000.0)
        return max(0.0, min(1.0, raw))

    @property
    def minutes_to_expiry(self) -> float | None:
        if not self.expiry:
            return None
        delta = self.expiry - utc_now()
        return delta.total_seconds() / 60


class AccountSnapshot(BaseModel):
    source: BankrollSource = BankrollSource.SIMULATED
    label: str = "Simulated"
    wallet_address: str | None = None
    proxy_wallet: str | None = None
    available_cash: float = 0.0
    positions_value: float = 0.0
    total_equity: float = 0.0
    active_bankroll: float = 0.0
    currency: str = "USD"
    synced: bool = False
    last_synced_at: datetime | None = None
    sync_error: str | None = None


class TradeSizeProfile(BaseModel):
    mode: TradeSizeMode = TradeSizeMode.AUTO
    fraction: float | None = None


def trade_size_key(strategy_type: StrategyType | str, market_id: str, related_market_ids: list[str] | None = None) -> str:
    strategy_value = strategy_type.value if isinstance(strategy_type, StrategyType) else str(strategy_type)
    related = ",".join(sorted(related_market_ids or []))
    return f"{strategy_value}:{market_id}:{related}"


class ProposedSize(BaseModel):
    bankroll_fraction: float = 0.0
    requested_fraction: float = 0.0
    notional: float = 0.0
    units: float = 0.0
    kelly_fraction: float = 0.0
    capped_fraction: float = 0.0
    size_source: str = "auto"
    estimated_profit: float = 0.0
    estimated_ai_cost: float = 0.0
    estimated_profit_after_ai_cost: float = 0.0


class RiskDecision(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    sizing: ProposedSize = Field(default_factory=ProposedSize)


class OpportunityCandidate(BaseModel):
    opportunity_id: str = Field(default_factory=lambda: f"opp_{uuid4().hex[:12]}")
    strategy_type: StrategyType
    market_id: str
    related_market_ids: list[str] = Field(default_factory=list)
    question: str
    category: str
    detected_at: datetime = Field(default_factory=utc_now)
    gross_edge: float
    net_edge: float
    fill_adjusted_edge: float
    depth_weighted_edge: float
    expected_profit: float
    capital_at_risk: float
    executable_size: float
    fill_confidence: float
    liquidity_score: float
    expected_holding_minutes: float
    rationale: str
    status: OpportunityStatus = OpportunityStatus.WATCH
    evidence: dict[str, Any] = Field(default_factory=dict)
    risk: RiskDecision | None = None


class OrderLeg(BaseModel):
    outcome: str
    side: str
    order_type: str = "limit"
    price: float
    quantity: float
    token_id: str | None = None


class ExecutionIntent(BaseModel):
    opportunity_id: str
    market_id: str
    mode: AppMode
    legs: list[OrderLeg]
    notes: str = ""


class FillReport(BaseModel):
    fill_id: str = Field(default_factory=lambda: f"fill_{uuid4().hex[:12]}")
    order_id: str
    market_id: str
    outcome: str
    side: str
    price: float
    quantity: float
    fee: float = 0.0
    filled_at: datetime = Field(default_factory=utc_now)


class OrderReport(BaseModel):
    order_id: str = Field(default_factory=lambda: f"ord_{uuid4().hex[:12]}")
    opportunity_id: str
    market_id: str
    legs: list[OrderLeg]
    mode: AppMode
    status: str
    created_at: datetime = Field(default_factory=utc_now)
    fills: list[FillReport] = Field(default_factory=list)
    message: str = ""


class PositionSummary(BaseModel):
    position_id: str = Field(default_factory=lambda: f"pos_{uuid4().hex[:12]}")
    market_id: str
    question: str
    category: str
    state: PositionState = PositionState.OPEN
    size: float
    entry_cost: float
    current_value: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    notes: str = ""


class AgentNote(BaseModel):
    note_type: str
    title: str
    body: str
    created_at: datetime = Field(default_factory=utc_now)
    related_id: str | None = None


class NotificationMessage(BaseModel):
    level: NotificationLevel
    title: str
    body: str
    created_at: datetime = Field(default_factory=utc_now)
    channel: str = "in_app"


class DashboardSummary(BaseModel):
    bankroll: float
    bankroll_source: BankrollSource = BankrollSource.SIMULATED
    realized_pnl: float
    unrealized_pnl: float
    active_positions: int
    blocked_trades: int
    kill_switch: bool
    mode: AppMode
    concurrent_positions: int
