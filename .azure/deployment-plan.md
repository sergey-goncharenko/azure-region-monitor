# Azure Deployment Plan

Status: Completed

## Goal

Publish the generated Azure Region Monitor public alpha dashboard with no
committed Azure operator metadata.

## Target Architecture

- GitHub Actions runs focused and full read-only regional probes.
- The workflow builds `public/` with dashboard pages and static JSON APIs.
- Azure Static Web Apps hosts the generated static dashboard.
- A Static Web Apps deployment token is stored in GitHub Actions secrets.

## Public Endpoint

- Dashboard hostname: `gray-island-09dc9e703.7.azurestaticapps.net`
- SKU: Free

Do not commit tenant IDs, subscription IDs, resource group names, managed
identity object IDs, deployment tokens, or private operator notes to this
repository. Keep environment-specific deployment details in Azure, GitHub
Actions secrets, or private operational notes.

## Deployment Steps

1. Build static dashboard locally and in CI.
2. Configure Azure resources outside the repository.
3. Store Azure OIDC values and the Static Web Apps deployment token as GitHub Actions secrets.
4. Trigger the relevant focused workflow or the full synthetic workflow.
5. Verify the hosted dashboard, JSON APIs, and methodology page.

## Security Notes

- No client secrets are committed.
- Azure OIDC values and deployment tokens remain GitHub Actions secrets.
- Dashboard output contains public Azure availability evidence only.