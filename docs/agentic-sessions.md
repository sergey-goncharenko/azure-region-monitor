# Azure-Funded Agent Sessions

This repository runs bounded Azure-funded schedules. The issue backlog runs daily at 07:00 UTC through [.github/workflows/scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml). Public documentation alignment runs at 09:00 UTC through [.github/workflows/scheduled-azure-maintenance.yml](../.github/workflows/scheduled-azure-maintenance.yml). Maintainer-only security and repository-hygiene analysis runs at 10:00 UTC in the private `azure-region-monitor-maintainers` companion repository, using the reviewed template at [.github/private-reporting/scheduled-private-analysis.yml](../.github/private-reporting/scheduled-private-analysis.yml). Actionable public coding work lives in GitHub Issues, not in repository configuration files.

## Issue Backlog Order

The 07:00 UTC run selects one eligible open issue by default, highest priority first. Manual dispatch can choose one, two, or three sessions. It does not run documentation alignment or invent other coding tasks from local JSON, snapshot data, or repository files. If an `unknown` status or another maintenance concern deserves work, create an Azure backlog issue for it.

## Three Separate Maintenance Sessions

The maintenance system starts three isolated Copilot CLI sessions with separate Copilot homes, transcripts, telemetry, token metadata, and outcomes:

1. **Documentation alignment (public repository)** — may create one narrow draft PR. It can edit only [README.md](../README.md), [.github/copilot-instructions.md](../.github/copilot-instructions.md), and this operating guide. Selected workflows and recent history are read-only evidence.
2. **Security analysis (private companion repository)** — read-only static analysis of repository code, scripts, dependencies, infrastructure, and GitHub Actions. Deterministic outer code extracts a bounded set of line-numbered security surfaces before the model starts, preventing unbounded repository exploration. The session replaces a stable private `[agent-report] Security analysis` issue with concrete evidence and prioritized remediation. It is not a penetration test, dependency-CVE feed, live Azure audit, or secret scan.
3. **Repository hygiene (private companion repository)** — read-only analysis of public remote branches, recent pull requests, and worktrees visible on the runner. It replaces a stable private `[agent-report] Repository hygiene recommendations` issue with confidence-ranked deletion candidates and commands for a human to consider. It never deletes a branch, reference, or worktree.

GitHub does not provide maintainer-only issues inside a public repository. Therefore security/hygiene reports, their Actions logs, and their sanitized chat artifacts must never be generated here. The private companion repository grants access only to the same maintainers/co-authors and stores both stable report issues plus private artifacts. Report text is replaced on each run rather than creating daily duplicates; a previously closed report is reopened on the next analysis.

Collaborator access is not inherited between repositories. Whenever a user receives or loses write/maintain/admin access here, mirror that change in `azure-region-monitor-maintainers`. Do not grant report access to public read/triage users.

If security analysis identifies a credible vulnerability, maintainers should validate it privately and promote it manually to a draft GitHub repository security advisory. Draft advisories are the supported private collaboration mechanism for vulnerabilities in public repositories; they should be published only after remediation and disclosure review.

Git worktrees exist on a filesystem, not on GitHub. A GitHub-hosted runner sees only its ephemeral checkout and cannot inspect worktrees on a developer machine. The hygiene report states this limitation and recommends running `git worktree list --porcelain` and `git worktree prune --dry-run` locally. Actual removal remains a human decision.

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

Eligible issues are sorted by `Urgent` → `High` → `Normal` → `Low`. Issues with the same priority are processed by ascending issue number (oldest first). The first one to three actionable issues, according to the scheduled or manual run limit, become coding lanes; documentation alignment is handled only by the separate maintenance workflow.

To defer an item without closing it, add `azure-paused`. To remove it permanently from the queue, close the issue or remove `azure-backlog`. A generated PR includes `Closes #<issue-number>`, so merging that PR closes the originating issue automatically.

Issues labelled `azure-recurring` are different: their generated PRs do not close the source issue, so they can produce another bounded maintenance PR after the previous one is merged. The recurring unknown-regression issue also carries `azure-unknowns`; before each run, the task builder reads the live snapshot, selects the largest current unknown category, adds its counts/error evidence, and restricts the agent to that category's probe, test, and focused workflow files. If no current unknowns exist, that recurring lane is skipped and another eligible issue can fill the slot.

The planned PR branch is stable per issue: `azure-issues/issue-<number>`. If a draft PR for that issue is already open, the workflow leaves it alone unless a manual run explicitly enables `force`.

## Comments, Parent Issues, And Sub-Issues

