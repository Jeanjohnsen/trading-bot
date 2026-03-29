from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import agent, analytics, health, kill_switch, markets, opportunities, orders, positions, risk, settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(markets.router)
api_router.include_router(opportunities.router)
api_router.include_router(positions.router)
api_router.include_router(orders.router)
api_router.include_router(risk.router)
api_router.include_router(analytics.router)
api_router.include_router(agent.router)
api_router.include_router(settings.router)
api_router.include_router(kill_switch.router)

