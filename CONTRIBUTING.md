# Contributing

Thanks for helping improve Azure Region Monitor.

## Project Principles

- Prefer read-only Azure catalog and listing probes before lifecycle create/delete probes.
- Keep probe semantics explicit. A status should say what evidence produced it.
- Do not overstate `available` or `unavailable`; read-only evidence is not a deployment guarantee.
- Keep dashboard output full fidelity. Use paging, filtering, grouping, and lazy loading instead of capping data.

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install ".[dev]"
pytest
python -m ruff check src tests
```

## Adding a Modality

When adding a modality, update these together:

- Probe code and tests
- CLI registration
- Focused workflow and full workflow
- Snapshot merge category
- Dashboard grouping and methodology text
- README and relevant docs

## Security and Privacy

- Do not commit secrets, deployment tokens, tenant IDs, subscription IDs, resource group names, object IDs, or private operator notes.
- Use GitHub Actions secrets for Azure OIDC identifiers and Static Web Apps deployment tokens.
- Do not include private customer, subscription, tenant, or account data in sample snapshots.

## Pull Requests

Before opening a PR, run:

```powershell
pytest
python -m ruff check src tests
```

For dashboard generator changes, also build the static site locally:

```powershell
azure-region-monitor build-static --output public
```