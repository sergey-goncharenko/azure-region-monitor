# Scheduled Azure Backlog

This repository runs a bounded Azure-funded maintenance cycle daily at 07:00 UTC (09:00 EET). The schedule is implemented by [.github/workflows/scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml). Its actionable backlog lives in GitHub Issues, not in repository configuration files.

## Daily Order

Every scheduled run follows this order:

1. **GitHub backlog issues** — selects up to two eligible open issues, highest priority first.
2. **Documentation alignment** — always runs last, after the issue lanes, even if no issue is eligible. It may create one narrow documentation draft PR only when its bounded review confirms drift.

A run can open at most three draft PRs: two issue-backed PRs plus one documentation-alignment PR. It never merges a generated PR.

The schedule does not invent other coding tasks from local JSON, snapshot data, or repository files. If an `unknown` status or another maintenance concern deserves work, create an Azure backlog issue for it.

## Create And Manage Backlog Work

Use the **Azure autonomous backlog item** template from the repository's **New issue** page. The template applies the `azure-backlog` label and asks only for:

- **Priority**: `High`, `Normal`, or `Low`.
- **Objective**: the outcome that should be improved.
- **Context or acceptance evidence**: optional factual context or an observable success condition.

Do not prescribe files, tests, branches, or implementation details. The workflow derives a narrow source/test scope from the issue and safely declines work when no suitable scope can be derived.

An issue is eligible when it is:

- open;
- labelled `azure-backlog`; and
- not labelled `azure-paused`.

To defer an item without closing it, add `azure-paused`. To remove it permanently from the queue, close the issue or remove `azure-backlog`. A generated PR includes `Closes #<issue-number>`, so merging that PR closes the originating issue automatically.

The planned PR branch is stable per issue: `azure-issues/issue-<number>`. If a draft PR for that issue is already open, the workflow leaves it alone unless a manual run explicitly enables `force`.

## Safety Gates

Every proposal is bounded before a branch or PR is created:

- Azure receives only the issue objective and curated local repository excerpts.
- The proposal parser rejects malformed output, oversized diffs, and changes outside the automatically derived scope.
- Each proposal starts from a clean default-branch checkout.
- The workflow requires `git apply --check`, derived focused tests where available (otherwise the full suite), Ruff, and `git diff --check`.
- A failed, ambiguous, or out-of-scope proposal creates no pull request.
- Generated live snapshots are never included in a patch scope.

## Azure Configuration

Configure these repository settings:

- Secret `AZURE_OPENAI_KEY`: API key for the Azure OpenAI or Foundry deployment.
- Variable `AZURE_OPENAI_ENDPOINT`: endpoint URL.
- Variable `AZURE_OPENAI_DEPLOYMENT`: deployment name.
- Optional variable `AZURE_OPENAI_API_VERSION`: API version; the client defaults to `2025-04-01-preview`.

Use [.github/workflows/provision-azure-codex-openai.yml](../.github/workflows/provision-azure-codex-openai.yml) to create or verify the Azure AI Services resource and deployment. Its optional repository-settings mode needs the separate `GH_REPO_SETTINGS_TOKEN`; grant that token only the minimum settings permissions and rotate it after bootstrap.

The scheduled workflow uses the built-in `GITHUB_TOKEN` to read issues and create branches/draft PRs (`issues: read`, `contents: write`, `pull-requests: write`). It has no Copilot entitlement requirement.

## Cost Controls

- Azure OpenAI is the scheduled default for issue and documentation work.
- A run makes at most two issue proposal calls, one documentation review call, and one documentation patch call only when drift is confirmed.
- The workflow has a 25-minute hard timeout, a concurrency lock, and a maximum of three draft PRs per run.
- The older Copilot path is intentionally manual-only in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml), for an occasional comparison rather than recurring consumption.

## Manual Run

1. Create or reprioritize issues in GitHub.
2. Open **Actions** and select **Scheduled Azure backlog**.
3. Run once with `dry_run` enabled to inspect issue and documentation summaries without creating branches or draft PRs.
4. Run again with `dry_run` disabled when the queue is ready.
5. Review draft PRs normally. Merging an issue-backed PR closes its source issue.

Use `force` only to deliberately replace an existing proposal branch. It does not bypass patch, test, lint, or whitespace validation.
