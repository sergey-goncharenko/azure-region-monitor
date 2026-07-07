# Public Alpha Release Checklist

## Goal

Release Azure Region Monitor as a public alpha: useful enough to inspect and reuse, while clearly communicating evidence limits and protecting operator metadata.

## Release Scope

The alpha includes these read-only modalities:

- AKS extension catalog
- AKS Kubernetes versions
- Azure Functions Flex Consumption locations and Linux runtimes
- Azure AI model catalog listings
- Container Apps provider metadata
- VM SKU regional listings
- GitHub Models global inference latency
- Azure per-region OpenAI inference latency

## Pre-Release Checks

- Repository contains no committed secrets, deployment tokens, private keys, `.env` files, or generated credentials.
- Repository contains no tenant IDs, subscription IDs, managed identity object IDs, private resource group names, or private operator notes.
- GitHub workflow files reference secrets only through `${{ secrets.* }}` and do not echo secret values.
- Public dashboard and JSON APIs contain only Azure region, service, feature, status, message, and timestamp data.
- Methodology page explains that read-only catalog evidence is not a deployment, quota, capacity, policy, or inference guarantee.
- Full test suite and Ruff pass.
- Focused workflows and the full workflow are green after the release candidate commit.

## Release Steps

1. Run the repository and public-site audit.
2. Run `pytest` and `python -m ruff check src tests`.
3. Run the full synthetic workflow and verify the deployed dashboard.
4. Tag the release as `v0.1.0-alpha`.
5. Publish release notes that call out status semantics and known limits.
6. Make the repository public after the release candidate is verified.

## Known Alpha Limits

- `available` means the feature was listed or matched by the probe for that region.
- `unavailable` means the probe completed successfully but the feature was absent from the probe's evidence source.
- `unknown` means the monitor did not get trustworthy evidence.
- The alpha does not prove deployment success, quota availability, regional capacity, policy access, account approval, content filtering, or runtime invocation success.