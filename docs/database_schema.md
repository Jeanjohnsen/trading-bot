# Database Schema

## Core tables

- `market_snapshots`
- `opportunities`
- `positions`
- `orders`
- `fills`
- `risk_events`
- `agent_notes`
- `daily_summaries`
- `failures`
- `config_changes`
- `notifications`

## Storage intent

- Snapshots and opportunities support scanner debugging and replay.
- Orders and fills provide immutable execution history.
- Failures and agent notes support post-trade learning.
- Notifications and risk events support operator visibility and incident review.
