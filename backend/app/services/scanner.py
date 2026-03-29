from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import AppMode, MarketQuote, OpportunityCandidate, OpportunityStatus
from app.risk.validate_risk import RiskEngine, RiskState
from app.strategies.cross_market_arb import cross_market_opportunities
from app.strategies.orderbook_arb import orderbook_micro_arb
from app.strategies.sum_to_one import direct_sum_to_one_opportunity


class ScannerService:
    def __init__(self, runtime_config: dict) -> None:
        self.runtime_config = runtime_config

    def _data_age_seconds(self, market_id: str, books: dict) -> float:
        timestamps = [book.timestamp for key, book in books.items() if key.startswith(f"{market_id}:")]
        if not timestamps:
            return 9999
        newest = max(timestamps)
        return (datetime.now(UTC) - newest).total_seconds()

    def scan(
        self,
        quotes: list[MarketQuote],
        books: dict,
        mode: AppMode,
        risk_state: RiskState,
        risk_engine: RiskEngine,
    ) -> list[OpportunityCandidate]:
        risk_cfg = self.runtime_config.get("risk", {})
        fee_rate = float(risk_cfg.get("fee_rate", 0.0))
        slippage_buffer = float(risk_cfg.get("slippage_tolerance", 0.01))
        execution_buffer = float(risk_cfg.get("execution_risk_buffer", 0.005)) + float(risk_cfg.get("latency_buffer", 0.002))

        opportunities: list[OpportunityCandidate] = []
        for quote in quotes:
            direct = direct_sum_to_one_opportunity(quote, fee_rate, slippage_buffer, execution_buffer)
            if direct:
                opportunities.append(direct)

            depth = orderbook_micro_arb(
                quote,
                yes_book=books.get(f"{quote.market_id}:yes"),
                no_book=books.get(f"{quote.market_id}:no"),
                fee_rate=fee_rate,
                slippage_buffer=slippage_buffer,
                execution_risk_buffer=execution_buffer,
            )
            if depth:
                opportunities.append(depth)

        opportunities.extend(cross_market_opportunities(quotes, buffer=execution_buffer + slippage_buffer))

        for opportunity in opportunities:
            quote = next((item for item in quotes if item.market_id == opportunity.market_id), quotes[0])
            data_age = self._data_age_seconds(opportunity.market_id, books)
            estimated_slippage = max(0.001, 0.012 - (opportunity.fill_confidence * 0.01))
            risk = risk_engine.evaluate(
                opportunity=opportunity,
                quote=quote,
                state=risk_state,
                mode=mode,
                data_age_seconds=data_age,
                estimated_slippage=estimated_slippage,
            )
            if opportunity.strategy_type.value == "cross_market_arb":
                risk.approved = False
                risk.blocked_by.append("atomic_execution_pending")
                risk.reasons.append("Cross-market execution remains watch-only until atomic routing is validated.")
            opportunity.risk = risk
            opportunity.status = OpportunityStatus.APPROVED if risk.approved else OpportunityStatus.BLOCKED

        opportunities.sort(key=lambda item: (item.status == OpportunityStatus.APPROVED, item.net_edge, item.fill_confidence), reverse=True)
        return opportunities
