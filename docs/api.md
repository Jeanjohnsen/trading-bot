# API Routes

- `GET /health`
- `GET /markets`
- `GET /opportunities`
- `POST /opportunities/{opportunity_id}/execute`
- `POST /scan`
- `GET /positions`
- `GET /orders`
- `GET /risk`
- `GET /analytics`
- `GET /agent/summary`
- `GET /agent/postmortem`
- `GET /settings`
- `GET /kill-switch`
- `POST /kill-switch`

## Notes

- Execution is paper-mode by default.
- `POST /kill-switch` is the dashboard emergency stop API.
- `POST /scan` forces an immediate rescan outside the background schedule.

