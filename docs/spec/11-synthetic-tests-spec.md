# Synthetic Tests Specification

## Current Read-only Tests

The current production workflow prioritizes low-cost read-only evidence. These checks query Azure control-plane listings and do not create resources.

## AKS Extension Catalog Tests
- Command: `az k8s-extension extension-types list-by-location`
- `available`: extension type is listed in the region.
- `unavailable`: command succeeded but the extension type is absent from that region's catalog, or the `locations/extensionTypes` endpoint reports the region is outside its supported locations.
- `unknown`: command failed, timed out, or returned invalid JSON.

## AKS Kubernetes Version Tests
- Command: `az aks get-versions --location <region>`
- `available`: a listed version matches the configured minor-version prefix.
- `unavailable`: command succeeded but no listed version matched the prefix.
- `unknown`: command failed, timed out, or returned invalid JSON.

## Functions Tests
- Command: `az functionapp list-flexconsumption-locations --output json`
- Command: `az functionapp list-runtimes --os linux --output json`
- `available` for `hostingPlans.flexConsumption`: region is listed as an available Flex Consumption location.
- `unavailable` for `hostingPlans.flexConsumption`: command succeeded but the region is absent from the Flex Consumption location list.
- Runtime rows are available when Flex is listed for the region and the runtime is listed in the Linux runtime catalog.
- Runtime rows are unavailable when Flex is absent for the region or the runtime is absent from the Linux runtime catalog.
- This does not test quota, regional capacity, policy, provider registration, or a real deployment.

## VM SKU Tests
- Primary command: `az vm list-sizes --location <region>`
- Supplemental fallback: `az vm list-skus --location <region> --resource-type virtualMachines --all` may add read-only listing evidence when the legacy command fails or returns a suspiciously small catalog.
- `available`: SKU is listed in the region.
- `unavailable`: command succeeded but SKU is absent from the region list.
- `unknown`: command failed, timed out, or returned invalid JSON.

## Container Apps Provider Metadata Tests
- Command: `az provider show --namespace Microsoft.App --expand resourceTypes/locations --output json`
- Default resource types: `managedEnvironments`, `containerApps`, `jobs`, `managedEnvironments/daprComponents`, and `connectedEnvironments`.
- `available`: the Microsoft.App resource type advertises the region in provider metadata.
- `unavailable`: provider metadata was retrieved, but the resource type did not advertise that region.
- `unknown`: command failed, timed out, or returned invalid JSON.
- This does not create a Container Apps environment or test quota, regional capacity, Dapr runtime behavior, policy, provider registration, or deployment success.

## Azure AI Model Catalog Tests
- Command: `az cognitiveservices model list --location <region> --output json`
- Default scope: all model/version records returned by the regional catalog command.
- `available`: model/version is listed in the region's model catalog.
- `unavailable`: command succeeded but the model/version is absent from that region's catalog, or the `locations/models` endpoint reports the region is outside its supported locations.
- `unknown`: command failed, timed out, or returned invalid JSON.
- This does not test quota, provisioned throughput, content filtering, account approval, deployment creation, or inference success.

## GitHub Models Global Inference Latency Tests

- Probe: `model-latency-cli`
- Vantage: `github-global` (GitHub Models' single global endpoint; not an Azure region)
- Default scope: curated and auto-discovered GitHub Models catalog (OpenAI text chat models plus non-OpenAI anchors)
- `available`: at least one timed inference call returned a trustworthy response; `latency_ms` is the p50 round-trip; p95, time-to-first-token, and tokens/sec are in the message.
- `unknown`: every sample failed, timed out, or returned no tokens.
- This probe never emits `unavailable`. Latency depends on the network path from the probe runner to GitHub's endpoint and is not an Azure regional availability or SLA signal.

## Azure Per-Region OpenAI Inference Latency Tests

- Probe: `ai-model-latency-cli`
- Vantage: one Azure region per measured deployment (Standard Azure OpenAI deployment from `infra/regional-latency`)
- Default scope: per-region Azure OpenAI Standard deployments created by the `infra/regional-latency` Bicep template
- `available`: a timed Azure OpenAI inference call succeeded for that region; `latency_ms` is the p50 round-trip.
- `unknown`: every sample failed.
- Unlike the GitHub Models modality, latency is attributable to the Azure region because each deployment is a single-region Standard deployment. It still includes network distance from the probe runner and is not an SLA or throughput guarantee.
- This probe is not part of the daily `daily-scan.yml` run because it requires the `infra/regional-latency` infrastructure to be deployed. Run it with the focused `azure-latency-tests.yml` workflow.

## Future Lifecycle Tests

Lifecycle tests should be added only when the read-only signal is not enough. These tests cost more and need cleanup safeguards.

## AKS Lifecycle Tests
- Create cluster
- Enable extension
- Capture error codes

## Container Apps Lifecycle Tests
- Deploy app
- Enable Dapr
- Test logs

## OpenAI Tests
- List models. Implemented as the Azure AI model catalog probe.
- Invoke model
- Check quotas
