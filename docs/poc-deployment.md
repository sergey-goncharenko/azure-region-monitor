# PoC Deployment Runbook

## Goal

The PoC proves that synthetic checks can produce structured, region-by-region Azure availability evidence. The first real check uses Azure CLI to list AKS extension types by location and records whether configured extension types appear in each target region.

## Current PoC Shape

- Probe: `aks-extension-cli`
- Default regions: `westeurope`, `swedencentral`, `eastus`
- Default features:
  - `extensions.gitops=microsoft.flux`
  - `extensions.monitor=microsoft.azuremonitor.containers`
- Output snapshot: `data/snapshots/latest.json`
- Output diff: `data/diffs/latest.json`
- Automation: `.github/workflows/synthetic-tests.yml`

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

To override regions:

```powershell
azure-region-monitor run --probe aks-extension-cli --region westeurope --region swedencentral --region eastus --output data/snapshots/latest.json
```

To override extension mappings:

```powershell
$env:AKS_EXTENSION_FEATURES="extensions.gitops=microsoft.flux,extensions.monitor=microsoft.azuremonitor.containers"
azure-region-monitor run --probe aks-extension-cli --output data/snapshots/latest.json
```

## GitHub Actions Setup

Create a Microsoft Entra application or managed identity that can authenticate from GitHub Actions with OIDC. The workflow expects these repository secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

The workflow only needs read-style Azure CLI access for this first probe. Do not add client secrets; use federated credentials for GitHub OIDC.

When scripting the federated credential subject in PowerShell, use `${repo}` before `:ref`:

```powershell
"repo:${repo}:ref:refs/heads/main"
```

Using `$repo:ref` makes PowerShell treat `repo` as a scoped variable name and creates the wrong subject.

Run the workflow manually first:

1. Open Actions in GitHub.
2. Select `Synthetic regional tests`.
3. Use `Run workflow`.
4. Optionally enter comma-separated regions.
5. Optionally enter a previous snapshot path, such as `data/snapshots/2026-05-08.json`, only when you intentionally want to compare against that checked-in file.
6. Download the `azure-region-monitor-synthetic-data` artifact.

## Success Criteria

The PoC is successful when a run produces:

- a valid snapshot for at least 3 regions;
- clear `available`, `unavailable`, or `unknown` statuses for each configured AKS extension feature;
- captured error codes/messages when Azure CLI cannot determine availability;
- at least one confirmed regional difference, or enough evidence to choose a more discriminating AKS feature probe.

## Next Decision

If this AKS extension type listing does not expose a real regional difference, the next probe should use a controlled create/enable/delete lifecycle against a temporary test cluster in each region. That is more expensive and slower, so it should wait until the low-cost list probe has been tried.