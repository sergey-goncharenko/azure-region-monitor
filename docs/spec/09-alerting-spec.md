# Alerting Specification

## Trigger Types
- First observed feature in the retained regional catalog (not merely a new region for an existing feature)
- New availability
- Regression (feature becomes unavailable)
- Partial failure
- Latency degradation (optional v2)

## Delivery Channels
- Email
- Slack
- Microsoft Teams
- Webhook
- RSS feed

## Alert Payload
- Region
- Service
- Previous state
- New state
- Timestamp

## First-observation event contract

`/api/history/changes/{date}.json` contains an uncapped `feature_events` array.
Each `new_feature` event has a stable `id` derived from the service and feature
identity, `date`, `observed_at`, `service`, `feature`, `modality`, sorted `regions`
with positive read-only listing evidence, and `evidence_path` to the daily change
document. The same records are included in the history index and recent-changes
projection. Notification consumers can deduplicate on `id` without comparing
snapshots or relying on the capped regional `highlights` array. No delivery
channel is implemented by this event contract.

The first retained snapshot is a baseline, not a discovery. An event requires a
previous snapshot, previously monitored service/feature family, and no occurrence
of the feature (including unknown or unavailable) in any earlier retained
snapshot. Missing earlier snapshot evidence suppresses first-observation events.
“First” means first observed within retained history, not first Azure launch;
regional listings do not establish deployability, quota, or capacity.