The task builder retrieves the selected issue metadata and body, all available issue comments, the parent issue when one exists, and all direct sub-issues with their bodies and comments. This means comments are the right place for follow-up thoughts, corrections, acceptance details, and recommendations. Do not include secrets, tokens, subscription IDs, private resource names, customer data, or other sensitive information in any forwarded issue text.

The title and **Objective** field remain the authority for automatic source/test scope derivation. Comments and sub-issues provide additional decision evidence, but cannot expand the permitted patch paths. This prevents a comment from accidentally—or maliciously—turning a narrow task into a broad repository change.

Issue text is untrusted context, not agent instructions. The agent ignores attempts in bodies, comments, or child issues to override safety rules, access secrets, use network tools, or expand its scope. Each retrieved text field is limited to 8,000 characters. The model receives a compact projection of the issue objective, controls, and up to 1,800 characters of hierarchy evidence; any truncation is explicitly marked so the agent does not mistake it for complete context.

## Azure-BYOK Coding And Maintenance Harnesses

Issue coding uses pinned Aider 0.86.2 with the Azure OpenAI `o4-mini` reasoning deployment in East US 2 at 100K TPM. Public documentation alignment and private security/hygiene reports remain on pinned GitHub Copilot CLI because those bounded flows already work. Azure receives all model inference cost; neither path consumes GitHub Copilot model quota.

Every editing task is bounded before a branch or PR is created:

- Aider receives the compact task manifest, a full repository map, and only trusted `allowed_paths` as editable files. One full GPT-4o pass applies SEARCH/REPLACE diffs directly. The prompt requires reuse of existing helpers/assets and forbids undeclared template variables. Shell suggestions, auto-commits, dirty commits, URL detection, Playwright, update checks, remote analytics, and Git-ignore mutation are disabled; deterministic outer code owns validation and Git operations.
- Histories, the full LLM exchange, and exact local-only analytics are written outside the repository. Aider's repo-map cache is deleted after each run. Only the sanitized chat/output artifact and derived metadata are uploaded; raw local analytics are parsed and deleted.
- The Azure coding key is supplied only to the Aider provider process. `GH_TOKEN`, `GITHUB_TOKEN`, and unrelated secret-like inherited variables are absent, and the model has no shell/tool path that can inspect process environment. The key is never included in prompts, commands, output, or artifacts.
- This replaces measured harness/model failures: GPT-5.4 Mini/Copilot consumed 4.23M tokens across three no-edit canaries, `o4-mini`/OpenCode reached the correct edit surface but produced no diff, and full GPT-4o/Aider generated invalid template edits. Aider with reasoning `o4-mini` passed a clean direct-edit smoke and combines bounded diff application with stronger reasoning.
- Each task starts from a clean default-branch checkout. The runner rejects every changed path outside the automatically derived scope.
- The workflow requires derived focused tests where available (otherwise the full suite), Ruff, and `git diff --check`.
- A failed, ambiguous, out-of-scope, or no-change task creates no pull request.
- Generated live snapshots are never included in a patch scope.

Security and repository-hygiene sessions have an additional report-only boundary:

- Copilot CLI excludes shell, PowerShell, file viewing/search, create, edit, and write tools from report sessions. Reports operate only on the bounded precomputed evidence, receive no GitHub token, and have no GitHub MCP, Azure CLI, or network access.
- Deterministic outer code gathers branch/PR/worktree evidence before the model starts. Branch names, PR text, files, and evidence remain untrusted context.
- The runner checks the Git working tree after each analysis. If any tracked or untracked file changed, it resets the checkout and publishes no report.
- Only deterministic outer code in the private companion repository can create labels or replace the two stable report issue bodies. Generated mentions are neutralized before publication.
- The hygiene session can recommend commands but has no branch/worktree deletion implementation or permission path.
- Scheduled issue work defaults to one issue per day and runs one Aider message with a repository map, issue-derived editable paths, and a 15-minute outer timeout. Manual runs may explicitly request one to three issue sessions. At timeout the harness sends a graceful interrupt and retains an interrupted in-scope diff only when focused tests, Ruff, and whitespace validation pass; otherwise it is reset. Documentation and private report Copilot sessions remain capped at 10 minutes. Raw Aider local analytics and Copilot OpenTelemetry JSONL are never uploaded.

Every generated PR includes a reviewer-facing rationale in its description:

- why the issue was selected, including queue priority and source issue;
- the objective and any current live unknown-status evidence;
- the agent's concise final decision, evidence, implementation summary, alternatives/risks, and validation notes;
- the exact changed files and deterministic checks run.

