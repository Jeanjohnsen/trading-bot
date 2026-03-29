# Architecture

## Recommended stack

- Backend: Python 3.12+ with FastAPI, SQLAlchemy, httpx
- Storage: SQLite by default, Postgres-ready schema
- Frontend: Static HTML/CSS/JS dashboard served by FastAPI
- AI layer: Anthropic Messages API with Claude as interpretation/orchestration layer
- Scheduling: in-process async scanner loop for MVP

## Layering

1. `data/`
   Pulls Polymarket market metadata and CLOB orderbooks, then normalizes them into stable market objects.
2. `strategies/`
   Computes structural and depth-aware arbitrage opportunities.
3. `risk/`
   Applies deterministic approval, sizing, kill-switch, and exposure rules.
4. `execution/`
   Routes paper trades today and provides the interface boundary for live Polymarket later.
5. `agents/`
   Uses Claude for summaries, explanations, research briefs, postmortems, and daily recaps only.
6. `storage/`
   Persists snapshots, opportunities, trades, fills, failures, agent notes, and summaries.
7. `dashboard/`
   Renders operator views against backend endpoints.

## Future Kalshi adapter path

- Keep `strategies/`, `risk/`, `analytics/`, `dashboard/`, and `storage/` unchanged.
- Implement a new connector that conforms to the market-discovery and order-routing shapes already used by `TradingRuntime`.

