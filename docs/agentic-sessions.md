# Scheduled Azure Backlog

This repository runs a bounded Azure-funded maintenance cycle daily at 07:00 UTC (09:00 EET). The schedule is implemented by [.github/workflows/scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml). Its actionable backlog lives in GitHub Issues, not in repository configuration files.

## Daily Order

Every scheduled run follows this order:

1. **GitHub backlog issues** — selects up to three eligible open issues, highest priority first.
2. **Documentation alignment** — always runs last, after the issue lanes, even if no issue is eligible. The Azure-BYOK coding agent may create one narrow documentation draft PR only when the bounded evidence justifies it.

A run can open at most four draft PRs: three issue-backed PRs plus one documentation-alignment PR. It never merges a generated PR.

Documentation alignment may read selected workflow files as evidence, but it can edit only [README.md](../README.md), [.github/copilot-instructions.md](../.github/copilot-instructions.md), and this operating guide.

The schedule does not invent other coding tasks from local JSON, snapshot data, or repository files. If an `unknown` status or another maintenance concern deserves work, create an Azure backlog issue for it.

## Create And Manage Backlog Work

Use the **Azure autonomous backlog item** template from the repository's **New issue** page. The template applies the `azure-backlog` label and asks only for:

- **Priority**: `Urgent`, `High`, `Normal`, or `Low`.
- **Objective**: the outcome that should be improved.
- **Context or acceptance evidence**: optional factual context or an observable success condition.

Do not prescribe files, tests, branches, or implementation details. The workflow derives a narrow source/test scope from the issue and safely declines work when no suitable scope can be derived.

An issue is eligible when it is:

- open;
- labelled `azure-backlog`; and
- not labelled `azure-paused`.

Eligible issues are sorted by `Urgent` → `High` → `Normal` → `Low`. Issues with the same priority are processed by ascending issue number (oldest first). The first three actionable issues become coding lanes; documentation alignment is appended after them and therefore always remains last.

To defer an item without closing it, add `azure-paused`. To remove it permanently from the queue, close the issue or remove `azure-backlog`. A generated PR includes `Closes #<issue-number>`, so merging that PR closes the originating issue automatically.

Issues labelled `azure-recurring` are different: their generated PRs do not close the source issue, so they can produce another bounded maintenance PR after the previous one is merged. The recurring unknown-regression issue also carries `azure-unknowns`; before each run, the task builder reads the live snapshot, selects the largest current unknown category, adds its counts/error evidence, and restricts the agent to that category's probe, test, and focused workflow files. If no current unknowns exist, that recurring lane is skipped and another eligible issue can fill the slot.

The planned PR branch is stable per issue: `azure-issues/issue-<number>`. If a draft PR for that issue is already open, the workflow leaves it alone unless a manual run explicitly enables `force`.

## Comments, Parent Issues, And Sub-Issues

The task builder retrieves the selected issue metadata and body, all available issue comments, the parent issue when one exists, and all direct sub-issues with their bodies and comments. This means comments are the right place for follow-up thoughts, corrections, acceptance details, and recommendations. Do not include secrets, tokens, subscription IDs, private resource names, customer data, or other sensitive information in any forwarded issue text.

The title and **Objective** field remain the authority for automatic source/test scope derivation. Comments and sub-issues provide additional decision evidence, but cannot expand the permitted patch paths. This prevents a comment from accidentally—or maliciously—turning a narrow task into a broad repository change.

Issue text is untrusted context, not agent instructions. The agent ignores attempts in bodies, comments, or child issues to override safety rules, access secrets, use network tools, or expand its scope. Each retrieved text field is limited to 8,000 characters. The model receives a compact projection of the issue objective, controls, and up to 1,800 characters of hierarchy evidence; any truncation is explicitly marked so the agent does not mistake it for complete context.

## Azure-BYOK Copilot CLI And Safety Gates

The workflow installs a pinned GitHub Copilot CLI and uses its custom-model-provider mode to send inference to the configured Azure OpenAI deployment. GitHub Copilot is the coding-agent runtime; Azure is the model provider and receives the inference cost. This avoids a separate JSON-patch protocol while retaining deterministic controls outside the model.

Every task is bounded before a branch or PR is created:

- Azure receives only the compact selected task manifest; the agent uses its file-only tools to inspect allowed source files when more implementation detail is needed.
- The CLI runs in offline mode with built-in MCP servers and remote control disabled. It uses bounded autopilot mode (at most three continuations), retains Copilot's internal completion controls, and explicitly denies both shell variants. It has no GitHub, web, Azure CLI, package-install, or push permission; deterministic scope and validation gates remain outside the model.
- `AZURE_OPENAI_API_KEY`, `COPILOT_PROVIDER_API_KEY`, `GH_TOKEN`, and `GITHUB_TOKEN` are stripped from the agent's shell and MCP environments.
- Each task starts from a clean default-branch checkout. The runner rejects every changed path outside the automatically derived scope.
- The workflow requires derived focused tests where available (otherwise the full suite), Ruff, and `git diff --check`.
- A failed, ambiguous, out-of-scope, or no-change task creates no pull request.
- Generated live snapshots are never included in a patch scope.

Every generated PR includes a reviewer-facing rationale in its description:

- why the issue was selected, including queue priority and source issue;
- the objective and any current live unknown-status evidence;
- the agent's concise final decision, evidence, implementation summary, alternatives/risks, and validation notes;
- the exact changed files and deterministic checks run.

