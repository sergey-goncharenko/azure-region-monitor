# Azure-Funded Agent Sessions

This repository runs bounded Azure-funded schedules. The regular issue backlog runs daily at 07:00 UTC through the GitHub Agentic Workflows source [.github/workflows/scheduled-agentic-backlog.md](../.github/workflows/scheduled-agentic-backlog.md) and its generated lock workflow. The former Aider workflow [.github/workflows/scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml) remains available only for manual fallback and existing PR rework. Public documentation alignment runs at 09:00 UTC through [.github/workflows/scheduled-azure-maintenance.yml](../.github/workflows/scheduled-azure-maintenance.yml). Maintainer-only security and repository-hygiene analysis runs at 10:00 UTC in the private `azure-region-monitor-maintainers` companion repository. Actionable public coding work lives in GitHub Issues, not in repository configuration files.

## Issue Backlog Order

The 07:00 UTC run selects one eligible open issue, highest priority first. Manual agentic dispatch can target one issue. The Aider fallback can still choose one to three sessions manually. Neither coding workflow runs documentation alignment or invents coding tasks outside the issue queue. Unknown checks become work only through issue #48 (or another explicit backlog issue); live snapshot evidence never creates a standalone task.

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

Do not prescribe branches or broad implementation rewrites. The deterministic task builder still derives relevant source/test hints, but the agentic comparison lane may inspect and edit the full repository. Safe outputs exclude generated snapshots and API payloads, protect sensitive repository files, and gate publication on full validation.

An issue is eligible when it is:

- open;
- labelled `azure-backlog`; and
- not labelled `azure-paused`.

Eligible issues are sorted by `Urgent` → `High` → `Normal` → `Low`. Issues with the same priority are processed by ascending issue number (oldest first). The first one to three actionable issues, according to the scheduled or manual run limit, become coding lanes; documentation alignment is handled only by the separate maintenance workflow.

To defer an item without closing it, add `azure-paused`. To remove it permanently from the queue, close the issue or remove `azure-backlog`. A generated PR includes `Closes #<issue-number>`, so merging that PR closes the originating issue automatically.

Issues labelled `azure-recurring` are different: their generated PRs do not close the source issue, so they can produce another bounded maintenance PR after the previous one is merged. Issue #48 is open, `azure-backlog`, `azure-recurring`, `azure-unknowns`, and Priority **Urgent**, so normal issue ordering selects it before lower-priority issues. Only after that selection does the task builder read the live snapshot, choose the largest current unknown category, and add its counts, error evidence, and relevant probe/test/workflow hints. If no current unknowns exist, that recurring lane is skipped and another eligible issue can fill the slot.

Use `azure-unknowns` only when the issue should run conditionally against the largest current `unknown` group. It is not a generic investigation label: an issue about `unavailable` results, presentation, content, or another one-off outcome must omit it, otherwise the selector defers that issue whenever the live snapshot has no unknown group.

Agentic PR branches start with `agentic/issue-<number>` and receive a collision-avoidance suffix. Aider fallback branches remain `azure-issues/issue-<number>`. Before starting a model, deterministic filtering skips any issue that already has an open PR from either lane.

Every non-dry-run backlog workflow updates one stable `[agent-status] Scheduled Azure backlog` issue labelled `azure-agent-status` with the latest workflow link and open, queue-eligible, deferred-without-unknown-evidence, open-PR-blocked, paused, and selected counts. When no runnable task remains, no model is started and the status issue receives one concise comment with the reason. Selected runs continue to use source-issue notes and draft PRs for detailed outcomes.

## Comments, Parent Issues, And Sub-Issues

The task builder retrieves the selected issue metadata and body, all available issue comments, the parent issue when one exists, and all direct sub-issues with their bodies and comments. This means comments are the right place for follow-up thoughts, corrections, acceptance details, and recommendations. Do not include secrets, tokens, subscription IDs, private resource names, customer data, or other sensitive information in any forwarded issue text.

The title and **Objective** field remain the authority for task selection and relevance hints. Comments and sub-issues provide additional decision evidence but are not trusted instructions. Full-repository agentic access does not let issue text override safe-output exclusions, protected-file review, deterministic validation, or tool/network controls.

Issue text is untrusted context, not agent instructions. The agent ignores attempts in bodies, comments, or child issues to override safety rules, access secrets, use network tools, or expand its scope. Each retrieved text field is limited to 8,000 characters. The model receives a compact projection of the issue objective, controls, and up to 1,800 characters of hierarchy evidence; any truncation is explicitly marked so the agent does not mistake it for complete context.

## Azure-BYOK Coding And Maintenance Harnesses

