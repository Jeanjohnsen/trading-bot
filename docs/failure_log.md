# Failure Log

This file is the operator-facing narrative log. Structured records also live in the database.

## Taxonomy

- `correct_arb_capture`
- `missed_fill`
- `slippage_issue`
- `false_edge`
- `timing_issue`
- `api_or_execution_issue`
- `risk_block`
- `external_shock`
- `leg_risk`
- `stale_data`
- `metadata_conflict`

## Operating rule

Every closed trade or failed execution attempt should generate:

1. a structured database record
2. a short operator-readable summary
3. a recommended action if the issue is recurring

