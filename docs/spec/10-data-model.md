# Data Model

## Snapshot JSON Structure
```json
{
  "timestamp": "2026-05-07T00:00:00Z",
  "regions": {
    "westeurope": {
      "aks": {
        "extensions": {
          "gitops": "available",
          "monitor": "unavailable"
        }
      }
    }
  }
}
```

## Diff JSON Structure
```json
{
  "timestamp": "2026-05-07T00:00:00Z",
  "changes": [
    {
      "region": "swedencentral",
      "service": "aks",
      "feature": "gitops",
      "previous": "unavailable",
      "current": "available"
    }
  ]
}
```