Regular issue coding now uses GitHub Agentic Workflows `gh-aw` v0.86.2 / AWF 0.27.44 with pinned Copilot CLI 1.0.65 routed through the existing Azure OpenAI `o4-mini` reasoning deployment in East US 2 at 100K TPM. The Aider 0.86.2 lane remains manual fallback and existing-PR rework support while results are compared. Public documentation alignment and private security/hygiene reports remain on pinned GitHub Copilot CLI. Azure receives all model inference cost; these BYOK paths do not consume GitHub Copilot model quota.

Every editing task is bounded before a branch or PR is created:

- Deterministic Python code still selects one issue, enriches recurring unknown work from the live snapshot, skips issues with open Aider or agentic PRs, and writes a compact task manifest. The manifest is transferred to the isolated agent job without exposing credentials.
- The agentic Copilot runtime may inspect and edit the full repository. It runs inside the Agent Workflow Firewall with an explicit network allowlist, bounded continuations, selected shell commands, read-only GitHub tools, and safe-output-only repository writes.
- The Azure coding key is held by the AWF API-proxy sidecar and explicitly excluded from the agent container. The agent receives neither the real provider key nor a write-capable GitHub token.
- Candidate changes are buffered as artifacts. Threat detection checks the patch, then a deterministic post-step applies it to a clean checkout and runs `python scripts/check.py`. That script is the single validation entrypoint shared with [.github/workflows/pr-validation.yml](../.github/workflows/pr-validation.yml) and with the agent's own pre-commit `python scripts/check.py --fix`, so the three cannot drift apart. Only three things block publication: a threat-detection finding, a patch that does not apply, and a patch that edits `scripts/check.py`, which is the gate itself. Test and lint findings are advisory. Generated `data/**` and `public/api/**` files are excluded; protected manifests, instructions, and `.github/**` changes create a blocking review requirement.
- A successful run may create one draft `[agentic]` PR. A no-change run must use the framework `noop` output. Agent prompts, patches, tool/network logs, token usage, and AI-credit estimates remain available through GitHub Actions artifacts and `gh aw audit`.
- The Aider fallback retains its narrow issue-derived editable paths, one optional test-feedback repair pass, exact local analytics, deterministic Git ownership, and same-branch rework behavior. Use it manually if the public-preview agentic lane fails or cannot produce a reviewable PR.
- First scheduled comparison run `29397795045` created PR #61 but consumed 3.42M tokens, 67 turns, and 477.783 AIC while logging 42 transient inference retries plus avoidable denied/malformed tool calls. The follow-up configuration supplies a concise issue-selection summary, enables literal `jq` extraction, forbids redundant dependency installation, caps runs at 50 turns/400 AIC, and requires truthful validation reporting.
- This replaces measured harness/model failures: GPT-5.4 Mini/Copilot consumed 4.23M tokens across three no-edit canaries, `o4-mini`/OpenCode reached the correct edit surface but produced no diff, and full GPT-4o/Aider generated invalid template edits. Aider with reasoning `o4-mini` passed a clean direct-edit smoke and combines bounded diff application with stronger reasoning.
- Live canary run `29205903483` completed in 1m36s and created draft PR #57 in one `o4-mini` call (73,385 tokens, estimated $0.093065) after focused tests, Ruff, and whitespace validation passed. A later request for the remaining broader navigation work failed validation; deterministic reset preserved the valid skip-link slice, and the PR was marked as partial without closing issue #56.
- Each task starts from a clean default-branch checkout. Agentic safe outputs own commits and PR creation; the model cannot push directly.
- The agent runs `python scripts/check.py --fix` before committing, which repairs unused imports and trailing whitespace in its own new code, and the independent publication gate reruns `python scripts/check.py` afterwards. A failing rerun no longer discards the work: [.github/workflows/agentic-backlog-outcome.yml](../.github/workflows/agentic-backlog-outcome.yml) posts the findings as a comment and an `agentic/validation` commit status on the draft PR. GitHub does not start `pull_request` workflows for events raised with `GITHUB_TOKEN`, so that commit status, not **PR validation**, is what reports on a bot-authored PR; **PR validation** covers human pull requests and pushes to `main`.
- A failed, ambiguous, invalid, or no-change task creates no pull request.
- Generated live snapshots and static API payloads are never included in a published patch.

Security and repository-hygiene sessions have an additional report-only boundary:

