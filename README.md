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
- Data can be incomplete or temporarily wrong while the monitor is in public alpha.
- Region coverage means the configured Azure public cloud region list used by the monitor; it does not claim sovereign clouds, private previews, every possible API version, or hidden capacity cells.
- The project does not publish tenant IDs, subscription IDs, private resource names, credentials, or customer data.
- Alerts, signed webhooks, and SDKs are future roadmap items.
- Durable Blob-backed history publication is available as an opt-in operator rollout; it is not enabled merely by installing this code.

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
- An Azure OpenAI per-region inference latency probe (`ai-model-latency-cli`); the former GitHub Models global latency probe was retired with that service on 2026-07-30, and its history is kept as archived evidence
- JSON snapshot and diff storage helpers
- Daily static snapshot history and compact recent-change summaries
- A human-readable methodology page explaining what each status means
- A diff engine that classifies new availability and regressions
- A FastAPI read-only API matching the initial API spec
- A GitHub Actions workflow for manual or scheduled PoC runs, plus [weekly and source-triggered documentation augmentation](docs/agentic-sessions.md#documentation-augmentation) for evolving reader needs, terminology, and use cases; edits stay within `README.md`, `.github/copilot-instructions.md`, and `docs/agentic-sessions.md` and require a stated reader benefit with supporting evidence
- A generated static dashboard and JSON endpoint for Azure Static Web Apps
- Shared publication byte/file budgets, pre-deployment recovery artifacts, and an optional complete Blob archive with compatible historical evidence URLs; see [publication and recovery operations](docs/poc-deployment.md#publication-budgets-recovery-and-optional-blob-archive)
- Tests for the diff engine and API behavior

## Scope Discovery

The full scheduled workflow (`.github/workflows/daily-scan.yml`) runs daily and discovers the region set at run time from `az account list-locations` (every physical region), so brand-new Azure regions are covered automatically. If discovery is unavailable it falls back to the Python `DEFAULT_REGIONS` list, which tracks Azure physical locations returned by Azure CLI. In alpha, treat this as the monitor's configured Azure public cloud scope, not a contractual statement that every Azure location, sovereign cloud, private preview region, or hidden capacity cell is represented.

Feature items are mixed by design:

- AKS extension catalog, Azure AI model catalog, and VM SKU runs discover the listed feature universe from each full scan and normalize missing discovered items to `unavailable` in regions where the listing probe succeeded. Full and VM-focused workflows pass `AZURE_VM_SKUS=all`, so VM SKU rows cover sizes returned by regional legacy `az vm list-sizes --location <region>` calls, supplemented by supported `az vm list-skus --location <region> --resource-type virtualMachines --all` evidence when the legacy listing fails or is suspiciously small.
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

GitHub retired GitHub Models on 2026-07-30, so the former `model-latency-cli` probe, its `model-latency-tests.yml` workflow, and the daily-scan job were removed. `merge-snapshot` drops retired modalities (see `src/azure_region_monitor/retired_modalities.py`) from the published live snapshot, so their last `unknown` results do not linger as current evidence. Retained history and `latency-history.json` keep the archived GitHub Models measurements, and the latency page shows them only as a labelled, retired section.

The dashboard and latest daily post lead with a deterministic **At a glance** briefing derived from complete snapshot comparisons, not generated prose. It separates distinct features from feature-region listings, names affected regions, and distinguishes new gains, delistings, restorations, catalog observation gaps, measurement-only latency gaps, tracked continuing absences, and monitoring-scope changes. Green ▲ marks listings in regions where the feature was not listed before, teal ↩ marks listings that returned after being missing in the previous scan (shown in a collapsed group and counted separately in the headline, because a return is not a new rollout), red ▼ marks lost listings, and grey/amber gap indicators mark observation limits; measurement-only latency gaps are shown but do not drive the headline. Region and service filters narrow grouped cards, with full evidence, filters, and history collapsed below the glance view. Snapshot timestamps describe the comparison, not per-probe freshness or workload health. Missing baselines and gaps between scan dates are explicit.

The stored daily narrative and review-only social drafts still use the configured Azure OpenAI Responses deployment by default. They are not prerequisites for the reader briefing. This keeps recurring writing workloads on the Azure subscription rather than consuming GitHub Copilot or GitHub Models allowance. Set `AI_SUMMARY_ENABLED=0` or `AI_SOCIAL_ENABLED=0` to use deterministic narrative fallbacks. When generated text is rejected, `narrative_fallback_reason` records `unsupported_generation:<check>` for the failed validation check. There is no GitHub Models fallback; if Azure OpenAI is unavailable, the deterministic fallback is published.

Quality target: a reader should identify the main change, affected regions, and evidence limits within 15 seconds. Offline scenarios check factual answers and rendering; they do not substitute for a timed human comprehension check.

Feature explanations distinguish documented exact specifications, family/category context, and unverified identifiers. Known VM sizes include CPU/RAM and storage/network differentiators, and size names can be decoded from Microsoft Learn naming conventions when a catalog-specific page is not available. Extensions, runtimes, models, and Container Apps resource types have product-specific context and read-more links. During history updates, `LEARN_LOOKUP_ENABLED=1` enables deterministic Microsoft Learn MCP lookup for digest features; results are relevance-gated, cached in history, and fail open so a lookup problem does not block publication. Documentation explains the capability, not the cause of a regional change. Unknown products remain visible with an explicit limitation and an official lookup link.

The [reader-improvement plan](docs/reader-improvement.md) starts with maintainer-only qualitative feedback: **What was unclear? What would have helped?** Page feedback and `/feedback.html` prepare a GitHub draft with page/date/view, filters, viewport, and scroll context. Optional current-tab screenshots require picker consent, PNG review, then manual copy/download and attachment. No backend/token, analytics, autopost, or upload is added. Issues/attachments are public; pasting on GitHub uploads before final Submit. Founder feedback is not unbiased reader measurement. The optional later study is `/reading-check.html` or `/reading-check/YYYY-MM-DD.html`, with local timing/JSON export and a reviewable GitHub draft.

Run the Azure per-region model latency probe (real Azure regional latency, requires the regional deployments from `infra/regional-latency`):

```powershell
$env:AI_LATENCY_TARGETS = (az deployment group show -g azure-region-monitor-latency -n regional-latency --query "properties.outputs.targets.value" -o json)
$env:AZURE_OPENAI_TOKEN = (az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)
azure-region-monitor run --probe ai-model-latency-cli --region eastus --region westus3 --region swedencentral --output data/snapshots/latest.json
```

This probe targets a single-region Standard Azure OpenAI deployment per region, so the latency is attributable to each Azure region. See `infra/regional-latency/README.md` for setup and cost.

Run the read-only Container Apps provider metadata probe locally:

```powershell
azure-region-monitor run --probe container-apps-provider-cli --output data/snapshots/latest.json
```

By default, the Container Apps probe checks Microsoft.App provider metadata for managed environments, apps, jobs, Dapr components, and connected environments.

Default regions now cover the full set of Azure public cloud physical locations returned by Azure CLI. The current `DEFAULT_REGIONS` list in `config.py` includes 70+ regions across all Azure geographies. Run with `--region` flags to restrict to a smaller set during local testing.

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

Set `AZURE_VM_SKUS=all` to track every SKU returned by the regional VM SKU listing probe, including supported `az vm list-skus` fallback evidence when the legacy listing is not trustworthy:

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
- `unknown`: the monitor did not get trustworthy evidence, usually because the Azure CLI command failed, timed out, returned invalid JSON, or hit a provider/control-plane issue. It is not an availability verdict; it means the monitor could not trust the probe result.
- `partial`: reserved for future multi-condition probes where only some required sub-checks pass.

For Azure Functions Flex Consumption, `unavailable` means the region was absent from `az functionapp list-flexconsumption-locations --output json`. Azure CLI describes that command as listing available locations for running function apps on the Flex Consumption plan. Absence from that list is not a quota result; quota, regional capacity, policy, provider registration, and create-time failures require separate signals.

For Azure AI models, `available` means `az cognitiveservices model list --location <region> --output json` listed that model/version in the region. `unavailable` means the model/version was absent from the region's model catalog, or the regional `locations/models` endpoint reported that the region is outside its supported locations. This is catalog evidence; it does not test quota, provisioned throughput, content filtering, account approval, or a deployment invocation.

For Container Apps, `available` means `az provider show --namespace Microsoft.App --expand resourceTypes/locations --output json` advertised the configured Microsoft.App resource type in that region. `unavailable` means the provider metadata call succeeded but did not advertise that resource type for that region; it is not a deployment, quota, or Dapr runtime version test.

Archived GitHub Models latency rows (`modelLatency.*`, vantage `github-global`, retired 2026-07-30) used the same meanings: `available` was a trustworthy timed response and `unknown` meant every sample failed. They measured one global endpoint, not an Azure region, and are no longer collected.

For Azure model latency (the `ai-latency` modality), `available` means a timed Azure OpenAI inference call succeeded for that region; `unknown` means every sample failed. This modality is keyed by real Azure regions, because each measured deployment is a single-region Standard Azure OpenAI deployment processed in that region. The latency is therefore attributable to the region, though it still includes network distance from the probe runner's vantage. It does not emit `unavailable`, and it is not an SLA or throughput guarantee.

## Next Engineering Steps

1. Drive down the unknown percentage by investigating repeated failure reasons, tuning retries/timeouts, improving CLI error classification, and adding provider-specific fallback probes.
2. Review the live Azure AI model catalog results and tune dashboard grouping if model volume makes scanning awkward.
3. Add quota/capacity-specific probes where Azure exposes safe read APIs; do not overload `unavailable` to mean quota failure.
4. Add controlled create/delete lifecycle probes only where read-only evidence is not enough and cleanup can be guaranteed.
5. Add the next read-only modality, likely App Service Linux rollout signals.
6. Add alert delivery once daily recent-change summaries are stable enough for subscriptions.
7. Move any remaining heavy dashboard detail sections to on-demand fetches if browser performance degrades again.

See [docs/poc-deployment.md](docs/poc-deployment.md) for the PoC deployment/runbook.
