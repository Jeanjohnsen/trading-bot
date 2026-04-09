from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None
_configured_database_url: str | None = None


def configure_database(database_url: str | None = None):
    global engine, SessionLocal, _configured_database_url

    resolved_database_url = database_url or get_settings().database_url
    if engine is not None and SessionLocal is not None and _configured_database_url == resolved_database_url:
        return engine, SessionLocal

    engine_kwargs = {"future": True, "echo": False}
    if resolved_database_url.startswith("sqlite:///:memory:"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(resolved_database_url, **engine_kwargs)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    _configured_database_url = resolved_database_url
    return engine, SessionLocal


configure_database()


def get_session() -> Generator[Session, None, None]:
    if SessionLocal is None:
        configure_database()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
