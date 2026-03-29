from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.services.runtime import TradingRuntime

router = APIRouter()


class KillSwitchPayload(BaseModel):
    active: bool


@router.get("/kill-switch")
def kill_switch_status(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return {"active": runtime.kill_switch.is_active()}


@router.post("/kill-switch")
async def kill_switch(payload: KillSwitchPayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.toggle_kill_switch(payload.active)

