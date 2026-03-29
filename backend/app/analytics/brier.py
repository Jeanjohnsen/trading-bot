from __future__ import annotations


def brier_score(forecasts: list[float], outcomes: list[int]) -> float:
    if not forecasts or len(forecasts) != len(outcomes):
        return 0.0
    return sum((forecast - outcome) ** 2 for forecast, outcome in zip(forecasts, outcomes, strict=False)) / len(forecasts)

