# POLY-ARB AGENT

POLY-ARB AGENT is a production-minded MVP for structural prediction-market trading on Polymarket, built paper-first with deterministic arbitrage logic and Claude as an interpretation layer rather than a free-form execution engine.

## What this MVP includes

- Deterministic scanners for:
  - direct sum-to-one arbitrage
  - orderbook depth-aware arbitrage
  - cross-market consistency checks
- Deterministic risk engine with:
  - kill switch
  - live-mode lock
  - edge, liquidity, drawdown, daily loss, concurrency, and slippage guards
- Paper broker and order router with immutable event logging
- FastAPI backend with typed JSON endpoints
- Dark editorial dashboard styled to match the referenced personal site
- Claude agent layer for:
  - opportunity interpretation
  - optional research briefs
  - trade explanations
  - post-trade reviews
  - daily recap summaries
- Directional research-signal opportunities derived from deterministic forecast snapshots
- SQLite-first storage with a Postgres-ready shape
- Forecast logging and analytics with:
  - deterministic research forecast snapshots
  - outcome/resolution syncing from closed Polymarket markets
  - real Brier Score based on logged forecasts that resolved
- Tests and fixtures for core formulas, risk checks, and strategy edge cases

## Architecture

```text
backend/app/
  api/            FastAPI routes and response schemas
  analytics/      PnL, drawdown, Brier, Sharpe, calibration helpers
  agents/         Claude wrappers and prompt-safe orchestration
  core/           Settings, logging, config loading
  data/           Market ingestion, orderbook ingestion, normalization
  domain/         Shared enums and Pydantic models
  execution/      Polymarket interface, paper broker, routing, fill monitoring
  notifications/  In-app and outbound alert dispatch
  risk/           Deterministic validation, sizing, kill switch
  services/       Scanner, state aggregation, summaries
  storage/        Database models, sessions, repositories
  strategies/     Arbitrage logic
dashboard/        Static operator UI served by FastAPI
config/           Environment, preset, and risk profile YAML
docs/             Formulas, notes, runbook, lessons
tests/            Unit and integration coverage with canned fixtures
```

## Quick start

1. Create and activate a virtual environment with `python -m venv .venv`, then run `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Unix).
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and add your real secrets locally.
4. Start the API:

```bash
uvicorn app.main:app --app-dir backend --reload
```

5. Open `http://127.0.0.1:8000`.

## Claude controls

- `ENABLE_CLAUDE_AGENT=true`
  Initial default for Claude orchestration, explanations, summaries, and postmortems. The dashboard can also toggle Claude on or off at runtime.
- `ENABLE_RESEARCH_MODE=true|false`
  Only controls the optional research workflow. It does not control the main Claude agent layer.
- Demo/bootstrap data automatically disables Claude at runtime, even if `ENABLE_CLAUDE_AGENT=true`, to avoid spending tokens on non-live market data.
- The dashboard Settings panel includes a runtime Claude toggle. If demo data is active, the toggle can be switched on, but Claude will still remain blocked until real market data is in use.

This means Claude can still be enabled in `paper`, `live`, or `backtest` modes while `ENABLE_RESEARCH_MODE=false`, `ENABLE_LIVE_TRADING=false`, and `ENABLE_MARKET_ORDERS=false`.

## Runtime control layers

There are four separate control layers in the app:

- `APP_MODE`
  Selects the overall operating mode: `paper`, `live`, or `backtest`.
- Execution gates
  `ENABLE_LIVE_TRADING`, `ENABLE_MARKET_ORDERS`, and the kill switch decide whether the app is actually allowed to send or simulate trades.
- Data source
  `BOOTSTRAP_DEMO_DATA=true` allows demo/fallback market data if live venue data is unavailable.
- Research / forecasting
  `ENABLE_RESEARCH_MODE=true` turns on deterministic research forecast logging, resolution tracking, and directional research-signal opportunities without requiring live trading.

## App modes

`APP_MODE` controls how the system is allowed to execute trades:

- `paper`
  Safe default. Signals, risk checks, and execution flow still run, but orders are simulated through the paper broker instead of being sent live.
- `live`
  Intended for real trading. This mode is still guarded by deterministic risk checks and also requires `ENABLE_LIVE_TRADING=true`. The current MVP supports real Polymarket live posting for single-leg `research_signal` opportunities only. Multi-leg strategies remain non-live until routing and leg-risk controls are validated.
- `backtest`
  Reserved for historical replay and offline simulation. The architecture is ready for it, but the MVP does not yet include a full standalone backtest engine.

