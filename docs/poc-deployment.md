# PoC Deployment Runbook

## Goal

The PoC proves that synthetic checks can produce structured, region-by-region Azure availability evidence. The current implementation uses read-only Azure CLI catalog/listing probes for AKS extension types, AKS Kubernetes versions, Azure Functions Flex Consumption locations and runtimes, Azure AI model catalog listings, Container Apps provider resource type locations, and VM SKU regional size listings.

## Current PoC Shape

- Current probes: `aks-extension-catalog-cli`, `aks-version-cli`, `function-flex-cli`, `ai-model-catalog-cli`, `container-apps-provider-cli`, and `vm-sku-cli`
- Original PoC regions: `westeurope`, `swedencentral`, `eastus`
- Default workflow regions: blank workflow input, which falls back to the Python `DEFAULT_REGIONS` list
- Default full run scope: Azure physical locations returned by Azure CLI, including recommended and other public cloud locations
- Legacy curated AKS extension defaults for `aks-extension-cli`:
  - `extensions.gitops=microsoft.flux`
  - `extensions.monitor=microsoft.azuremonitor.containers`
- Default AKS Kubernetes version prefixes:
  - `1.32`
  - `1.33`
  - `1.34`
  - `1.35`
- Default VM SKU workflow mode: `all` listed VM SKUs per region
- Default Container Apps resource type checks:
  - `containerApps.managedEnvironments=managedEnvironments`
  - `containerApps.apps=containerApps`
  - `containerApps.jobs=jobs`
  - `containerApps.daprComponents=managedEnvironments/daprComponents`
  - `containerApps.connectedEnvironments=connectedEnvironments`
- Default Azure AI model checks: all models returned by `az cognitiveservices model list --location <region> --output json`
- Output snapshot: `data/snapshots/latest.json`
- Output diff: `data/diffs/latest.json`
- Full dashboard automation: `.github/workflows/synthetic-tests.yml`
- Full dashboard schedule: daily at 03:17 UTC
- Manual modality test workflows:
  - `.github/workflows/aks-extension-tests.yml`
  - `.github/workflows/aks-version-tests.yml`
  - `.github/workflows/function-flex-tests.yml`
  - `.github/workflows/ai-model-tests.yml`
  - `.github/workflows/container-apps-tests.yml`
  - `.github/workflows/vm-sku-tests.yml`
