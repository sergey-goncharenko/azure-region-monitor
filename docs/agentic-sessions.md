# Scheduled Agent Sessions

This repository has a lightweight scheduled workflow for bounded agentic maintenance. The workflow lives in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml) and runs daily at 07:00 UTC, which is fixed 09:00 EET.

## Sessions

The workflow starts at most two bounded tasks per day:

- Documentation and instructions maintenance: runs Azure-backed Codex from GitHub Actions, checks whether docs, runbooks, workflow notes, and [.github/copilot-instructions.md](../.github/copilot-instructions.md) still match the current codebase, recent commits, and recent GitHub Actions behavior, and opens a draft PR only when changes are needed.
- Parked unknowns investigation: reads the latest public snapshot, ranks `unknown` results by modality/check count, and asks GitHub Copilot cloud agent to investigate only the top modality.

The unknowns session is created as a GitHub issue assigned to `copilot-swe-agent[bot]` with an `agent_assignment`. Copilot should open one pull request when it finds a justified repository change. If there is no useful change, the prompt tells Copilot to comment on the issue and close it instead of opening an empty PR.

The docs task does not use a Copilot cloud-agent issue. It builds the prompt with [scripts/build_azure_codex_docs_prompt.py](../scripts/build_azure_codex_docs_prompt.py), runs `codex -p azure exec --full-auto`, validates the result, and opens a draft PR from the fixed `azure-codex/docs-alignment` branch when the working tree changed.

## Required Secrets And Variables

For the Azure Codex docs task, configure:

- Repository secret `AZURE_OPENAI_KEY`: API key for the Azure OpenAI / Foundry model deployment used by Codex.
- Repository variable `AZURE_OPENAI_ENDPOINT`: Azure OpenAI endpoint URL.
- Repository variable `AZURE_OPENAI_DEPLOYMENT`: deployment name for the model Codex should use.
- Optional repository variable `AZURE_OPENAI_API_VERSION`: API version. If omitted, the workflow uses `2025-04-01-preview`.

Use the manual [Provision Azure Codex OpenAI](../.github/workflows/provision-azure-codex-openai.yml) workflow to create or verify the Azure AI Services resource and model deployment. If you set `configure_repo_settings` to true, the workflow can also write `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`, and `AZURE_OPENAI_KEY` into repository settings. That mode requires a repository secret named `GH_REPO_SETTINGS_TOKEN` whose token can write Actions variables and secrets. The default `GITHUB_TOKEN` should not be treated as sufficient for repository secret administration.

The provisioning workflow uses the existing Azure OIDC secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`, and the Azure identity needs permission to register `Microsoft.CognitiveServices`, create the target resource group/resource, create model deployments, and read account keys. If you use `GH_REPO_SETTINGS_TOKEN`, grant the token only the minimum repository administration or Actions settings permissions needed to write repository variables and secrets, then rotate or remove it after bootstrapping.

The scheduled agent workflow uses the built-in `GITHUB_TOKEN` with `contents: write` and `pull-requests: write` to push the docs branch and open the draft PR.

For the Copilot unknowns task, configure a repository secret named `COPILOT_AGENT_TOKEN` that belongs to the account whose Copilot entitlement should be used. The GitHub Copilot agent APIs require a user token; the workflow `GITHUB_TOKEN` is not accepted for Copilot assignment.

For a fine-grained personal access token for the unknowns task, grant access to this repository and include:

- Metadata: read
- Actions: read and write
- Contents: read and write
- Issues: read and write
- Pull requests: read and write

The token holder must have a paid Copilot plan with Copilot cloud agent enabled for the repository.

## Cost Controls

- The docs task uses a fixed branch, `azure-codex/docs-alignment`, and skips when an open PR already exists for that branch unless `force` is set.
- The scheduler creates no more than one open unknowns task per session label. If an earlier unknowns issue is still open, the next scheduled run skips that session.
- The unknowns session is skipped when the loaded snapshot has no `unknown` statuses, unless the workflow is manually run with `force_unknowns_without_candidates`.
- Prompts target 30 minutes of focused work and tell the agent to stop before 45 minutes if the task is not converging. Copilot cloud agent also has GitHub's hard session limit for the unknowns lane.
- The unknowns prompt includes a precomputed top modality so the agent does not need to spend tokens reading the full snapshot just to choose a target.
- Manual runs can set `dry_run` to inspect the generated issues without starting Copilot sessions.

## Manual Run

1. Open Actions in GitHub.
2. Select `Scheduled agent sessions`.
3. Use `Run workflow`.
4. Keep `dry_run` enabled for the first check, then run again with `dry_run` disabled after verifying the generated prompts.

Use `force` only when you intentionally want another session while an earlier one is still open.