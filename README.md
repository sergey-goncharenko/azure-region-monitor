# Azure Regional Feature Availability Monitor

A public service that continuously tests Azure regions for real-world feature availability (AKS extensions, Functions triggers, OpenAI models, Container Apps capabilities, etc.) and publishes:

- Near real-time availability matrix
- Daily diffs
- Historical timelines
- Notifications when something becomes newly available or broken
- APIs for SaaS companies to integrate region-readiness checks

This project aims to become the canonical source of truth for Azure regional rollout behavior.

See `/docs/spec` for full product specification and `/docs/roadmap` for the engineering plan.

PoC dashboard: <https://gray-island-09dc9e703.7.azurestaticapps.net/>

Latest JSON snapshot: <https://gray-island-09dc9e703.7.azurestaticapps.net/api/latest.json>

## Current Starter

The first implementation slice is a Python service with:

- A modular synthetic probe runner
- A deterministic sample AKS extension probe for the PoC regions
- An Azure CLI-backed AKS extension probe for real regional checks
- JSON snapshot and diff storage helpers
- A diff engine that classifies new availability and regressions
- A FastAPI read-only API matching the initial API spec
- A GitHub Actions workflow for manual or scheduled PoC runs
- A generated static dashboard and JSON endpoint for Azure Static Web Apps
- Tests for the diff engine and API behavior

## Project Structure

```text
src/azure_region_monitor/
	api.py              FastAPI app for public JSON endpoints
	cli.py              Local runner, diff command, and API server command
	diff.py             Snapshot comparison and change classification
	models.py           Pydantic data contracts
	runner.py           Probe orchestration
	storage.py          JSON load/write helpers
	probes/             Synthetic probe interfaces and implementations
data/
	snapshots/          Sample and generated availability snapshots
	diffs/              Sample and generated diffs
tests/                Unit and API tests
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install ".[dev]"
pytest
```

Generate a sample snapshot for the PoC regions:

```powershell
azure-region-monitor run --output data/snapshots/latest.json
```

Run the real Azure CLI-backed AKS extension probe locally:

```powershell
az login
az extension add --name k8s-extension --upgrade
azure-region-monitor run --probe aks-extension-cli --output data/snapshots/latest.json
```

Customize AKS extension features with comma-separated `feature=extensionType` pairs:

```powershell
$env:AKS_EXTENSION_FEATURES="extensions.gitops=microsoft.flux,extensions.monitor=microsoft.azuremonitor.containers"
azure-region-monitor run --probe aks-extension-cli --output data/snapshots/latest.json
```

Generate a diff between two snapshots:

```powershell
azure-region-monitor diff data/snapshots/2026-05-07.json data/snapshots/latest.json --output data/diffs/latest.json
```

Run the local API:

```powershell
azure-region-monitor serve --reload
```

Build the static dashboard and JSON endpoint:

```powershell
azure-region-monitor build-static --output public
```

Useful endpoints:

- `GET /api/latest`
- `GET /api/diff`
- `GET /api/regions/{region}`
- `GET /api/services/{service}`
- `GET /api/history/{date}`

## Next Engineering Steps

1. Inspect the Azure Static Web Apps deployment from `.github/workflows/synthetic-tests.yml`.
2. Confirm whether the chosen AKS extension types expose regional differences across more regions.
3. Add a more discriminating AKS lifecycle probe if list-based extension checks stay identical.
4. Add alert delivery once the daily diff flow is stable.

See [docs/poc-deployment.md](docs/poc-deployment.md) for the PoC deployment/runbook.
