from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from app.core.settings import get_settings
from app.domain.models import (
    AgentNote,
    ForecastSnapshot,
    MarketQuote,
    MarketResolution,
    NotificationMessage,
    OpportunityCandidate,
    OrderReport,
    PositionSummary,
)
from app.storage.bootstrap import bootstrap_database, sqlite_path_from_url


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)


class Repository:
    def __init__(self) -> None:
        settings = get_settings()
        self.database_path = sqlite_path_from_url(settings.database_url)
        bootstrap_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _dump_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, default=_json_default, separators=(",", ":"))

    def _load_json(self, payload_json: str) -> dict[str, Any]:
        return json.loads(payload_json)

    def replace_opportunities(self, opportunities: list[OpportunityCandidate]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM opportunities")
            connection.executemany(
                """
                INSERT INTO opportunities (opportunity_id, market_id, detected_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        opportunity.opportunity_id,
                        opportunity.market_id,
                        opportunity.detected_at.isoformat(),
                        self._dump_json(opportunity.model_dump(mode="json")),
                    )
                    for opportunity in opportunities
                ],
            )

    def save_market_snapshots(self, quotes: list[MarketQuote]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO market_snapshots (market_id, payload_json, created_at)
                VALUES (?, ?, ?)
                """,
                [
                    (
                        quote.market_id,
                        self._dump_json(quote.model_dump(mode="json")),
                        quote.last_updated.isoformat(),
                    )
                    for quote in quotes
                ],
            )

    def save_forecasts(self, forecasts: list[ForecastSnapshot]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO forecasts (forecast_id, market_id, created_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        forecast.forecast_id,
                        forecast.market_id,
                        forecast.created_at.isoformat(),
                        self._dump_json(forecast.model_dump(mode="json")),
                    )
                    for forecast in forecasts
                ],
            )

    def unresolved_forecast_market_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT f.market_id
                FROM forecasts f
                LEFT JOIN market_resolutions r ON r.market_id = f.market_id
                WHERE r.market_id IS NULL
                """
            ).fetchall()
        return [row["market_id"] for row in rows]

    def upsert_market_resolutions(self, resolutions: list[MarketResolution]) -> None:
        if not resolutions:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO market_resolutions (resolution_id, market_id, resolved_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(market_id) DO UPDATE SET
                    resolution_id = excluded.resolution_id,
                    resolved_at = excluded.resolved_at,
                    payload_json = excluded.payload_json
                """,
                [
                    (
                        resolution.resolution_id,
                        resolution.market_id,
                        resolution.resolved_at.isoformat(),
                        self._dump_json(resolution.model_dump(mode="json")),
                    )
                    for resolution in resolutions
                ],
            )

    def save_agent_note(self, note: AgentNote) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_notes (note_type, related_id, created_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    note.note_type,
                    note.related_id,
                    note.created_at.isoformat(),
                    self._dump_json(note.model_dump(mode="json")),
                ),
            )

    def save_order_report(self, report: OrderReport) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO orders (order_id, market_id, created_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    report.order_id,
                    report.market_id,
                    report.created_at.isoformat(),
                    self._dump_json(report.model_dump(mode="json")),
                ),
            )

    def save_failure(self, category: str, message: str, review: str, market_id: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO failures (market_id, category, message, review)
                VALUES (?, ?, ?, ?)
                """,
                (market_id, category, message, review),
            )

    def save_position(self, position: PositionSummary) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO positions (position_id, market_id, opened_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    position.position_id,
                    position.market_id,
                    position.opened_at.isoformat(),
                    self._dump_json(position.model_dump(mode="json")),
                ),
            )

    def save_notification(self, notification: NotificationMessage) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notifications (level, created_at, payload_json)
                VALUES (?, ?, ?)
                """,
                (
                    notification.level.value,
                    notification.created_at.isoformat(),
                    self._dump_json(notification.model_dump(mode="json")),
                ),
            )

    def save_config_change(self, actor: str, key: str, previous_value: str, new_value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO config_changes (actor, key, previous_value, new_value)
                VALUES (?, ?, ?, ?)
                """,
                (actor, key, previous_value, new_value),
            )

    def list_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM orders
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._load_json(row["payload_json"]) for row in rows]

    def list_notifications(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM notifications
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._load_json(row["payload_json"]) for row in rows]

    def latest_agent_notes(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM agent_notes
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._load_json(row["payload_json"]) for row in rows]

    def forecast_metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            forecast_count = connection.execute("SELECT COUNT(*) AS count FROM forecasts").fetchone()["count"]
            resolution_rows = connection.execute(
                "SELECT market_id, resolved_at, payload_json FROM market_resolutions"
            ).fetchall()

            resolved_scores: list[float] = []
            resolved_market_count = 0

            for resolution_row in resolution_rows:
                resolution = self._load_json(resolution_row["payload_json"])
                forecast_row = connection.execute(
                    """
                    SELECT payload_json
                    FROM forecasts
                    WHERE market_id = ? AND created_at <= ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (resolution_row["market_id"], resolution_row["resolved_at"]),
                ).fetchone()
                if not forecast_row:
                    continue
                forecast = self._load_json(forecast_row["payload_json"])
                probability = float(forecast["forecast_probability"])
                outcome = float(resolution["outcome"])
                resolved_scores.append((probability - outcome) ** 2)
                resolved_market_count += 1

        brier_score = sum(resolved_scores) / len(resolved_scores) if resolved_scores else None
        return {
            "forecast_count": forecast_count,
            "resolved_market_count": resolved_market_count,
            "brier_score": brier_score,
        }

    def save_daily_summary(
        self,
        summary_date: str,
        realized_pnl: float,
        unrealized_pnl: float,
        body: str,
        win_rate: float,
        fill_rate: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_summaries (summary_date, realized_pnl, unrealized_pnl, body, win_rate, fill_rate)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(summary_date) DO UPDATE SET
                    realized_pnl = excluded.realized_pnl,
                    unrealized_pnl = excluded.unrealized_pnl,
                    body = excluded.body,
                    win_rate = excluded.win_rate,
                    fill_rate = excluded.fill_rate
                """,
                (summary_date, realized_pnl, unrealized_pnl, body, win_rate, fill_rate),
            )
