# Scheduled Copilot Agent Sessions

This repository has a lightweight scheduled workflow that starts bounded GitHub Copilot cloud-agent sessions. The workflow lives in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml) and runs daily at 07:00 UTC, which is fixed 09:00 EET.

## Sessions

The workflow starts at most two sessions per day:

- Documentation and instructions maintenance: checks whether docs, runbooks, workflow notes, and [.github/copilot-instructions.md](../.github/copilot-instructions.md) still match the current codebase, recent commits, and recent GitHub Actions behavior.
- Parked unknowns investigation: reads the latest public snapshot, ranks `unknown` results by modality/check count, and asks Copilot to investigate only the top modality.

Both sessions are created as GitHub issues assigned to `copilot-swe-agent[bot]` with an `agent_assignment`. Copilot should open one pull request when it finds a justified repository change. If there is no useful change, the prompt tells Copilot to comment on the issue and close it instead of opening an empty PR.

## Required Secret

Create a repository secret named `COPILOT_AGENT_TOKEN` that belongs to the `sergey-goncharenko` account. The GitHub Copilot agent APIs require a user token; the workflow `GITHUB_TOKEN` is not accepted for Copilot assignment.

For a fine-grained personal access token, grant access to this repository and include:

- Metadata: read
- Actions: read and write
- Contents: read and write
- Issues: read and write
- Pull requests: read and write

The token holder must have a paid Copilot plan with Copilot cloud agent enabled for the repository.

## Cost Controls

- The scheduler creates no more than one open task per session label. If an earlier docs or unknowns issue is still open, the next scheduled run skips that session.
- The unknowns session is skipped when the loaded snapshot has no `unknown` statuses, unless the workflow is manually run with `force_unknowns_without_candidates`.
- Prompts target 30 minutes of focused work and tell Copilot to stop before 45 minutes if the task is not converging. Copilot cloud agent also has GitHub's hard session limit.
- The unknowns prompt includes a precomputed top modality so the agent does not need to spend tokens reading the full snapshot just to choose a target.
- Manual runs can set `dry_run` to inspect the generated issues without starting Copilot sessions.

## Manual Run

1. Open Actions in GitHub.
2. Select `Scheduled Copilot agent sessions`.
3. Use `Run workflow`.
4. Keep `dry_run` enabled for the first check, then run again with `dry_run` disabled after verifying the generated prompts.

Use `force` only when you intentionally want another session while an earlier one is still open.