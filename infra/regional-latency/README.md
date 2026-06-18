# Regional model latency infrastructure

This Bicep template provisions the Azure resources used by the `ai-model-latency-cli`
probe to measure **Azure OpenAI inference latency per region**.

## What it creates

For each region in `regions`:

- A Cognitive Services account (`kind: OpenAI`, SKU `S0`) **in that region**.
- A single-region **Standard** deployment of the configured model (default `gpt-4o`).
- A `Cognitive Services OpenAI User` role assignment for the probe identity (keyless
  data-plane access), when `probePrincipalId` is supplied.

Standard deployments are pay-per-token with **no idle/hourly cost**, and a single-region
(non-global) SKU is processed in the account's region — which is what makes the measured
latency attributable to that region.

## Why per-region accounts

An Azure OpenAI resource is regional, and its Standard (non-global) deployment is
processed in that resource's region. To compare regions you therefore need one account
per region. "Global Standard" deployments may be processed in any geography and are
**not** region-attributable, so they are intentionally not used here.

## Deploy

```powershell
az login
$rg = "azure-region-monitor-latency"
az group create --name $rg --location eastus

# Object ID of the identity the probe runs as (the GitHub OIDC app/managed identity).
$principalId = az ad sp show --id $env:AZURE_CLIENT_ID --query id -o tsv

az deployment group create `
  --resource-group $rg `
  --template-file infra/regional-latency/main.bicep `
  --parameters probePrincipalId=$principalId `
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
| `regions` | eastus, westus3, swedencentral, uksouth, australiaeast, japaneast | Regions with confirmed gpt-4o single-region Standard quota. |
| `modelName` | `gpt-4o` | Model deployed in every region. |
| `modelVersion` | `2024-11-20` | Model version. |
| `deploymentCapacity` | `10` | Standard capacity (thousands of TPM). Small is fine for probing. |
| `deploymentName` | `gpt-4o` | Deployment name the probe targets. |
| `probePrincipalId` | `''` | Object ID of the probe identity; role assignment is skipped if empty. |

## Teardown

```powershell
az group delete --name azure-region-monitor-latency --yes --no-wait
```