- Shared runner workflow: `.github/workflows/regional-probe-run.yml`
- Static host: Azure Static Web Apps
- Current hostname: `azwatch.operator.lat`
- Azure Static Web Apps fallback hostname: `gray-island-09dc9e703.7.azurestaticapps.net`
- Methodology page: `https://azwatch.operator.lat/methodology.html`

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install ".[dev]"
az login
az extension add --name k8s-extension --upgrade
azure-region-monitor run --probe aks-extension-cli --output data/snapshots/latest.json
azure-region-monitor diff data/snapshots/2026-05-07.json data/snapshots/latest.json --output data/diffs/latest.json
```

Run the full read-only regional probe set locally:

```powershell
azure-region-monitor run --probe aks-extension-catalog-cli --probe aks-version-cli --probe function-flex-cli --probe ai-model-catalog-cli --probe container-apps-provider-cli --probe vm-sku-cli --output data/snapshots/latest.json
```

To override regions:

```powershell
azure-region-monitor run --probe aks-extension-cli --region westeurope --region swedencentral --region eastus --output data/snapshots/latest.json
```

To override extension mappings:

```powershell
$env:AKS_EXTENSION_FEATURES="extensions.gitops=microsoft.flux,extensions.monitor=microsoft.azuremonitor.containers"
azure-region-monitor run --probe aks-extension-cli --output data/snapshots/latest.json
```

To override AKS Kubernetes version prefixes:

```powershell
$env:AKS_KUBERNETES_VERSION_PREFIXES="1.32,1.33,1.34,1.35"
azure-region-monitor run --probe aks-version-cli --output data/snapshots/latest.json
```

To override VM SKUs:

```powershell
$env:AZURE_VM_SKUS="Standard_B2s,Standard_D2s_v5,Standard_D2as_v5,Standard_E2s_v5"
azure-region-monitor run --probe vm-sku-cli --output data/snapshots/latest.json
```

To override Azure Functions runtime checks:

```powershell
$env:FUNCTION_RUNTIME_FEATURES="runtimes.python.3.12=PYTHON|3.12,runtimes.node.22=NODE|22"
azure-region-monitor run --probe function-flex-cli --output data/snapshots/latest.json
```

The default Functions runtime set tracks every versioned Linux runtime listed by Azure CLI and excludes the unversioned custom runtime entry.

## Feature and Group Refresh Behavior

Some modality items are discovered during every full scan, and some are configured intentionally:

- AKS extension catalog, Azure AI model catalog, and VM SKU probes discover their feature items from the regional Azure catalogs/lists. Full and VM-focused workflows pass `AZURE_VM_SKUS=all`, so VM SKU rows cover every listed size returned by `az vm list-sizes`. The full run unions discovered items and fills absent items as `unavailable` where the catalog probe succeeded.
- Azure Functions runtime rows, Container Apps resource type rows, and AKS Kubernetes version-prefix rows come from Python configuration or workflow inputs.
- Dashboard groups are derived from feature names during static-site generation. New extension publishers, model families, runtime families, and VM SKU families appear automatically when those feature names appear in the latest snapshot.

To run or override Azure AI model catalog checks:

```powershell
$env:AI_MODEL_FEATURES="all"
azure-region-monitor run --probe ai-model-catalog-cli --output data/snapshots/latest.json
```

For selected models, use comma-separated `feature=model@version` pairs:

```powershell
$env:AI_MODEL_FEATURES="aiModels.openai.gpt-4o.2024-08-06=gpt-4o@2024-08-06"
azure-region-monitor run --probe ai-model-catalog-cli --output data/snapshots/latest.json
```

To override Container Apps resource type checks:

```powershell
$env:CONTAINER_APPS_RESOURCE_FEATURES="containerApps.apps=containerApps,containerApps.daprComponents=managedEnvironments/daprComponents"
azure-region-monitor run --probe container-apps-provider-cli --output data/snapshots/latest.json
```

## GitHub Actions Setup

Create a Microsoft Entra application or managed identity that can authenticate from GitHub Actions with OIDC. The workflow expects these repository secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

The workflow only needs read-style Azure CLI access for this first probe. Do not add client secrets; use federated credentials for GitHub OIDC.

The Azure Static Web Apps deployment step expects this repository secret:

- `AZURE_STATIC_WEB_APPS_API_TOKEN`

When scripting the federated credential subject in PowerShell, use `${repo}` before `:ref`:

```powershell
"repo:${repo}:ref:refs/heads/main"
```

Using `$repo:ref` makes PowerShell treat `repo` as a scoped variable name and creates the wrong subject.

Run the workflow manually first:

1. Open Actions in GitHub.
2. Select `Synthetic regional tests`.
3. Use `Run workflow` when you want to run all current modalities and deploy the dashboard.
4. Optionally enter comma-separated regions.
5. Optionally enter comma-separated AKS Kubernetes minor version prefixes.
6. Optionally enter comma-separated VM SKUs.
7. Optionally enter a previous snapshot path, such as `data/snapshots/2026-05-08.json`, only when you intentionally want to compare against that checked-in file.
8. Download the `azure-region-monitor-synthetic-data` artifact.

For a faster modality-specific run, select one of the focused workflows instead:

- `AKS extension regional tests` runs `aks-extension-catalog-cli`.
- `AKS Kubernetes version regional tests` runs `aks-version-cli` only.
- `Azure Functions Flex regional tests` runs `function-flex-cli` only.
- `Azure AI model regional tests` runs `ai-model-catalog-cli` only.
- `Container Apps regional tests` runs `container-apps-provider-cli` only.
- `VM SKU regional tests` runs `vm-sku-cli` only.

Focused workflows upload modality-specific artifacts and do not deploy the public dashboard by default. When `deploy_dashboard` is enabled, focused deployments merge the fresh modality snapshot into the current live dashboard snapshot before publishing, so other modality sections remain visible.

The reusable runner caps each Azure CLI probe command with `AZURE_CLI_TIMEOUT_SECONDS`. The reusable default is 45 seconds; the full synthetic workflow currently defaults to 120 seconds. Slow calls are recorded as `unknown` in the snapshot instead of blocking the dashboard refresh.

## Status Semantics

Current probes are read-only listing probes. They provide rollout evidence, not a complete deployment guarantee.

- `available`: Azure listed the feature in the command output used by the probe.
- `unavailable`: the command completed successfully, but the feature was absent from the output.
- `unknown`: the command failed, timed out, returned invalid JSON, or did not provide trustworthy evidence.
- `partial`: reserved for future probes with multiple required sub-checks.

For Azure Functions Flex Consumption, `unavailable` means `az functionapp list-flexconsumption-locations --output json` did not return the region. The CLI help says this command lists available locations for running function apps on Flex Consumption. It does not test subscription quota, regional capacity, policy, provider registration, or a real create/deploy path.

For Azure AI models, `unavailable` means `az cognitiveservices model list --location <region> --output json` did not list the model/version in the regional model catalog, or the regional `locations/models` endpoint reported that the region is outside its supported locations. It does not test quota, provisioned throughput, content filtering, account approval, deployment creation, or inference success.

For Container Apps, `unavailable` means `az provider show --namespace Microsoft.App --expand resourceTypes/locations --output json` completed successfully, but the configured Microsoft.App resource type did not advertise the region in its `locations` metadata. It does not test a real Container Apps environment or app deployment, Dapr runtime behavior, quota, capacity, policy, or provider registration for the subscription.

## Success Criteria

The PoC is successful when a run produces:

- a valid snapshot for at least 3 regions;
- clear `available`, `unavailable`, or `unknown` statuses for each checked feature;
- captured error codes/messages when Azure CLI cannot determine availability;
- at least one confirmed regional difference, or enough evidence to choose a more discriminating modality or lifecycle probe.

## Next Decision

If the read-only AKS extension and Kubernetes version probes do not expose a real regional difference, the next probe should use a controlled create/enable/delete lifecycle against a temporary test cluster in each region. That is more expensive and slower, so it should wait until the low-cost probes have been tried.