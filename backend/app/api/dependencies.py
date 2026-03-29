from __future__ import annotations

from fastapi import Request

from app.services.runtime import TradingRuntime


def get_runtime(request: Request) -> TradingRuntime:
    return request.app.state.runtime