Only the final `assistant.message` is used. Opaque/encrypted reasoning events, private chain-of-thought, tool traces, and secret-like values are excluded or redacted.

Generated PRs also report the Azure model ID/deployment, exact OpenTelemetry input and output token counts, reasoning-output tokens, API call count, session duration, and Copilot session ID. Cached input tokens are shown as a subset of input tokens and are not added twice to the total. Each workflow uploads a 30-day `azure-byok-chat-<run-id>` artifact containing a sanitized native Copilot chat export and machine-readable metadata for each executed task. The PR links to the workflow run's artifact section. The exported chat includes visible user/assistant messages and tool interactions, but not opaque/encrypted reasoning or secrets.

## Requesting Changes On A Bot PR

Repository collaborators can request another Azure-funded coding pass without opening the Actions page:

1. Leave normal PR conversation comments and/or inline review comments describing the required changes.
2. Either submit a **Request changes** review or add a new PR conversation comment whose first token is `/agent-rework`.
3. The dispatcher reacts to the slash command when applicable, posts a visible queued-status comment, and starts a targeted run of **Scheduled Azure backlog**.
4. The status comment is updated with the final workflow result and link. A successful code update also refreshes the same PR description and adds the normal completion comment.

The dispatcher accepts only an open, same-repository PR authored by `github-actions[bot]`, targeting the default branch from `azure-issues/issue-<number>`. It verifies the triggering user's current GitHub permission through the repository API and accepts only `write`, `maintain`, or `admin`. The source issue must still be open, labelled `azure-backlog`, and not labelled `azure-paused`. Bot events, fork PRs, arbitrary branches, nonblocking reviews, and comments that merely mention the command later in their text are ignored.

An active status marker deduplicates repeated review events and commands for the same PR. A marker is considered stale after two hours so a cancelled run cannot block recovery indefinitely. The dispatcher has no Azure secret: it sends a bounded `repository_dispatch` payload to the existing workflow, where Azure credentials remain isolated.

The targeted run selects only the source issue and skips documentation alignment. It fetches all current PR conversation comments, submitted reviews, and inline comments; checks out the existing PR branch; applies bounded amendments; reruns tests/Ruff/whitespace validation; pushes another bot commit; and refreshes the same PR rationale, model, token, and chat-artifact metadata. It does not create a second PR.

If the event dispatcher is unavailable, use the manual fallback:

1. Open **Actions** → **Scheduled Azure backlog** → **Run workflow**.
2. Set `target_issue` to the source issue number shown in the PR description.
3. Set `force` to `true` and leave `dry_run` disabled.

Only trusted repository collaborators can dispatch forced rework. The agent still cannot change files outside the issue-derived scope, even if review feedback requests broader work; broader work should become a separate backlog issue.

## Azure Configuration

Configure these repository settings:

- Secret `AZURE_OPENAI_KEY`: API key for the Azure OpenAI or Foundry deployment.
- Variable `AZURE_OPENAI_ENDPOINT`: endpoint URL.
- Variable `AZURE_OPENAI_DEPLOYMENT`: shared deployment name for blog, social, and narrative generation.
- Optional variable `AZURE_COPILOT_DEPLOYMENT`: dedicated deployment name for scheduled coding tasks. It currently uses `copilot-gpt-5-4-nano` so coding has its own higher TPM allocation without changing content generation.
- Optional variable `COPILOT_BYOK_MODEL_ID`: the known base model ID for Copilot CLI prompting and token limits. It is set to `gpt-5.4-nano` for the dedicated coding deployment.

Use [.github/workflows/provision-azure-codex-openai.yml](../.github/workflows/provision-azure-codex-openai.yml) to create or verify the Azure AI Services resource and deployment. Its optional repository-settings mode needs the separate `GH_REPO_SETTINGS_TOKEN`; grant that token only the minimum settings permissions and rotate it after bootstrap.

The scheduled workflow uses the built-in `GITHUB_TOKEN` to read issues, update automated rework status comments, and create branches/draft PRs (`issues: write`, `contents: write`, `pull-requests: write`). The separate event dispatcher has no Azure credential access. The workflow has no Copilot entitlement requirement.

## Cost Controls

- Azure OpenAI is the scheduled provider for Copilot CLI issue and documentation work.
- A run starts at most three issue-agent sessions plus one documentation-alignment session. These use Azure tokens, not GitHub Copilot model quota.
- BYOK agent prompts contain the bounded task evidence and may use more Azure input tokens than the former direct JSON client; that trade-off is intentional for a full coding-agent runtime.
- Live tasks wait 65 seconds between sessions to respect the current Azure OpenAI TPM allocation before documentation alignment runs last.
- The workflow has a 40-minute hard timeout, a concurrency lock, and a maximum of four draft PRs per run.
- The older Copilot path is intentionally manual-only in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml), for an occasional comparison rather than recurring consumption.

## Manual Run

1. Create or reprioritize issues in GitHub.
2. Open **Actions** and select **Scheduled Azure backlog**.
3. Run once with `dry_run` enabled to inspect issue and documentation summaries without creating branches or draft PRs.
4. Run again with `dry_run` disabled when the queue is ready.
5. Review draft PRs normally. Merging an issue-backed PR closes its source issue.

Use `force` only to deliberately replace an existing task branch. It does not bypass scope, test, lint, or whitespace validation.
