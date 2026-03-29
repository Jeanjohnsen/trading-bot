from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.services.runtime import TradingRuntime

router = APIRouter()


@router.get("/agent/summary")
async def agent_summary(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.get_agent_summary()


@router.get("/agent/postmortem")
def postmortems(runtime: TradingRuntime = Depends(get_runtime)) -> list[dict]:
    return runtime.get_postmortems()

