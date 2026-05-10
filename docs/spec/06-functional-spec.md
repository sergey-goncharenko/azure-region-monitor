# Functional Specification

## 1. Synthetic Testing Engine
- Runs on a schedule or by manual focused modality workflow
- Tests each tracked Azure region
- Captures read-only listing evidence, error codes, messages, and latency
- Outputs structured JSON
- Supports focused modality snapshots that can be merged into the live dashboard snapshot

## 2. Diff Engine
- Compares today's results with yesterday's
- Detects new availability, regressions, partial failures

## 3. Public Dashboard
- Summary metrics and modality summary tables
- Region by modality/group matrix
- Paged detailed heatmap backed by `api/latest.json`
- Human-readable status methodology page
- Recent changes panel backed by compact daily change summaries

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
- Compact recent-change summaries
