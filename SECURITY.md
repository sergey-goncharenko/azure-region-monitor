# Security Policy

## Supported Versions

The public alpha tracks the `main` branch. Tagged releases are snapshots of the current alpha state.

## Reporting a Vulnerability

Please report suspected vulnerabilities through GitHub Security Advisories when available. If advisories are not available for your fork or clone, open a GitHub issue with a minimal, non-sensitive description and avoid posting secrets, tenant IDs, subscription IDs, tokens, or private resource names.

Automated security findings and repository-hygiene reports are stored only in the private maintainer companion repository. They must not be copied into public issues, Actions logs, or artifacts. Maintainers validate credible vulnerabilities privately and promote them to a draft repository security advisory before coordinated disclosure.

## Data Handling

Azure Region Monitor is designed to publish public, read-only Azure catalog and listing evidence. Public snapshots should not contain credentials, customer data, tenant IDs, subscription IDs, object IDs, private resource names, or private deployment logs.

GitHub Actions should use OIDC and repository secrets for Azure authentication. Client secrets and Static Web Apps deployment tokens must never be committed.