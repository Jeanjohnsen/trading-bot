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
- SQLite-first storage with a Postgres-ready shape
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

## App modes

`APP_MODE` controls how the system is allowed to execute trades:

- `paper`
  Safe default. Signals, risk checks, and execution flow still run, but orders are simulated through the paper broker instead of being sent live.
- `live`
  Intended for real trading. This mode is still guarded by deterministic risk checks and also requires `ENABLE_LIVE_TRADING=true`. In the current MVP, live posting is intentionally still gated until wallet signing and venue-specific execution are fully validated.
- `backtest`
  Reserved for historical replay and offline simulation. The architecture is ready for it, but the MVP does not yet include a full standalone backtest engine.

Recommended setting right now: `APP_MODE=paper`.

## Safety defaults

- Live trading is disabled by default.
- Market orders are disabled by default.
- Claude cannot bypass deterministic risk approval.
- The `storage/KILL_SWITCH` file or the dashboard emergency stop blocks new trades.
- Paper mode remains the recommended mode until fill-quality and slippage assumptions are validated with real data.

## Paper-only until validated

- Actual order signing and live posting to Polymarket
- Emergency unwind using market orders
- Cross-market group execution with strict atomicity guarantees
- Research-driven discretionary trades
- Automated config mutation by any model

## Sources used for this MVP

- Polymarket docs: https://docs.polymarket.com/index
- Polymarket orderbook reference: https://docs.polymarket.com/api-reference/market-data/get-order-book
- Anthropic Messages API: https://docs.anthropic.com/en/api/messages
- Anthropic models overview: https://docs.anthropic.com/en/docs/about-claude/models/overview
- Design reference repo: https://github.com/Jeanjohnsen/jeanjohnsen.github.io
