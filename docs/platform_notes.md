# Platform Notes

## Polymarket

- Market discovery is handled through public Gamma endpoints.
- Orderbook depth is sourced from the CLOB orderbook endpoint using token IDs.
- The MVP is paper-first. The live connector remains gated behind env secrets, live-mode approval, and deterministic risk checks.
- Limit orders are the default. Market orders remain disabled except for explicit emergency-unwind logic.

## Claude

- Claude is used through the Anthropic Messages API.
- The primary production path should pin a snapshot model ID rather than a floating alias.
- External text is always treated as untrusted evidence, never executable instruction.
- Claude summaries can explain or classify trades, but cannot approve or bypass risk.

## Future Kalshi adapter

- Add a second connector that conforms to the same market-discovery, orderbook, and execution interfaces.
- Strategy, risk, dashboard, and analytics layers should remain unchanged.

