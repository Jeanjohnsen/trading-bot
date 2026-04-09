import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

from app.core.settings import get_settings
from app.domain.models import OpportunityCandidate, StrategyType


def _structured_schema(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE opportunities (
            id INTEGER PRIMARY KEY,
            opportunity_id VARCHAR(64) NOT NULL,
            market_id VARCHAR(128) NOT NULL,
            strategy_type VARCHAR(64) NOT NULL,
            category VARCHAR(64) NOT NULL,
            question VARCHAR(512) NOT NULL,
            gross_edge FLOAT NOT NULL,
            net_edge FLOAT NOT NULL,
            fill_confidence FLOAT NOT NULL,
            liquidity_score FLOAT NOT NULL,
            status VARCHAR(32) NOT NULL,
            rationale TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        """
    )
    connection.commit()
    connection.close()


def _sample_opportunity() -> OpportunityCandidate:
    return OpportunityCandidate(
        strategy_type=StrategyType.SUM_TO_ONE,
        market_id="m1",
        question="Test market",
        category="finance",
        gross_edge=0.04,
        net_edge=0.03,
        fill_adjusted_edge=0.03,
        depth_weighted_edge=0.02,
        expected_profit=3.0,
        capital_at_risk=95.0,
        executable_size=100.0,
        fill_confidence=0.8,
        liquidity_score=0.8,
        expected_holding_minutes=5,
        rationale="Test",
    )


def _workspace_db_path() -> Path:
    path = Path(tempfile.gettempdir()) / f"test_storage_bootstrap_{uuid4().hex}.db"
    if path.exists():
        path.unlink()
    return path


def test_bootstrap_database_accepts_existing_structured_schema(monkeypatch) -> None:
    db_path = _workspace_db_path()
    _structured_schema(db_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()

    from app.storage.bootstrap import bootstrap_database

    bootstrap_database()

    connection = sqlite3.connect(db_path)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(opportunities)").fetchall()]
    connection.close()

    assert "created_at" in columns
    assert "updated_at" in columns


def test_repository_replace_opportunities_works_with_structured_schema(monkeypatch) -> None:
    db_path = _workspace_db_path()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()

    from app.storage.bootstrap import bootstrap_database
    from app.storage.repositories import Repository

    bootstrap_database()
    repository = Repository()
    opportunity = _sample_opportunity()

    repository.replace_opportunities([opportunity])

    connection = sqlite3.connect(db_path)
    row = connection.execute("SELECT opportunity_id, market_id, strategy_type FROM opportunities").fetchone()
    connection.close()

    assert row == (opportunity.opportunity_id, "m1", "sum_to_one")
