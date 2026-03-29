from app.analytics.brier import brier_score
from app.analytics.drawdown import max_drawdown
from app.risk.kelly_size import kelly_fraction


def test_brier_score_computes_mean_square_error() -> None:
    score = brier_score([0.7, 0.2], [1, 0])
    assert round(score, 4) == 0.065


def test_kelly_fraction_never_returns_negative_value() -> None:
    assert kelly_fraction(0.4, 1.0) == 0.0
    assert round(kelly_fraction(0.6, 1.0), 4) == 0.2


def test_max_drawdown_uses_peak_to_trough_drop() -> None:
    assert round(max_drawdown([100, 108, 103, 96, 110]), 4) == 0.1111

