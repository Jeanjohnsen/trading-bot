# Formulas

## Core probability and forecast formulas

- `edge = p_model - p_market`
- `EV = p * b - (1 - p)`
- `mispricing_score = (p_model - p_market) / max(spread_floor, volatility_floor)`
- `brier = mean((forecast_probability - outcome) ** 2)`
- `kelly_fraction = ((b * p) - (1 - p)) / b`

## Arbitrage formulas

- `gross_arb = 1.0 - (yes_entry + no_entry)`
- `net_arb = gross_arb - fees - slippage_buffer - execution_risk_buffer`
- `fill_adjusted_edge = expected_profit / capital_at_risk`
- `depth_weighted_edge = ((1.0 * executable_size) - total_entry_cost - buffers) / capital_at_risk`

## Practical notes

- For structural YES/NO arbitrage, deterministic mechanical edge takes precedence over any model-derived probability.
- Kelly sizing is always fractional in this system and always capped by deterministic bankroll and exposure limits.
- If a trade only looks attractive at top-of-book but not at executable depth, the strategy must reject it.

