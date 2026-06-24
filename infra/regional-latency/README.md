# Regional model latency infrastructure

This Bicep template provisions the Azure resources used by the `ai-model-latency-cli`
probe to measure **Azure OpenAI inference latency per region**.

## What it creates

For the union of all regions any model targets:

- A Cognitive Services account (`kind: OpenAI`, SKU `S0`) **in that region**.
- A single-region **Standard** deployment of each configured model in the regions that
  model supports.
- Optionally, a per-account `Cognitive Services OpenAI User` role assignment for the
  probe identity when `probePrincipalId` is supplied (skipped in CI — see Permissions).

Standard deployments are pay-per-token with **no idle/hourly cost**, and a single-region
(non-global) SKU is processed in the account's region — which is what makes the measured
latency attributable to that region.

## Why per-region accounts

An Azure OpenAI resource is regional, and its Standard (non-global) deployment is
processed in that resource's region. To compare regions you therefore need one account
per region. "Global Standard" deployments may be processed in any geography and are
**not** region-attributable, so they are intentionally not used here.

## Automatic model & region discovery (CI)

The `Azure model latency tests` workflow keeps the deployed set current without manual
edits. On each run it:

1. Lists the model catalog (`az cognitiveservices model list`) for a broad set of
   candidate regions (read-only).
2. Selects OpenAI chat models that offer a single-region **Standard** SKU (the only
   region-attributable kind) via `azure_model_discovery.select_regional_standard_models`,
   one newest version per model, capped by `max_models`.
3. Writes a Bicep `models` parameter file and runs an **idempotent incremental**
   deployment, then probes every deployment found in the resource group.

New models (for example `gpt-5.1`) and newly enabled regions therefore surface
automatically. The step is best-effort (`continue-on-error`), so a deployment hiccup
still lets the probe run against existing deployments.

## Permissions

The single GitHub OIDC principal needs two role assignments **at the resource-group
scope** (granted once, out of band):

- **Contributor** — create/update the per-region accounts and Standard deployments.
- **Cognitive Services OpenAI User** — keyless data-plane inference for the probe. At
  RG scope this is inherited by every account, including ones created later, so the
  template does **not** create per-account role assignments in CI (that would require
  `Microsoft.Authorization/roleAssignments/write`, beyond Contributor).

```powershell
$rg = "azure-region-monitor-latency"
$scope = "/subscriptions/<sub-id>/resourceGroups/$rg"
$oid = az ad sp show --id $env:AZURE_CLIENT_ID --query id -o tsv
az role assignment create --assignee-object-id $oid --assignee-principal-type ServicePrincipal --role "Contributor" --scope $scope
az role assignment create --assignee-object-id $oid --assignee-principal-type ServicePrincipal --role "Cognitive Services OpenAI User" --scope $scope
```

## Deploy

```powershell
az login
$rg = "azure-region-monitor-latency"
az group create --name $rg --location eastus

# Uses the in-template default models, or pass a discovered params file.
az deployment group create `
  --resource-group $rg `
  --template-file infra/regional-latency/main.bicep `
  --query "properties.outputs.targets.value" -o json
```

The `targets` output is the JSON the probe consumes via `AI_LATENCY_TARGETS`:

```json
[
  { "region": "eastus", "endpoint": "https://azwatch-lat-eastus-xxxx.openai.azure.com/", "deployment": "gpt-4o", "model": "gpt-4o" }
]
```

## Run the probe locally

```powershell
$env:AI_LATENCY_TARGETS = (az deployment group show -g $rg -n main --query "properties.outputs.targets.value" -o json)
$env:AZURE_OPENAI_TOKEN = (az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)
$regionArgs = (($env:AI_LATENCY_TARGETS | ConvertFrom-Json) | ForEach-Object { "--region", $_.region })
azure-region-monitor run --probe ai-model-latency-cli @regionArgs --output data/snapshots/latest.json
```

## Cost

- Idle: $0 (Standard has no hourly charge).
- Tokens: a tiny prompt x a few samples x N regions per day is a few cents/month.
- Comfortably inside a Visual Studio subscription monthly Azure credit; the spending
  limit hard-stops resources if the credit is exhausted.

## Parameters

| Parameter | Default | Notes |
| --- | --- | --- |
| `models` | gpt-4o (6 regions) + gpt-5.1 (3 regions) | Array of `{ name, version, deploymentName, regions[] }`. CI overrides this with the discovered set. Accounts are created for the union of all model regions. |
| `deploymentCapacity` | `10` | Standard capacity (thousands of TPM). Small is fine for probing. |
| `probePrincipalId` | `''` | Object ID of the probe identity; per-account role assignments are skipped if empty (the default in CI, which relies on the RG-scoped grant). |

## Teardown

```powershell
az group delete --name azure-region-monitor-latency --yes --no-wait
```