- Copilot CLI excludes shell, PowerShell, file viewing/search, create, edit, and write tools from report sessions. Reports operate only on the bounded precomputed evidence, receive no GitHub token, and have no GitHub MCP, Azure CLI, or network access.
- Deterministic outer code gathers branch/PR/worktree evidence before the model starts. Branch names, PR text, files, and evidence remain untrusted context.
- The runner checks the Git working tree after each analysis. If any tracked or untracked file changed, it resets the checkout and publishes no report.
- Only deterministic outer code in the private companion repository can create labels or replace the two stable report issue bodies. Generated mentions are neutralized before publication.
- The hygiene session can recommend commands but has no branch/worktree deletion implementation or permission path.
- Scheduled issue work runs one agentic issue per day with a 30-minute job timeout, 50 tool turns, three Copilot continuations, and per-run/daily AI-credit limits. Manual Aider fallback retains its 15-minute per-message timeout and can explicitly request one to three issue sessions. Documentation and private report Copilot sessions remain capped at 10 minutes.

Every generated PR includes a reviewer-facing rationale in its description:

- why the issue was selected, including queue priority and source issue;
- the objective and any current live unknown-status evidence;
- the agent's concise final decision, evidence, implementation summary, alternatives/risks, and validation notes;
- the exact changed files and deterministic checks run.

Agentic issue PRs use safe-output metadata and GitHub Actions audit artifacts. Aider fallback PRs retain their deterministic reviewer summary plus sanitized visible chat/diff output. Copilot maintenance uses the latest visible `assistant.message`. Opaque/encrypted reasoning and private chain-of-thought are excluded; secret-like values are redacted.

When an initial issue session intentionally makes no edit, reaches its outer budget, or fails deterministic scope/validation checks, no PR is required. Deterministic outer code creates or replaces one stable `Azure BYOK agent note` comment on the source issue with the bounded outcome, final visible summary when available, model/token metadata, and workflow link. Later runs replace that note instead of adding daily comment noise. Non-recurring no-PR issues receive `azure-paused` automatically so the next daily cycle advances to newer work; a maintainer can refine, close, or explicitly unpause them. Recurring monitor issues remain eligible. Requested PR rework is stricter: no repository change, failed validation, or an empty cumulative PR diff fails the rework workflow and cannot be published as success.

Agentic runs expose prompts, outputs, patches, tool/firewall logs, token usage, and estimated AI credits in their workflow artifacts. Aider fallback PRs continue reporting exact local-only prompt/completion tokens, API calls, duration, estimated cost, and repair-pass use. Copilot maintenance sessions retain their OpenTelemetry-based accounting. Opaque reasoning and secrets are excluded from published artifacts.

## Requesting Changes On A Bot PR

Both agentic `[agentic]` PRs and Aider fallback PRs can receive another Azure-funded coding pass without opening the Actions page. The dispatcher routes salted `agentic/issue-*` branches back to the agentic runner and `azure-issues/issue-<number>` branches to Aider:

1. Describe the required bounded correction in the **Request changes** review body, or begin a submitted review or new PR conversation comment with `/agent-rework`.
2. Submit the review or comment. The triggering text is capped and carried as trusted acceptance criteria only after write-level permission and PR/source-issue validation; it cannot expand editable paths or override safety controls.
3. The dispatcher posts a visible queued-status comment and starts the appropriate agentic or Aider rework runner.
4. The status comment is updated with the final workflow result and link. A successful code update also refreshes the same PR description and adds the normal completion comment.

The dispatcher accepts only an open, same-repository PR authored by `github-actions[bot]`, targeting the default branch from an agentic or Aider issue branch. It verifies the triggering user's current GitHub permission through the repository API and accepts only `write`, `maintain`, or `admin`. The source issue must still be open, labelled `azure-backlog`, and not labelled `azure-paused`. Bot events, fork PRs, arbitrary branches, ordinary nonblocking reviews, and comments that merely mention the command later in their text are ignored.

When the initial scheduled-agent publication gate reports a nonzero `scripts/check.py` result, its deterministic outcome follower queues one automatic `validation-failure` repair pass after publishing the exact advisory output on the PR. The request is keyed to the original run and skipped when a rework is already active, so workflow reruns do not duplicate it. A rework commit can rerun PR validation but cannot recursively schedule another model pass; any remaining failure stays visible for human review.

An active status marker deduplicates repeated review events and commands for the same PR. A marker is considered stale after two hours so a cancelled run cannot block recovery indefinitely. The dispatcher has no Azure secret: it sends a bounded `repository_dispatch` payload to the existing workflow, where Azure credentials remain isolated.

