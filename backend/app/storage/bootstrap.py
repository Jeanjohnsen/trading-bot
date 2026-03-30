from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.settings import get_settings


def sqlite_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"Only sqlite URLs are supported, got: {database_url}")
    return Path(database_url.removeprefix("sqlite:///")).resolve()


def bootstrap_database() -> Path:
    settings = get_settings()
    database_path = sqlite_path_from_url(settings.database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS market_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS opportunities (
                opportunity_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_notes (
                note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_type TEXT NOT NULL,
                related_id TEXT,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS failures (
                failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                review TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS config_changes (
                change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT NOT NULL,
                key TEXT NOT NULL,
                previous_value TEXT,
                new_value TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_summaries (
                summary_date TEXT PRIMARY KEY,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                body TEXT NOT NULL,
                win_rate REAL NOT NULL,
                fill_rate REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS forecasts (
                forecast_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_resolutions (
                resolution_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL UNIQUE,
                resolved_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_market_snapshots_market_id ON market_snapshots (market_id);
            CREATE INDEX IF NOT EXISTS idx_opportunities_detected_at ON opportunities (detected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_positions_opened_at ON positions (opened_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_notes_created_at ON agent_notes (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_forecasts_market_id_created_at ON forecasts (market_id, created_at DESC);
            """
        )
        connection.commit()

    return database_path
