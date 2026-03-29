from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.services.runtime import TradingRuntime

router = APIRouter()


@router.get("/settings")
def settings(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return runtime.get_settings_view()

