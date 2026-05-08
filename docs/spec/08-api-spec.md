# API Specification

## GET /api/latest
Returns the latest availability snapshot.

## GET /api/diff
Returns the most recent diff.

## GET /api/regions/{region}
Returns availability for a specific region.

## GET /api/services/{service}
Returns availability for a specific service.

## GET /api/history/{date}
Returns historical snapshot for a given date.

## POST /api/subscribe
Registers a webhook or email for alerts.
