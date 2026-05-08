# Functional Specification

## 1. Synthetic Testing Engine
- Runs daily or hourly
- Tests each Azure region
- Captures success/failure, error codes, latency
- Outputs structured JSON

## 2. Diff Engine
- Compares today's results with yesterday's
- Detects new availability, regressions, partial failures

## 3. Public Dashboard
- Region → Service matrix
- Service → Region matrix
- Timeline view
- Diff view

## 4. Alerts
- Email, Slack, Teams, Webhook, RSS
- Triggered on availability changes

## 5. Public API
- `/api/latest`
- `/api/diff`
- `/api/regions/{region}`
- `/api/services/{service}`

## 6. Historical Dataset
- Daily snapshots
- Daily diffs
