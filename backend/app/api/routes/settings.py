from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.domain.models import AppMode
from app.services.runtime import TradingRuntime

router = APIRouter()


class AppModePayload(BaseModel):
    mode: AppMode


class ClaudeAgentPayload(BaseModel):
    enabled: bool


@router.get("/settings")
def settings(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return runtime.get_settings_view()


@router.post("/settings/app-mode")
async def set_app_mode(payload: AppModePayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_app_mode(payload.mode)


@router.post("/settings/claude-agent")
async def set_claude_agent(payload: ClaudeAgentPayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_claude_agent_enabled(payload.enabled)
