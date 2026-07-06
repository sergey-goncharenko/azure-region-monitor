# Copilot Instructions

## Project Context

This repository builds the Azure Regional Feature Availability Monitor: a static public dashboard plus JSON APIs that show region-by-region Azure rollout evidence.

Current implemented modalities:

- AKS extension catalog: `aks-extension-catalog-cli`
- AKS Kubernetes versions: `aks-version-cli`
- Azure Functions Flex Consumption locations and Linux runtimes: `function-flex-cli`
- Azure AI model catalog: `ai-model-catalog-cli`
- Container Apps provider metadata: `container-apps-provider-cli`
- VM SKU regional size listings: `vm-sku-cli`
- GitHub Models global inference latency: `model-latency-cli`
- Azure per-region OpenAI inference latency: `ai-model-latency-cli`

The dashboard is deployed to Azure Static Web Apps. Focused modality workflows can merge fresh modality snapshots into the current live snapshot before deployment.

## Working Process

- Prefer read-only Azure catalog/listing probes before create/delete lifecycle probes.
- Keep probe semantics explicit in docs and UI. A status should say what evidence produced it, not imply stronger deployment guarantees than we have tested.
- When adding a modality, update all of these together: probe code, CLI registration, focused workflow, full workflow, snapshot merge categories, dashboard grouping, tests, README, and `docs/poc-deployment.md`.
- After dashboard generator changes, run focused static-site tests, full `pytest`, and Ruff.
- After workflow changes, push first, then run the focused workflow before deploying or expanding scope.
- For dashboard-only UI/docs changes, use `dashboard-redeploy.yml` instead of rerunning probes.
- Scheduled Copilot cloud-agent sessions are configured by `.github/workflows/scheduled-copilot-agents.yml` and documented in `docs/agentic-sessions.md`. Keep those prompts bounded: one PR per session, no Azure create/delete probes, and no manual edits to generated live snapshot data.

## Status Semantics

- `available`: the probe got positive read-only evidence, such as a listed extension type, runtime, version, location, or VM size.
- `unavailable`: the probe completed successfully, but the feature was absent from the catalog/list used by that probe.
- `unknown`: the probe did not get trustworthy evidence because the Azure CLI command failed, timed out, returned invalid JSON, or hit a provider/control-plane issue.
- `partial`: reserved for multi-condition checks; current catalog probes rarely emit it.

Do not describe `unavailable` as a quota failure unless a dedicated quota or create/delete probe produced that evidence.

For Azure Functions Flex Consumption, `unavailable` means the region was not returned by `az functionapp list-flexconsumption-locations --output json`. The Azure CLI help describes that command as listing available locations for running function apps on Flex Consumption. Absence from that list is regional listing evidence, not proof of quota exhaustion or deployment failure.

For Azure AI models, `unavailable` means `az cognitiveservices model list --location <region> --output json` did not list the model/version in that regional model catalog, or the regional `locations/models` endpoint reported the region is outside its supported locations. It is not quota, account approval, deployment, content filtering, or inference evidence.

For Container Apps, `unavailable` means Microsoft.App provider metadata was retrieved but the configured resource type did not advertise the region in its `locations` list. It is not a quota, capacity, Dapr runtime, or deployment result.

## Dashboard Lessons

- Do not cap data to make the page smaller. The project preference is full fidelity with paging, filters, and lazy rendering.
- Keep heavy raw checks in `api/latest.json`; the main page should show grouped summaries.
- Large AKS extension groups should stay available but lazy-load secondary tables so Chrome does less initial DOM/layout work.
- Preserve static history during deployments by fetching/carrying forward `api/history` before rebuilding the site.

## Azure Functions Lessons

- Default Functions runtime coverage should come from Python config, not duplicated workflow defaults.
- The current Functions runtime list tracks every versioned Linux runtime listed by Azure CLI and excludes the unversioned `custom` runtime entry.
- Runtime rows are tied to the Flex location signal. If Flex Consumption is not listed in a region, runtime rows are marked unavailable for that region because there is no Flex hosting target in the current read-only evidence.