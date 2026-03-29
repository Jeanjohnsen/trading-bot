from __future__ import annotations


def calibration_error(forecasts: list[float], outcomes: list[int]) -> float:
    if not forecasts or len(forecasts) != len(outcomes):
        return 0.0
    return abs((sum(forecasts) / len(forecasts)) - (sum(outcomes) / len(outcomes)))

