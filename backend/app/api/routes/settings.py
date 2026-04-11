from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends

from app.api.dependencies import get_runtime
from app.domain.models import AppMode, TradeSizeMode
from app.services.runtime import TradingRuntime

router = APIRouter()


class AppModePayload(BaseModel):
    mode: AppMode


class ClaudeAgentPayload(BaseModel):
    enabled: bool


class RuntimeTogglePayload(BaseModel):
    enabled: bool


class TradeSizePayload(BaseModel):
    mode: TradeSizeMode
    fraction: float | None = None


class ResearchThresholdPayload(BaseModel):
    research_signal_min_net_edge: float


@router.get("/settings")
def settings(runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return runtime.get_settings_view()


@router.post("/settings/app-mode")
async def set_app_mode(payload: AppModePayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_app_mode(payload.mode)


@router.post("/settings/claude-agent")
async def set_claude_agent(payload: ClaudeAgentPayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_claude_agent_enabled(payload.enabled)


@router.post("/settings/live-trading")
async def set_live_trading(payload: RuntimeTogglePayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_live_trading_enabled(payload.enabled)


@router.post("/settings/research-mode")
async def set_research_mode(payload: RuntimeTogglePayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_research_mode_enabled(payload.enabled)


@router.post("/settings/market-orders")
async def set_market_orders(payload: RuntimeTogglePayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_market_orders_enabled(payload.enabled)


@router.post("/settings/trade-size")
async def set_trade_size(payload: TradeSizePayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_trade_size_profile(payload.mode, payload.fraction)


@router.post("/settings/research-thresholds")
async def set_research_thresholds(payload: ResearchThresholdPayload, runtime: TradingRuntime = Depends(get_runtime)) -> dict:
    return await runtime.set_research_thresholds(payload.research_signal_min_net_edge)
