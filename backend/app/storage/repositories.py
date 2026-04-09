from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import desc, select

from app.domain.models import AgentNote, ForecastSnapshot, MarketQuote, MarketResolution, NotificationMessage, OpportunityCandidate, OrderReport, PositionSummary
from app.storage.bootstrap import bootstrap_database
import app.storage.database as storage_db
from app.storage.models import (
    AgentNoteRecord,
    ConfigChangeRecord,
    DailySummaryRecord,
    FailureRecord,
    ForecastRecord,
    FillRecord,
    MarketSnapshotRecord,
    MarketResolutionRecord,
    NotificationRecord,
    OpportunityRecord,
    OrderRecord,
    PositionRecord,
    RiskEventRecord,
)


class Repository:
    def __init__(self) -> None:
        bootstrap_database()

    def save_market_snapshots(self, quotes: list[MarketQuote]) -> None:
        with storage_db.SessionLocal() as session:
            for quote in quotes:
                session.add(
                    MarketSnapshotRecord(
                        market_id=quote.market_id,
                        question=quote.question,
                        category=quote.category,
                        yes_price=quote.yes_price,
                        no_price=quote.no_price,
                        yes_bid=quote.yes_bid,
                        yes_ask=quote.yes_ask,
                        no_bid=quote.no_bid,
                        no_ask=quote.no_ask,
                        liquidity_score=quote.liquidity_score,
                        expires_at=quote.expiry,
                    )
                )
            session.commit()

    def replace_opportunities(self, opportunities: list[OpportunityCandidate]) -> None:
        with storage_db.SessionLocal() as session:
            session.query(OpportunityRecord).delete()
            for opportunity in opportunities:
                session.add(
                    OpportunityRecord(
                        opportunity_id=opportunity.opportunity_id,
                        market_id=opportunity.market_id,
                        strategy_type=opportunity.strategy_type.value,
                        category=opportunity.category,
                        question=opportunity.question,
                        gross_edge=opportunity.gross_edge,
                        net_edge=opportunity.net_edge,
                        fill_confidence=opportunity.fill_confidence,
                        liquidity_score=opportunity.liquidity_score,
                        status=opportunity.status.value,
                        rationale=opportunity.rationale,
                        evidence_json=json.dumps(opportunity.evidence),
                    )
                )
            session.commit()

    def save_forecasts(self, forecasts: list[ForecastSnapshot]) -> None:
        if not forecasts:
            return
        with storage_db.SessionLocal() as session:
            for forecast in forecasts:
                session.add(
                    ForecastRecord(
                        forecast_id=forecast.forecast_id,
                        market_id=forecast.market_id,
                        question=forecast.question,
                        category=forecast.category,
                        source=forecast.source,
                        mode=forecast.mode.value,
                        forecast_probability=forecast.forecast_probability,
                        market_probability=forecast.market_probability,
                        confidence=forecast.confidence,
                        edge=forecast.edge,
                        rationale=forecast.rationale,
                        expires_at=forecast.expires_at,
                        created_at=forecast.created_at,
                    )
                )
            session.commit()

    def upsert_market_resolutions(self, resolutions: list[MarketResolution]) -> None:
        if not resolutions:
            return
        with storage_db.SessionLocal() as session:
            for resolution in resolutions:
                existing = session.scalar(select(MarketResolutionRecord).where(MarketResolutionRecord.market_id == resolution.market_id))
                if existing:
                    existing.question = resolution.question
                    existing.outcome = resolution.outcome
                    existing.resolved_at = resolution.resolved_at
                    existing.source = resolution.source
                    existing.label = resolution.label
                    existing.updated_at = resolution.resolved_at
                else:
                    session.add(
                        MarketResolutionRecord(
                            market_id=resolution.market_id,
                            question=resolution.question,
                            outcome=resolution.outcome,
                            resolved_at=resolution.resolved_at,
                            source=resolution.source,
                            label=resolution.label,
                            created_at=resolution.resolved_at,
                            updated_at=resolution.resolved_at,
                        )
                    )
            session.commit()

    def unresolved_forecast_market_ids(self, limit: int = 500) -> list[str]:
        with storage_db.SessionLocal() as session:
            forecast_rows = session.scalars(select(ForecastRecord.market_id).distinct().limit(limit)).all()
            resolved_rows = session.scalars(select(MarketResolutionRecord.market_id)).all()
        resolved_ids = set(resolved_rows)
        return [market_id for market_id in forecast_rows if market_id not in resolved_ids]

    def forecast_metrics(self) -> dict:
        with storage_db.SessionLocal() as session:
            forecast_rows = session.scalars(select(ForecastRecord).order_by(desc(ForecastRecord.created_at))).all()
            resolution_rows = session.scalars(select(MarketResolutionRecord)).all()

        market_ids = {row.market_id for row in forecast_rows}
        resolution_map = {row.market_id: row for row in resolution_rows}
        paired_scores: list[float] = []
        resolved_predictions = 0

        forecasts_by_market: dict[str, list[ForecastRecord]] = {}
        for row in forecast_rows:
            forecasts_by_market.setdefault(row.market_id, []).append(row)

        for market_id, resolution in resolution_map.items():
            forecasts = forecasts_by_market.get(market_id, [])
            chosen = next((row for row in forecasts if row.created_at <= resolution.resolved_at), None)
            if not chosen:
                continue
            resolved_predictions += 1
            paired_scores.append((chosen.forecast_probability - float(resolution.outcome)) ** 2)

        tracked_markets = len(market_ids)
        resolved_markets = len(resolution_map)
        unresolved_markets = max(tracked_markets - resolved_markets, 0)

        return {
            "logged_snapshots": len(forecast_rows),
            "tracked_markets": tracked_markets,
            "resolved_markets": resolved_markets,
            "resolved_predictions": resolved_predictions,
            "unresolved_markets": unresolved_markets,
            "brier_score": (sum(paired_scores) / len(paired_scores)) if paired_scores else None,
            "latest_resolution_at": max((row.resolved_at for row in resolution_rows), default=None),
            "latest_forecast_at": forecast_rows[0].created_at if forecast_rows else None,
        }

    def save_order_report(self, report: OrderReport) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                OrderRecord(
                    order_id=report.order_id,
                    opportunity_id=report.opportunity_id,
                    market_id=report.market_id,
                    mode=report.mode.value,
                    status=report.status,
                    message=report.message,
                    raw_json=report.model_dump_json(),
                )
            )
            for fill in report.fills:
                session.add(
                    FillRecord(
                        fill_id=fill.fill_id,
                        order_id=fill.order_id,
                        market_id=fill.market_id,
                        outcome=fill.outcome,
                        side=fill.side,
                        price=fill.price,
                        quantity=fill.quantity,
                        fee=fill.fee,
                        filled_at=fill.filled_at,
                    )
                )
            session.commit()

    def save_position(self, position: PositionSummary) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                PositionRecord(
                    position_id=position.position_id,
                    market_id=position.market_id,
                    question=position.question,
                    category=position.category,
                    state=position.state.value,
                    size=position.size,
                    entry_cost=position.entry_cost,
                    current_value=position.current_value,
                    realized_pnl=position.realized_pnl,
                    unrealized_pnl=position.unrealized_pnl,
                    notes=position.notes,
                    opened_at=position.opened_at,
                    closed_at=position.closed_at,
                )
            )
            session.commit()

    def save_risk_event(self, event_type: str, severity: str, message: str, context: dict) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                RiskEventRecord(
                    event_type=event_type,
                    severity=severity,
                    message=message,
                    context_json=json.dumps(context),
                )
            )
            session.commit()

    def save_agent_note(self, note: AgentNote) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                AgentNoteRecord(
                    note_type=note.note_type,
                    related_id=note.related_id,
                    title=note.title,
                    body=note.body,
                    created_at=note.created_at,
                )
            )
            session.commit()

    def save_notification(self, notification: NotificationMessage) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                NotificationRecord(
                    level=notification.level.value,
                    title=notification.title,
                    body=notification.body,
                    channel=notification.channel,
                    created_at=notification.created_at,
                )
            )
            session.commit()

    def save_failure(self, category: str, description: str, lesson: str, market_id: str | None = None) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                FailureRecord(
                    failure_id=f"fail_{uuid4().hex[:12]}",
                    category=category,
                    market_id=market_id,
                    description=description,
                    lesson=lesson,
                )
            )
            session.commit()

    def save_daily_summary(self, summary_date: str, realized_pnl: float, unrealized_pnl: float, body: str, win_rate: float, fill_rate: float) -> None:
        with storage_db.SessionLocal() as session:
            existing = session.scalar(select(DailySummaryRecord).where(DailySummaryRecord.summary_date == summary_date))
            if existing:
                existing.realized_pnl = realized_pnl
                existing.unrealized_pnl = unrealized_pnl
                existing.body = body
                existing.win_rate = win_rate
                existing.fill_rate = fill_rate
            else:
                session.add(
                    DailySummaryRecord(
                        summary_date=summary_date,
                        realized_pnl=realized_pnl,
                        unrealized_pnl=unrealized_pnl,
                        body=body,
                        win_rate=win_rate,
                        fill_rate=fill_rate,
                    )
                )
            session.commit()

    def save_config_change(self, actor: str, key: str, previous_value: str, new_value: str) -> None:
        with storage_db.SessionLocal() as session:
            session.add(
                ConfigChangeRecord(
                    actor=actor,
                    key=key,
                    previous_value=previous_value,
                    new_value=new_value,
                )
            )
            session.commit()

    def list_orders(self, limit: int = 100) -> list[dict]:
        with storage_db.SessionLocal() as session:
            rows = session.scalars(select(OrderRecord).order_by(desc(OrderRecord.created_at)).limit(limit)).all()
        return [
            {
                "order_id": row.order_id,
                "market_id": row.market_id,
                "opportunity_id": row.opportunity_id,
                "mode": row.mode,
                "status": row.status,
                "message": row.message,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def list_notifications(self, limit: int = 20) -> list[dict]:
        with storage_db.SessionLocal() as session:
            rows = session.scalars(select(NotificationRecord).order_by(desc(NotificationRecord.created_at)).limit(limit)).all()
        return [
            {
                "level": row.level,
                "title": row.title,
                "body": row.body,
                "channel": row.channel,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def latest_agent_notes(self, limit: int = 10) -> list[dict]:
        with storage_db.SessionLocal() as session:
            rows = session.scalars(select(AgentNoteRecord).order_by(desc(AgentNoteRecord.created_at)).limit(limit)).all()
        return [
            {
                "note_type": row.note_type,
                "title": row.title,
                "body": row.body,
                "created_at": row.created_at,
                "related_id": row.related_id,
            }
            for row in rows
        ]
