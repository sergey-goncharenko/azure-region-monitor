# Scheduled Azure Backlog

This repository runs a bounded Azure-funded maintenance cycle daily at 07:00 UTC (09:00 EET). The schedule is implemented by [.github/workflows/scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml). It is designed to turn a small prioritized backlog into safe draft pull requests without requiring a maintainer to specify tests or file allowlists.

## Daily Order

The cycle always processes work in this order:

1. **Current unknown-status evidence** — if the published snapshot has a meaningful `unknown` candidate, Azure proposes one evidence-backed maintenance patch.
2. **Ready backlog work** — Azure proposes the highest-priority ready items that fit the remaining coding slots.
3. **Documentation alignment** — Azure reviews bounded local documentation and instruction evidence after the coding lanes. If it confirms drift, Azure may propose one narrow documentation PR.

The default configuration permits at most two coding proposals before documentation alignment, so a run can open at most three draft PRs. A lane that lacks evidence produces a no-change result and does not consume a PR.

## Manage The Backlog

Manage [config/azure_agent_backlog.json](../config/azure_agent_backlog.json). Each item needs only:

- `status`: `ready`, `paused`, or `deprioritized`.
- `priority`: higher values are selected first.
- `title`: a short outcome-oriented name.
- `objective`: a concise description of the desired improvement.

Example:

```json
{
  "id": "improve-social-drafts",
  "status": "ready",
  "priority": 100,
  "title": "Improve social draft usefulness",
  "objective": "Make generated social drafts more factual and actionable for regional availability changes."
}
```

Set an item to `ready` to opt it into the next eligible run. Set it to `paused` to preserve it without scheduling work, or `deprioritized` to retain it below active priorities. The scheduler automatically derives a narrow candidate source/test scope from objective terms and rejects a task when it cannot derive a safe scope. Do not add paths, tests, model prompts, or implementation instructions to backlog entries.

`max_items_per_run` controls the maximum number of coding lanes (one unknowns lane plus ready backlog items), and is capped at two so documentation alignment remains the third activity.

## Safety Gates

Every proposed patch is bounded before a branch or PR is created:

- Azure receives only curated repository excerpts and the relevant live evidence.
- The proposal parser rejects malformed output, oversized diffs, and changes outside the derived scope.
- Each proposal starts from a clean default-branch checkout on a stable `azure-unknowns/`, `azure-goals/`, or `azure-docs/` branch.
- The workflow requires `git apply --check`, derived focused tests where available, Ruff, and `git diff --check`.
- A failed or ambiguous proposal creates no pull request. An existing open PR for the same stable branch is left alone unless a manual run explicitly sets `force`.
- Generated live snapshots are never part of an allowed patch scope.

The workflow opens **draft** PRs only. It never merges a generated change.

## Azure Configuration

Configure these repository settings:

- Secret `AZURE_OPENAI_KEY`: API key for the Azure OpenAI or Foundry deployment.
- Variable `AZURE_OPENAI_ENDPOINT`: endpoint URL.
- Variable `AZURE_OPENAI_DEPLOYMENT`: deployment name.
- Optional variable `AZURE_OPENAI_API_VERSION`: API version; the client defaults to `2025-04-01-preview`.

Use [.github/workflows/provision-azure-codex-openai.yml](../.github/workflows/provision-azure-codex-openai.yml) to create or verify the Azure AI Services resource and deployment. Its optional repository-settings mode needs the separate `GH_REPO_SETTINGS_TOKEN`; grant that token only the minimum settings permissions and rotate it after bootstrap.

The scheduled workflow uses the built-in `GITHUB_TOKEN` only for branches and draft PRs (`contents: write`, `pull-requests: write`). It has no Copilot entitlement requirement.

## Cost Controls

- Azure OpenAI is the scheduled default for unknowns, backlog, and documentation work.
- Each run makes only the calls needed for its bounded lanes: one unknowns proposal, zero to two ready backlog proposals, and a documentation review plus a patch call only when drift is confirmed.
- The workflow has a 25-minute hard timeout, a concurrency lock, and a maximum of three draft PRs per run.
- The old Copilot path is intentionally manual-only in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml), for an occasional unknowns comparison rather than recurring consumption.

## Manual Run

1. Open **Actions** and select **Scheduled Azure backlog**.
2. Run once with `dry_run` enabled to inspect the Azure summaries without creating branches or draft PRs.
3. Run again with `dry_run` disabled when the configuration is ready.
4. Review any draft PRs normally; update the backlog item status or priority when priorities change.

Use `force` only to deliberately replace an existing proposal branch. It does not bypass patch, test, lint, or whitespace validation.
