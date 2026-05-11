# Azure Regional Feature Availability Monitor

A public service that continuously tests Azure regions for real-world feature availability (AKS extensions, Functions triggers, OpenAI models, Container Apps capabilities, etc.) and publishes:

- Near real-time availability matrix
- Daily diffs
- Historical timelines
- Notifications when something becomes newly available or broken
- APIs for SaaS companies to integrate region-readiness checks

This project aims to become the canonical source of truth for Azure regional rollout behavior.

## Public Alpha

Azure Region Monitor is preparing for a public alpha release. The current alpha surface is a read-only regional availability dashboard and JSON API backed by Azure CLI/catalog evidence.

Alpha scope:

- Public dashboard and static JSON APIs
- Daily snapshot history and recent change summaries
- Focused workflows per modality
- Explicit methodology for status semantics and evidence limits

Alpha limits:

- Results are catalog/listing evidence, not deployment guarantees.
- The project does not publish tenant IDs, subscription IDs, private resource names, credentials, or customer data.
- Alerts, signed webhooks, SDKs, and durable external snapshot storage are future roadmap items.

See `/docs/spec` for full product specification and `/docs/roadmap` for the engineering plan.

See [docs/release/public-alpha.md](docs/release/public-alpha.md) for the public alpha release checklist.

License: [MIT](LICENSE)

Public website: <https://azwatch.operator.lat/>

Latest JSON snapshot: <https://azwatch.operator.lat/api/latest.json>

Status meanings and methodology: <https://azwatch.operator.lat/methodology.html>

## Current Starter

The first implementation slice is a Python service with:

- A modular synthetic probe runner
- A deterministic sample AKS extension probe for the PoC regions
- An Azure CLI-backed AKS extension probe for real regional checks
- An Azure CLI-backed AKS extension catalog probe that tracks every listed extension type per region
- An Azure CLI-backed AKS Kubernetes version probe for minor-version rollout checks
- An Azure CLI-backed Azure Functions Flex Consumption probe for hosting/runtime rollout checks
- An Azure CLI-backed Azure AI model catalog probe for model/version regional rollout checks
- An Azure CLI-backed Container Apps provider metadata probe for Microsoft.App resource type regional rollout checks
- An Azure CLI-backed VM SKU probe for compute SKU regional availability
- JSON snapshot and diff storage helpers
- Daily static snapshot history and compact recent-change summaries
- A human-readable methodology page explaining what each status means
- A diff engine that classifies new availability and regressions
- A FastAPI read-only API matching the initial API spec
- A GitHub Actions workflow for manual or scheduled PoC runs
- A generated static dashboard and JSON endpoint for Azure Static Web Apps
- Tests for the diff engine and API behavior

## Scope Discovery

The full scheduled workflow runs daily and uses the Python `DEFAULT_REGIONS` list when the region input is left blank. That list tracks Azure physical locations returned by Azure CLI, including recommended and other public cloud locations.

Feature items are mixed by design:

- AKS extension catalog, Azure AI model catalog, and VM SKU runs discover the listed feature universe from each full scan and normalize missing discovered items to `unavailable` in regions where the listing probe succeeded. Full and VM-focused workflows pass `AZURE_VM_SKUS=all`, so VM SKU rows cover every listed size returned by `az vm list-sizes`.
- Azure Functions runtimes, Container Apps resource types, and AKS Kubernetes minor-version prefixes are configured lists that are refreshed when we update the monitor config.
- Dashboard modality groups are derived from feature names in the snapshot at build time, so new discovered publishers, model families, or SKU families appear automatically after a full scan.

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

Run the full read-only regional probe set locally:

```powershell
azure-region-monitor run --probe aks-extension-catalog-cli --probe aks-version-cli --probe function-flex-cli --probe ai-model-catalog-cli --probe container-apps-provider-cli --probe vm-sku-cli --output data/snapshots/latest.json
```

Run the read-only VM SKU probe locally:

```powershell
azure-region-monitor run --probe vm-sku-cli --output data/snapshots/latest.json
```

Run the read-only Azure Functions Flex Consumption probe locally:

```powershell
azure-region-monitor run --probe function-flex-cli --output data/snapshots/latest.json
```

By default, the Functions probe checks every versioned Linux runtime currently listed by Azure CLI, excluding the unversioned custom runtime entry.

Run the read-only Azure AI model catalog probe locally:

```powershell
azure-region-monitor run --probe ai-model-catalog-cli --output data/snapshots/latest.json
```

By default, the AI model probe tracks every model/version returned by `az cognitiveservices model list --location <region> --output json` and normalizes regional absences across the snapshot.

Run the read-only Container Apps provider metadata probe locally:

```powershell
azure-region-monitor run --probe container-apps-provider-cli --output data/snapshots/latest.json
```

By default, the Container Apps probe checks Microsoft.App provider metadata for managed environments, apps, jobs, Dapr components, and connected environments.

Default regions now cover a small global spread:

```text
eastus, eastus2, westus3, westeurope, northeurope, swedencentral, uksouth, germanywestcentral, southeastasia, australiaeast
```

Customize AKS extension features with comma-separated `feature=extensionType` pairs:

