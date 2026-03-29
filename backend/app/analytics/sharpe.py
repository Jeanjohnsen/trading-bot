from __future__ import annotations

from math import sqrt


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [value - risk_free_rate for value in returns]
    mean_return = sum(excess) / len(excess)
    variance = sum((value - mean_return) ** 2 for value in excess) / (len(excess) - 1)
    if variance <= 0:
        return 0.0
    return mean_return / (variance ** 0.5) * sqrt(len(excess))

