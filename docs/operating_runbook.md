# Operating Runbook

## Local startup

1. Create `.env` from `.env.example`.
2. Keep `ENABLE_LIVE_TRADING=false`.
3. Start the API with `uvicorn app.main:app --app-dir backend --reload`.
4. Open the dashboard at `http://127.0.0.1:8000`.

## Pre-flight checks

- Confirm the kill switch is clear.
- Confirm mode is `paper`.
- Confirm scanner is receiving fresh orderbooks.
- Confirm opportunity feed shows non-stale timestamps.
- Confirm Anthropic API budget guard and key status before enabling agent summaries.

## Emergency actions

- Touch `storage/KILL_SWITCH` to stop new trades.
- Use dashboard emergency stop to set kill-switch state.
- If leg risk occurs, freeze new entries and run the configured unwind logic.

## Paper-only validation goals

- Validate fill simulation realism against observed live books.
- Validate slippage buffers under bursty conditions.
- Validate stale-book detection and recovery during API outages.
- Validate post-trade classification quality before trusting daily recaps.