Recommended setting right now: `APP_MODE=paper`.

## Suggested operating path

- Data collection only
  Use `APP_MODE=paper`, keep `ENABLE_LIVE_TRADING=false`, and leave the kill switch active. This gives you real market ingestion and logging without live execution.
- Research and prediction tracking
  Keep `APP_MODE=paper`, set `ENABLE_RESEARCH_MODE=true`, and optionally enable Claude if you want research briefs. Forecasts will be logged, later matched with resolved market outcomes, included in Brier analytics, and can surface directional research-signal opportunities in the execution feed.
- Paper execution
  Use `APP_MODE=paper` with live trading still off. This is the correct place to validate sizing, slippage assumptions, and risk blocks.
- Live execution
  Use `APP_MODE=live` only after paper validation, and only with `ENABLE_LIVE_TRADING=true`. Real live posting now exists for single-leg `research_signal` opportunities when signer credentials are configured. Multi-leg strategies still remain paper/watch-only.

## Bankroll sources

- `PAPER_BANKROLL`
  Sets the simulated bankroll used in `paper` and `backtest` modes.
- `POLYMARKET_WALLET_ADDRESS`
  Optional explicit wallet address for venue balance sync. If omitted, the app falls back to `POLYMARKET_RELAYER_API_KEY_ADDRESS`.
- `POLYMARKET_PROXY_WALLET`
  Optional override for the Polymarket proxy wallet. If omitted, the app will try to resolve the proxy wallet from Polymarket's public profile API.
- `POLYMARKET_PRIVATE_KEY`
  Required for authenticated live posting to the Polymarket CLOB API. This key is used only for signing live orders and should never be exposed in logs or API payloads.
- In `paper` mode, risk sizing uses the simulated bankroll and the UI labels it clearly as `Simulated`.
- In `live` mode, risk sizing uses the synced Polymarket venue cash balance and the UI labels it as `Venue-synced`.
- The dashboard also shows venue positions value separately so you can see how much cash is available to deploy versus how much is already tied up on the venue.

## Trade sizing

- `Auto Kelly`
  Uses the deterministic Kelly-style sizing logic already built into the risk engine.
- `Global fixed size`
  The Settings panel can switch the whole app to a fixed bankroll fraction such as `2%`, `5%`, or `10%`.
- `Manual override`
  The Execution View can override sizing for a single trade from the dashboard.
- All fixed sizing is still clipped by the hard cap in `risk.max_position_bankroll_fraction`.
- The risk engine also checks that projected expected profit clears the configured Claude/API cost floor before approving a trade.

## Forecast logging and Brier Score

- Forecast logging only runs when `ENABLE_RESEARCH_MODE=true`.
- On each scan, the app writes deterministic forecast snapshots for current markets.
- The forecast model is a bounded research baseline:
  - market-implied YES probability
  - plus a small deterministic momentum/liquidity adjustment
- The app also polls closed Polymarket markets and records resolved YES/NO outcomes for any market that has open forecast records.
- The dashboard Brier Score is calculated from the latest forecast snapshot that existed before each market resolved.
- If no forecasted markets have resolved yet, the dashboard shows no meaningful Brier score yet.

This means you can collect data and evaluate forecast quality before enabling any live execution.

## Safety defaults

- Live trading is disabled by default.
- Market orders are disabled by default.
- Claude cannot bypass deterministic risk approval.
- The `storage/KILL_SWITCH` file or the dashboard emergency stop blocks new trades.
- Paper mode remains the recommended mode until fill-quality and slippage assumptions are validated with real data.

## Still paper-only until validated

- Emergency unwind using market orders
- Multi-leg live posting for `sum_to_one` and `orderbook_arb`
- Cross-market group execution with strict atomicity guarantees
- Claude-driven discretionary trades
- Automated config mutation by any model
- Full historical backtest replay engine

## Current platform scope

- Polymarket is integrated now.
- Kalshi is not yet integrated in the current MVP, even though the architecture is prepared for an adapter later.

## Sources used for this MVP

- Polymarket docs: https://docs.polymarket.com/index
- Polymarket orderbook reference: https://docs.polymarket.com/api-reference/market-data/get-order-book
- Anthropic Messages API: https://docs.anthropic.com/en/api/messages
- Anthropic models overview: https://docs.anthropic.com/en/docs/about-claude/models/overview
- Design reference repo: https://github.com/Jeanjohnsen/jeanjohnsen.github.io
