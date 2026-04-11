from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_runtime
from app.domain.models import TradeSizeMode
from app.services.runtime import TradingRuntime

router = APIRouter()


class TradeSizePayload(BaseModel):
    mode: TradeSizeMode
    fraction: float | None = None


@router.get("/opportunities")
def opportunities(runtime: TradingRuntime = Depends(get_runtime)) -> list[dict]:
    return runtime.get_opportunities()


@router.post("/opportunities/{opportunity_id}/execute")
async def execute_opportunity(opportunity_id: str, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    try:
        report = await runtime.execute_opportunity(opportunity_id)
        return report.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/opportunities/{opportunity_id}/trade-size")
async def set_opportunity_trade_size(
    opportunity_id: str,
    payload: TradeSizePayload,
    runtime: TradingRuntime = Depends(get_runtime),
) -> dict:
    try:
        return await runtime.set_opportunity_trade_size(opportunity_id, payload.mode, payload.fraction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scan")
async def refresh(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.manual_refresh()
