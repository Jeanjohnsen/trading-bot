from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.services.runtime import TradingRuntime

router = APIRouter()


@router.get("/health")
def health(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return runtime.get_health()

