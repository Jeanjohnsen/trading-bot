from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.logging import configure_logging
from app.core.settings import ROOT_DIR, get_settings
from app.services.runtime import TradingRuntime
from app.storage.bootstrap import bootstrap_database
from app.storage.repositories import Repository


settings = get_settings()
dashboard_dir = ROOT_DIR / "dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    bootstrap_database()
    runtime = TradingRuntime(settings=settings, repository=Repository())
    app.state.runtime = runtime
    await runtime.startup()
    try:
        yield
    finally:
        await runtime.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router)
app.mount("/assets", StaticFiles(directory=dashboard_dir / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(dashboard_dir / "index.html")


@app.get("/app.js", include_in_schema=False)
def dashboard_js() -> FileResponse:
    return FileResponse(dashboard_dir / "app.js")


@app.get("/styles.css", include_in_schema=False)
def dashboard_css() -> FileResponse:
    return FileResponse(dashboard_dir / "styles.css")