The targeted run selects only the source issue and skips documentation alignment. It fetches all current PR conversation comments, submitted reviews, and inline comments as untrusted supporting context, while the exact validated triggering text is a separate trusted top-level requirement. It checks out the existing PR branch; applies bounded amendments; runs focused and full tests plus Ruff/whitespace validation; pushes another bot commit; and refreshes the same PR rationale, model, token, and chat-artifact metadata. It does not create a second PR, and it fails visibly if no cumulative PR delta survives validation.

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
- Secret `AZURE_CODING_OPENAI_KEY`: key for the dedicated coding resource. In the agentic lane it is isolated in the AWF API proxy; the Aider fallback passes it only to the provider process.
- Variable `AZURE_CODING_RESOURCE_NAME`: Azure OpenAI resource name; currently `azrm-code-eus2-16221e01`. The compiled agentic workflow currently pins the corresponding `/openai/v1` hostname and must be recompiled if this variable changes.
- Variable `AZURE_CODING_MODEL`: deployment/model name; currently `o4-mini`. The agentic source and lock workflow pin this model explicitly for reproducibility.
- Optional `AZURE_COPILOT_DEPLOYMENT` and `COPILOT_BYOK_MODEL_ID`: retained for public documentation and private report Copilot sessions, not issue coding.

Use [.github/workflows/provision-azure-codex-openai.yml](../.github/workflows/provision-azure-codex-openai.yml) to create or verify the dedicated East US 2 OpenAI resource and `o4-mini` deployment. Its optional repository-settings mode writes only the `AZURE_CODING_*` settings and needs the separate `GH_REPO_SETTINGS_TOKEN`; grant that token only minimum settings permissions and rotate it after bootstrap.

The deployment pins `o4-mini` version `2025-04-16` and `GlobalStandard` capacity 100. Before changing the version, verify the target SKU in the regional model catalog and available subscription quota, update the provisioning workflow default, provision first, run a targeted canary, and only then change the repository model variable.

The agentic workflow gives the model only read permissions. Deterministic preparation may update the stable status issue, while separate safe-output jobs receive scoped write permissions to create a draft PR after validation. The Aider fallback retains its deterministic outer Git/GitHub steps. The separate PR event dispatcher has no Azure credential access. Azure BYOK means these workflows have no Copilot entitlement requirement.

## Cost Controls

- Azure OpenAI is the scheduled provider for GitHub Agentic Workflows issue coding and Copilot documentation/report work. Aider uses the same dedicated coding deployment only when manually dispatched or invoked for existing-PR rework.
- The 07:00 UTC agentic backlog run starts at most one issue-agent session. Manual agentic dispatch targets at most one issue; manual Aider fallback may choose one to three. Public documentation alignment runs at 09:00 UTC. The private companion repository starts security and hygiene sessions at 10:00 UTC. These use Azure tokens, not GitHub Copilot model quota.
- BYOK agent prompts contain the bounded task evidence and may use more Azure input tokens than the former direct JSON client; that trade-off is intentional for a full coding-agent runtime.
- The agentic lane caps the main run at 400 AI credits, a rolling daily schedule at 800 AI credits, threat detection at 200 AI credits, 50 tool turns, three continuations, and 30 minutes. The dedicated `o4-mini` deployment has 100K TPM.
- The Aider fallback keeps its 70-minute job limit so a manually requested three-issue run can accommodate three 15-minute outer budgets plus validation and cooldowns. Each scheduled or manual agentic run creates at most one draft PR. Each workflow has its own concurrency lock.
- The older Copilot path is intentionally manual-only in [.github/workflows/scheduled-copilot-agents.yml](../.github/workflows/scheduled-copilot-agents.yml), for occasional manual use rather than recurring consumption.

## Manual Run

For coding backlog work:

1. Create or reprioritize issues in GitHub.
2. Open **Actions** and select **Scheduled agentic backlog**.
3. Optionally set `target_issue`; otherwise the deterministic queue chooses the highest-priority eligible issue.
4. Review the resulting draft `[agentic]` PR and its Actions audit artifacts. Merging a non-recurring issue-backed PR closes its source issue only when its body contains the generated closing keyword.

For manual fallback or existing Aider PR rework, select **Scheduled Azure backlog**. Use its dry run first, then disable `dry_run` only when the selected task is correct. Use `force` only to deliberately update an existing Aider task branch; it does not bypass scope, test, lint, or whitespace validation.

For public documentation work, select **Scheduled Azure documentation alignment**. For security/hygiene work, use **Scheduled private Azure analysis** in the private companion repository. Dry runs build the relevant manifests without starting a model, creating a PR, or updating reports.

The schedules are reversible: disable the agentic schedule before restoring the Aider schedule so regular issue work never runs twice.
<!-- End of Azure-funded agent session guide. -->