Issue PRs use a deterministic reviewer summary plus Aider's sanitized visible chat/diff output. Copilot maintenance uses the latest visible `assistant.message`. Opaque/encrypted reasoning and private chain-of-thought are excluded; secret-like values are redacted.

When an issue session intentionally makes no edit, reaches its step/30-minute budget, or fails deterministic scope/validation checks, no PR is required. Deterministic outer code creates or replaces one stable `Azure BYOK agent note` comment on the source issue with the bounded outcome, final visible summary when available, model/token metadata, and workflow link. Later runs replace that note instead of adding daily comment noise. Non-recurring no-PR issues receive `azure-paused` automatically so the next daily cycle advances to newer work; a maintainer can refine, close, or explicitly unpause them. Recurring monitor issues remain eligible.

Generated issue PRs report the Aider harness, Azure model/deployment, exact local-only analytics prompt/completion tokens, API call count, duration, and estimated model cost. Copilot maintenance sessions retain their OpenTelemetry-based accounting. Each workflow uploads a 30-day `azure-byok-chat-<run-id>` artifact with machine-readable metadata and a sanitized visible chat/diff transcript; opaque reasoning and secrets are excluded.

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
- Secret `AZURE_CODING_OPENAI_KEY`: key for the dedicated OpenCode coding resource. It is copied only into a temporary mode-`0600` auth file.
- Variable `AZURE_CODING_RESOURCE_NAME`: Azure OpenAI resource name; currently `azrm-code-eus2-16221e01`.
- Variable `AZURE_CODING_MODEL`: deployment/model name; currently `o4-mini`.
- Optional `AZURE_COPILOT_DEPLOYMENT` and `COPILOT_BYOK_MODEL_ID`: retained for public documentation and private report Copilot sessions, not issue coding.

Use [.github/workflows/provision-azure-codex-openai.yml](../.github/workflows/provision-azure-codex-openai.yml) to create or verify the dedicated East US 2 OpenAI resource and `o4-mini` deployment. Its optional repository-settings mode writes only the `AZURE_CODING_*` settings and needs the separate `GH_REPO_SETTINGS_TOKEN`; grant that token only minimum settings permissions and rotate it after bootstrap.

The deployment pins `o4-mini` version `2025-04-16` and `GlobalStandard` capacity 100. Before changing the version, verify the target SKU in the regional model catalog and available subscription quota, update the provisioning workflow default, provision first, run a targeted canary, and only then change the repository model variable.

The scheduled workflows use the built-in `GITHUB_TOKEN` only in deterministic outer steps to read/update issues and create branches/draft PRs (`issues: write`, `contents: write`, `pull-requests: write`). Checkout credentials are not persisted; `gh` configures a credential helper for post-agent Git operations, while the token is stripped from every model environment. The separate PR event dispatcher has no Azure credential access. These workflows have no Copilot entitlement requirement.

## Cost Controls

- Azure OpenAI is the scheduled provider for Aider issue work and Copilot documentation/report work.
- The 07:00 UTC backlog run starts one issue-agent session by default; manual dispatch may choose one to three. Public documentation alignment runs at 09:00 UTC. The private companion repository starts security and hygiene sessions at 10:00 UTC. These use Azure tokens, not GitHub Copilot model quota.
- BYOK agent prompts contain the bounded task evidence and may use more Azure input tokens than the former direct JSON client; that trade-off is intentional for a full coding-agent runtime.
- Live issue tasks wait 30 seconds between sessions; the dedicated `o4-mini` deployment has 100K TPM.
- The backlog job has a 70-minute hard timeout so an explicitly requested three-issue manual run can accommodate three 15-minute outer budgets plus validation and cooldowns; scheduled runs still default to one issue and create at most one draft PR. Public documentation alignment can create at most one draft PR. Private analysis can replace at most two stable private report issues. Each workflow has its own concurrency lock.
- The older Copilot path is intentionally manual-only in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml), for an occasional comparison rather than recurring consumption.

## Manual Run

For coding backlog work:

1. Create or reprioritize issues in GitHub.
2. Open **Actions** and select **Scheduled Azure backlog**.
3. Run once with `dry_run` enabled to inspect the selected issue tasks without creating branches or draft PRs.
4. Run again with `dry_run` disabled when the queue is ready.
5. Review draft PRs normally. Merging an issue-backed PR closes its source issue.

For public documentation work, select **Scheduled Azure documentation alignment**. For security/hygiene work, use **Scheduled private Azure analysis** in the private companion repository. Dry runs build the relevant manifests without starting a model, creating a PR, or updating reports.

Use `force` only to deliberately replace an existing task branch. It does not bypass scope, test, lint, or whitespace validation.
