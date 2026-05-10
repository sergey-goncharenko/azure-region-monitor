# Data Model

## Snapshot JSON Structure
```json
{
  "timestamp": "2026-05-07T00:00:00Z",
  "regions": {
    "westeurope": {
      "aks": {
        "extensionTypes.microsoft.flux": {
          "status": "available"
        },
        "kubernetesVersions.1.34": {
          "status": "available"
        }
      },
      "functions": {
        "hostingPlans.flexConsumption": {
          "status": "available",
          "message": "Azure Functions Flex Consumption is listed in westeurope."
        },
        "runtimes.python.3.14": {
          "status": "available"
        }
      },
      "compute": {
        "vmSkus.standard.d2s.v5": {
          "status": "available"
        }
      }
    }
  }
}
```

Each feature result has:

- `status`: one of `available`, `unavailable`, `partial`, or `unknown`.
- `latency_ms`: optional probe latency.
- `error_code`: optional machine-readable error such as `AzureCliCommandFailed`.
- `message`: optional human-readable probe evidence.

Status semantics:

- `available`: the read-only probe found positive listing/catalog evidence for the region.
- `unavailable`: the probe completed successfully, but the feature was absent from the listing/catalog used by that probe.
- `unknown`: the probe could not produce trustworthy evidence.
- `partial`: reserved for multi-condition checks.

`unavailable` must not be interpreted as quota exhaustion unless a quota-specific or deployment lifecycle probe produced that evidence.

## Diff JSON Structure
```json
{
  "timestamp": "2026-05-07T00:00:00Z",
  "changes": [
    {
      "region": "swedencentral",
      "service": "aks",
      "feature": "extensionTypes.microsoft.flux",
      "previous": "unavailable",
      "current": "available"
    }
  ]
}
```