```powershell
$env:AKS_EXTENSION_FEATURES="extensions.gitops=microsoft.flux,extensions.monitor=microsoft.azuremonitor.containers"
azure-region-monitor run --probe aks-extension-cli --output data/snapshots/latest.json
```

Customize AKS Kubernetes minor versions with comma-separated prefixes:

```powershell
$env:AKS_KUBERNETES_VERSION_PREFIXES="1.32,1.33,1.34,1.35"
azure-region-monitor run --probe aks-version-cli --output data/snapshots/latest.json
```

Customize VM SKUs with comma-separated SKU names:

```powershell
$env:AZURE_VM_SKUS="Standard_B2s,Standard_D2s_v5,Standard_D2as_v5,Standard_E2s_v5"
azure-region-monitor run --probe vm-sku-cli --output data/snapshots/latest.json
```

Set `AZURE_VM_SKUS=all` to track every SKU returned by `az vm list-sizes` in each region:

```powershell
$env:AZURE_VM_SKUS="all"
azure-region-monitor run --probe vm-sku-cli --output data/snapshots/latest.json
```

Customize Azure Functions runtime checks with comma-separated `feature=runtime` pairs:

```powershell
$env:FUNCTION_RUNTIME_FEATURES="runtimes.python.3.12=PYTHON|3.12,runtimes.node.22=NODE|22"
azure-region-monitor run --probe function-flex-cli --output data/snapshots/latest.json
```

Set `AI_MODEL_FEATURES=all` to track every model/version listed in each region, or provide comma-separated `feature=model@version` pairs to track selected models:

```powershell
$env:AI_MODEL_FEATURES="aiModels.openai.gpt-4o.2024-08-06=gpt-4o@2024-08-06,aiModels.openai.text-embedding-3-large.1=text-embedding-3-large@1"
azure-region-monitor run --probe ai-model-catalog-cli --output data/snapshots/latest.json
```

Customize Container Apps resource type checks with comma-separated `feature=resourceType` pairs:

```powershell
$env:CONTAINER_APPS_RESOURCE_FEATURES="containerApps.apps=containerApps,containerApps.daprComponents=managedEnvironments/daprComponents"
azure-region-monitor run --probe container-apps-provider-cli --output data/snapshots/latest.json
```

Generate a diff between two snapshots:

```powershell
azure-region-monitor diff data/snapshots/2026-05-07.json data/snapshots/latest.json --output data/diffs/latest.json
```

Update the static dashboard history after a run:

```powershell
azure-region-monitor update-history --snapshot data/snapshots/latest.json --history-dir data/history
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
- `GET /api/history/index.json`
- `GET /api/history/recent-changes.json`
- `GET /api/history/snapshots/{date}.json.gz`
- `GET /api/history/changes/{date}.json`
- `GET /robots.txt`
- `GET /sitemap.xml`
- `GET /llms.txt`
- `GET /llms-full.txt`

## Status Semantics

Most checks are read-only catalog or listing probes. They are designed to answer "does Azure advertise this feature for this region right now?" rather than "will my deployment certainly succeed?"

- `available`: the feature was listed or matched by the probe for that region.
- `unavailable`: the probe completed successfully, but the feature was absent from the command output or catalog used by that probe.
- `unknown`: the monitor did not get trustworthy evidence, usually because the Azure CLI command failed, timed out, returned invalid JSON, or hit a provider/control-plane issue.
- `partial`: reserved for future multi-condition probes where only some required sub-checks pass.

For Azure Functions Flex Consumption, `unavailable` means the region was absent from `az functionapp list-flexconsumption-locations --output json`. Azure CLI describes that command as listing available locations for running function apps on the Flex Consumption plan. Absence from that list is not a quota result; quota, regional capacity, policy, provider registration, and create-time failures require separate signals.

For Azure AI models, `available` means `az cognitiveservices model list --location <region> --output json` listed that model/version in the region. `unavailable` means the model/version was absent from the region's model catalog, or the regional `locations/models` endpoint reported that the region is outside its supported locations. This is catalog evidence; it does not test quota, provisioned throughput, content filtering, account approval, or a deployment invocation.

For Container Apps, `available` means `az provider show --namespace Microsoft.App --expand resourceTypes/locations --output json` advertised the configured Microsoft.App resource type in that region. `unavailable` means the provider metadata call succeeded but did not advertise that resource type for that region; it is not a deployment, quota, or Dapr runtime version test.

## Next Engineering Steps

1. Review the live Azure AI model catalog results and tune dashboard grouping if model volume makes scanning awkward.
2. Add quota/capacity-specific probes where Azure exposes safe read APIs; do not overload `unavailable` to mean quota failure.
3. Add controlled create/delete lifecycle probes only where read-only evidence is not enough and cleanup can be guaranteed.
4. Add the next read-only modality, likely App Service Linux rollout signals.
5. Add alert delivery once daily recent-change summaries are stable enough for subscriptions.
6. Move any remaining heavy dashboard detail sections to on-demand fetches if browser performance degrades again.

See [docs/poc-deployment.md](docs/poc-deployment.md) for the PoC deployment/runbook.
