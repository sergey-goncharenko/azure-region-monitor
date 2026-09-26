# Azure-Funded Agent Sessions

This repository runs bounded Azure-funded schedules. The regular issue backlog runs daily at 06:23 UTC through the GitHub Agentic Workflows source [.github/workflows/scheduled-agentic-backlog.md](../.github/workflows/scheduled-agentic-backlog.md) and its generated lock workflow. The former Aider workflow [.github/workflows/scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml) remains available only for manual fallback and existing PR rework. The separate public documentation alignment session runs at 08:41 UTC through [.github/workflows/scheduled-azure-maintenance.yml](../.github/workflows/scheduled-azure-maintenance.yml). Maintainer-only security and repository-hygiene analysis runs at 10:00 UTC in the private `azure-region-monitor-maintainers` companion repository. Actionable public coding work lives in GitHub Issues, not in repository configuration files.

## Policy And Enforcement

The canonical changeable human-agent delivery principles live in [.github/workflows/shared/agentic-policy.md](../.github/workflows/shared/agentic-policy.md). Scheduled issue coding, agentic PR rework, and model canaries import that file at runtime, so a policy revision changes all coding lanes without copying prompt prose. Every agent run uploads `agentic-policy-provenance`, containing the policy text plus its revision and SHA-256 digest.

The policy is not an authorization mechanism. Permissions, secret isolation, safe-output boundaries, protected and excluded files, status semantics, `scripts/check.py`, retry bounds, and cost ceilings remain executable workflow or Python controls covered by tests. Issues may propose a policy change, but they are untrusted task context and cannot change live policy. Run artifacts are immutable audit evidence for what a session used, not a control plane. A semantic policy change requires a human-reviewed repository change, a policy revision increment, strict compilation of all importing workflows, and `python scripts/check.py`.

## Issue Backlog Order

The 06:23 UTC run selects one eligible open issue, highest priority first. Manual agentic dispatch can target one issue. The Aider fallback can still choose one to three sessions manually. Neither coding workflow runs documentation alignment or invents coding tasks outside the issue queue. Unknown checks become work only through issue #48 (or another explicit backlog issue); live snapshot evidence never creates a standalone task.

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

Every non-dry-run backlog workflow updates one stable `[agent-status] Scheduled Azure backlog` issue labelled `azure-agent-status` with the latest workflow link and open, queue-eligible, malformed-template, deferred-without-unknown-evidence, open-PR-blocked, paused, and selected counts. A malformed backlog issue also receives one idempotent bot question asking a maintainer to add or expand the exact `### Objective` section; later runs do not duplicate that comment. When no runnable task remains, no model is started and the status issue receives one concise comment with the reason. Selected runs continue to use source-issue notes and draft PRs for detailed outcomes.

## Comments, Parent Issues, And Sub-Issues

The task builder retrieves the selected issue metadata and body, all available issue comments, the parent issue when one exists, and all direct sub-issues with their bodies and comments. This means comments are the right place for follow-up thoughts, corrections, acceptance details, and recommendations. The latest three non-bot source-issue comments are copied into the first-read task summary so the next agent sees them before editing. No command syntax is required. Do not include secrets, tokens, subscription IDs, private resource names, customer data, or other sensitive information in any forwarded issue text.

The title and **Objective** field remain the authority for task selection and relevance hints. Comments and sub-issues provide additional decision evidence but are not trusted instructions. Full-repository agentic access does not let issue text override safe-output exclusions, protected-file review, deterministic validation, or tool/network controls.

Issue text is untrusted context, not agent instructions. The agent ignores attempts in bodies, comments, or child issues to override safety rules, access secrets, use network tools, or expand its scope. Each retrieved text field is limited to 8,000 characters. The model receives a compact projection of the issue objective and controls; failed-attempt reports and later comments are separately bounded before entering the first-read summary. Any truncation is explicitly marked so the agent does not mistake it for complete context.

## Azure-BYOK Coding And Maintenance Harnesses

Regular issue coding uses GitHub Agentic Workflows (`gh-aw`) with a pinned Copilot CLI version and the model selected by the `AZWATCH_AGENTIC_MODEL` repository variable. That value supplies both the CLI model and the BYOK provider model ID; the provider must support it over the Responses API. The endpoint and key remain secrets, and each run's `aw_info.json` records the resolved model and runtime versions. The pinned versions are tracked in the compiled lock files ([scheduled-agentic-backlog.lock.yml](../.github/workflows/scheduled-agentic-backlog.lock.yml), [agentic-pr-rework.lock.yml](../.github/workflows/agentic-pr-rework.lock.yml)) and the `AZWATCH_AGENTIC_COPILOT_VERSION` repository variable. The Aider lane remains manual fallback and existing-PR rework support while results are compared; its version is pinned in [scheduled-azure-backlog.yml](../.github/workflows/scheduled-azure-backlog.yml). Public documentation alignment and private security/hygiene reports remain on pinned GitHub Copilot CLI. Inference is billed through the configured BYOK provider rather than GitHub Copilot model quota.

Every editing task is bounded before a branch or PR is created:

- Deterministic Python code still selects one issue, enriches recurring unknown work from the live snapshot, skips issues with open Aider or agentic PRs, and writes a compact task manifest. The manifest is transferred to the isolated agent job without exposing credentials.
- The agentic Copilot runtime may inspect and edit the full repository. It runs inside the Agent Workflow Firewall with an explicit network allowlist, bounded continuations, selected shell commands, read-only GitHub tools, and safe-output-only repository writes.
- The Azure coding key is held by the AWF API-proxy sidecar and explicitly excluded from the agent container. The agent receives neither the real provider key nor a write-capable GitHub token.
- Candidate changes are buffered as artifacts. Threat detection checks the patch, then a deterministic post-step applies it to a clean checkout and runs `python scripts/check.py`. That script is the single validation entrypoint shared with [.github/workflows/pr-validation.yml](../.github/workflows/pr-validation.yml) and with the agent's own pre-commit `python scripts/check.py --fix`, so the three cannot drift apart. Findings do not erase a coherent patch: validation is posted on the draft PR, while threat and protected-file findings add a warning label and generated `REQUEST_CHANGES` review. Patch-application failure, edits to `scripts/check.py`, or missing GitHub permission can still prevent publication. Generated `data/**` and `public/api/**` files remain excluded.
- A successful run may create one draft `[agentic]` PR. A no-change run must use the framework `noop` output. Agent prompts, patches, tool/network logs, token usage, and AI-credit estimates remain available through GitHub Actions artifacts and `gh aw audit`.
- The Aider fallback retains its narrow issue-derived editable paths, one optional test-feedback repair pass, exact local analytics, deterministic Git ownership, and same-branch rework behavior. Use it manually if the public-preview agentic lane fails or cannot produce a reviewable PR.
- First scheduled comparison run `29397795045` created PR #61 but consumed 3.42M tokens, 67 turns, and 477.783 AIC while logging 42 transient inference retries plus avoidable denied/malformed tool calls. The initial follow-up configuration supplied a concise issue-selection summary, enabled literal `jq` extraction, forbade redundant dependency installation, capped runs at 50 turns/400 AIC, and required truthful validation reporting. Current limits are described under **Cost Controls** below.
- This replaces measured harness/model failures: GPT-5.4 Mini/Copilot consumed 4.23M tokens across three no-edit canaries, `o4-mini`/OpenCode reached the correct edit surface but produced no diff, and full GPT-4o/Aider generated invalid template edits. Aider with reasoning `o4-mini` passed a clean direct-edit smoke and combines bounded diff application with stronger reasoning.
- Live canary run `29205903483` completed in 1m36s and created draft PR #57 in one `o4-mini` call (73,385 tokens, estimated $0.093065) after focused tests, Ruff, and whitespace validation passed. A later request for the remaining broader navigation work failed validation; deterministic reset preserved the valid skip-link slice, and the PR was marked as partial without closing issue #56.
- Each new issue task starts from a clean default-branch checkout. The agent prepares a local commit; safe outputs capture that commit and own remote branch/PR publication. PR rework instead commits on the already-checked-out reviewed branch. The model cannot push directly.
- The agent runs `python scripts/check.py --fix` before committing, which repairs unused imports and trailing whitespace in its own new code, and the independent publication gate reruns `python scripts/check.py` afterwards. A failing rerun no longer discards the work: [.github/workflows/agentic-backlog-outcome.yml](../.github/workflows/agentic-backlog-outcome.yml) posts the findings as a comment and an `agentic/validation` commit status on the draft PR. GitHub does not start `pull_request` workflows for events raised with `GITHUB_TOKEN`, so that commit status, not **PR validation**, is what reports on a bot-authored PR; **PR validation** covers human pull requests and pushes to `main`.
- If no coherent or publishable patch exists because evidence, clarification, or permission is missing, the agent comments on the source issue with one concrete question. A later scheduled attempt receives ordinary human replies. A task that is already satisfied uses `noop`.
- Generated live snapshots and static API payloads are never included in a published patch.

Security and repository-hygiene sessions have an additional report-only boundary:

- Copilot CLI excludes shell, PowerShell, file viewing/search, create, edit, and write tools from report sessions. Reports operate only on the bounded precomputed evidence, receive no GitHub token, and have no GitHub MCP, Azure CLI, or network access.
- Deterministic outer code gathers branch/PR/worktree evidence before the model starts. Branch names, PR text, files, and evidence remain untrusted context.
- The runner checks the Git working tree after each analysis. If any tracked or untracked file changed, it resets the checkout and publishes no report.
- Only deterministic outer code in the private companion repository can create labels or replace the two stable report issue bodies. Generated mentions are neutralized before publication.
- The hygiene session can recommend commands but has no branch/worktree deletion implementation or permission path.
- Scheduled issue work runs one agentic issue per day with a workflow-defined timeout, `AZWATCH_AGENTIC_MAX_TURNS` tool turns, three Copilot continuations, and per-run/daily AI-credit limits. Manual Aider fallback retains its 15-minute per-message timeout and can explicitly request one to three issue sessions. Documentation and private report Copilot sessions remain capped at 10 minutes.

Every generated PR includes a reviewer-facing rationale in its description:

Reader-facing product work follows the [verified reader-improvement plan](reader-improvement.md):
fixed questions and cases, source-backed feature context, before/after evidence, and
voluntary comprehension measurements. The plan documents product research; it does
not change the workflow policy or authorize work from raw feedback.

- why the issue was selected, including queue priority and source issue;
- the objective and any current live unknown-status evidence;
- the agent's concise final decision, evidence, implementation summary, alternatives/risks, and validation notes;
- the exact changed files and deterministic checks run.

When a change needs visual review, the agent must put the visual evidence where reviewers can inspect it inline, such as a concise PR comment with rendered images or a Markdown-friendly comparison. Do not make reviewers download and open a standalone HTML preview to understand a proposed design; include a short caption and the decision the visual supports.

The [static-site visual-evidence workflow](../.github/workflows/static-site-visual-evidence.yml)
checks out workflow tooling, base, and head in separate workspace subdirectories.
Both application revisions use the same copied repository-data fixture, with raw
dated snapshots supplying history when none is checked in; probes and AI writing
are disabled. The manifest records exact base/head commits and the shared snapshot
hash/date. This is a rendering comparison on repository fixtures, not a claim
about the currently deployed dataset.

The workflow runs for relevant PR changes and relevant pushes to `main`.
PR comparisons keep the exact PR base/head revisions, including historical broken
commits; squashing a later fix does not change those older results. Main pushes
instead perform a clearly named **reference smoke check** on the new commit,
building that same revision on both sides. This checks current rendering without
pretending to be a historical before/after comparison.

To validate an existing PR without changing its branch, use **Run workflow** and
supply `pr_number`. Leave it blank to smoke-test the selected ref (normally `main`).
Manual runs also cover cases where a bot-created event did not start a workflow.
The run summary links
an artifact containing an HTML before/after index, PNGs, a manifest, and build/server
logs. If one revision fails to build, screenshots from the successful side are
retained, the failed side is marked unavailable (not "added" or "removed"), and
the overall run remains failed. Partial generated HTML is never treated as a
successful build. Agents still need to bring relevant images into reviewer-facing
comments rather than treating an artifact upload alone as completed visual review.

Agentic issue PRs use safe-output metadata and GitHub Actions audit artifacts. Aider fallback PRs retain their deterministic reviewer summary plus sanitized visible chat/diff output. Copilot maintenance uses the latest visible `assistant.message`. Opaque/encrypted reasoning and private chain-of-thought are excluded; secret-like values are redacted.

Every coherent agentic change is published as a draft when safe-output transport permissions allow it, even if validation or threat detection reports findings. The draft cannot be squashed until a human marks it ready. Generated `REQUEST_CHANGES` reviews make security and protected-file findings prominent; the validation follower posts deterministic test/lint results on the PR and a concise source-issue link. There is no automatic retry. Requested PR rework remains available only when a human explicitly submits review feedback.

Agentic runs expose prompts, outputs, patches, tool/firewall logs, token usage, and estimated AI credits in their workflow artifacts. Aider fallback PRs continue reporting exact local-only prompt/completion tokens, API calls, duration, estimated cost, and repair-pass use. Copilot maintenance sessions retain their OpenTelemetry-based accounting. Opaque reasoning and secrets are excluded from published artifacts.

### Local Command Denials

The [September 26 run](https://github.com/sergey-goncharenko/azure-region-monitor/actions/runs/36224625002)
submitted a compound publication command containing an unallowlisted `git show-ref`
probe. The call was denied before a standalone branch, staging, or commit attempt.
The [September 22 run](https://github.com/sergey-goncharenko/azure-region-monitor/actions/runs/35696375953)
had successfully committed with the same runtime versions and Git grants. This was
not evidence that the agent needed a GitHub write token.

The shared policy's **Local Commands And Publication** section governs diagnosis,
delegation, and safe handling of these denials. Workflow-specific prompts supply
the separate local command sequence without expanding the tool allowlist.
Prompt-contract tests cover all three coding lanes; compiled-workflow tests
preserve the scheduled agent's read-only credentials and restricted shell grants.
These tests do not simulate the CLI's permission matcher. After publishing a
guidance change, use a controlled run to verify local commit creation, captured
patch, independent validation, and actual safe-output publication.

An issue comment is an escalation, not a delivered fix. The backlog outcome
follower currently consumes the raw Actions conclusion, so a green comment-only
run must not be interpreted as proof that a patch was published or validated.

## Requesting Changes On A Bot PR

Both agentic `[agentic]` PRs and Aider fallback PRs can receive another Azure-funded coding pass without opening the Actions page. The dispatcher routes salted `agentic/issue-*` branches back to the agentic runner and `azure-issues/issue-<number>` branches to Aider:

The shared workflow is named **PR rework dispatcher** (formerly **Azure BYOK PR
rework**). It is not an Aider-only check. Its job skips non-human events and reviews
other than **Request changes** before checkout; Python still performs the
authoritative permission, target, and duplicate-request checks.

GitHub may separately require approval for workflows triggered by Copilot activity,
even on a same-repository PR and before a job's `if:` condition is evaluated. This
is not an Azure environment approval or the gh-aw threat-detection gate. Old
unapproved/expired runs do not need to be approved to make a later legitimate human
Request changes review work. The early job guard reduces unnecessary runner work
but cannot guarantee suppression of these admission banners. Do not disable
repository-wide Copilot workflow protection merely to hide them. Moving to a
trusted scheduled/manual review poller is a separate design decision if eliminating
the event-triggered approval noise becomes necessary.

1. Describe the required bounded correction in the **Request changes** review body. Ordinary comments record context but do not dispatch work.
2. Submit the **Request changes** review. The triggering text is capped and carried as trusted acceptance criteria only after write-level permission and PR/source-issue validation; it cannot expand editable paths or override safety controls.
3. The dispatcher posts a visible queued-status comment and starts the appropriate agentic or Aider rework runner.
4. The status comment reports the verified publication outcome and links to the run. An agentic code update is successful only when the safe-output commit is verified on the original PR branch; a green job alone is not proof of publication.

The dispatcher accepts only an open, same-repository PR authored by `github-actions[bot]`, targeting the default branch from an agentic or Aider issue branch. It verifies the triggering user's current GitHub permission through the repository API and accepts only `write`, `maintain`, or `admin`. The source issue must still be open, labelled `azure-backlog`, and not labelled `azure-paused`. Bot events, fork PRs, arbitrary branches, ordinary nonblocking reviews, and comments that merely mention the command later in their text are ignored.

Validation findings do not start another model pass. Leave ordinary comments when recording context only. Submit **Request changes** when you intentionally want the existing PR rework dispatcher to start a bounded correction pass.

An active status marker deduplicates repeated review events and commands for the same PR. A marker is considered stale after two hours so a cancelled run cannot block recovery indefinitely. The dispatcher has no Azure secret: it sends a bounded `repository_dispatch` payload to the existing workflow, where Azure credentials remain isolated.

The targeted run selects only the source issue and skips documentation alignment. It fetches current PR conversation comments, submitted reviews, and inline comments as untrusted supporting context, while the exact validated triggering text is a separate trusted top-level requirement. It checks out the existing PR branch, applies bounded amendments, and runs focused and full tests plus Ruff/whitespace validation.

**Agentic rework is same PR or blocked.** Failed threat-detector installation, threat detection, validation, or branch publication never authorize a replacement or review PR. Non-fast-forward fallback is disabled, and a semantic detection gate prevents gh-aw's warning-to-review-PR conversion. The candidate patch is retained for seven days in the `agentic-rework-patch` run artifact before validation, without publishing model chats or private reports in the status comment. A blocked run requires a human decision before retry; the original PR is not claimed as updated.

The finalizer checks the executed safe-output manifest and detector/publication results, then verifies the live target branch against its recorded initial identity and the emitted push commit SHA. An explicitly requested out-of-scope follow-up may instead create one backlog issue, reported as **follow-up-created**, not a code update. Protected-file edits still divert to a human review issue and are reported as **blocked**, with that issue linked. Neither path silently creates another PR. The scheduled new-issue lane retains its separate draft-first publication policy.

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
- Secret `AZWATCH_AGENTIC_AZURE_BASE_URL`: BYOK base URL for the agentic coding lanes.
- Variable `AZWATCH_AGENTIC_MODEL`: model/deployment ID for scheduled coding, agentic PR rework, and the default canary. The canary's explicit `model=gpt-6-astra` input overrides it for that coding run only; its independent detector retains the repository model.
- Variable `AZWATCH_AGENTIC_COPILOT_VERSION`: pinned CLI version for those same workflows.
- Variable `AZWATCH_AGENTIC_MAX_TURNS`: bounded tool-turn limit for those same workflows.
- Variables `AZURE_CODING_RESOURCE_NAME` and `AZURE_CODING_MODEL`: dedicated resource and deployment/model settings used by the Aider fallback, not the agentic model selectors.
- Optional `AZURE_COPILOT_DEPLOYMENT` and `COPILOT_BYOK_MODEL_ID`: retained for public documentation and private report Copilot sessions, not issue coding.

Use [.github/workflows/provision-azure-codex-openai.yml](../.github/workflows/provision-azure-codex-openai.yml) to create or verify the dedicated East US 2 OpenAI resource and `o4-mini` deployment. Its optional repository-settings mode writes only the `AZURE_CODING_*` settings and needs the separate `GH_REPO_SETTINGS_TOKEN`; grant that token only minimum settings permissions and rotate it after bootstrap.

That bootstrap workflow defaults to `o4-mini` version `2025-04-16` and `GlobalStandard` capacity 100; it does not describe the current agentic deployment. For an agentic model change, first verify the actual secret endpoint's deployment, Responses/tool-calling compatibility, quota, and AWF pricing coverage under the existing credit ceilings. A model catalog listing or free quota is not proof of deployable capacity or successful inference. Obtain approval before creating a paid deployment, retain the previous deployment for rollback, and run a bounded canary before promotion. Use the isolated canary input rather than changing the shared production model variable for an experiment.

The agentic workflow gives the model only read permissions. Deterministic preparation may update the stable status issue, while separate safe-output jobs receive scoped write permissions to create a draft PR after validation. The Aider fallback retains its deterministic outer Git/GitHub steps. The separate PR event dispatcher has no Azure credential access. Azure BYOK means these workflows have no Copilot entitlement requirement.

### Astra Canary And Terra Rollback

On 2026-09-26, `gpt-6-astra` version `2026-09-03` was deployed beside
`gpt-5.6-terra` in the existing East US 2 coding resource: Global Standard,
capacity 500, `Microsoft.DefaultV2`, and `NoAutoUpgrade`. Terra's deployment
properties and capacity were verified unchanged. Direct Entra-authenticated
Responses, streaming function-call, and tool-result round-trip smoke tests passed.
These small probes do not replace a successful coding/publication canary.

The production model remains `gpt-5.6-terra`. In **Actions / Model canary**, choose
`model=gpt-6-astra` and an eligible `target_issue` to test Astra without changing
scheduled or rework model selection. This is a real bounded coding run that may
publish one draft PR. It uses the existing 80-turn repository setting and
700-credit run ceiling; the detector stays on Terra with its 200-credit ceiling.
The canary disables catalog-based model substitution and whole-session retries.
Review actual model/usage provenance, local commit and patch capture, validation,
and the published result before interpreting the run as successful.

The first [Astra coding canary](https://github.com/sergey-goncharenko/azure-region-monitor/actions/runs/36253553476)
on issue #130 failed closed before commit/publication. Its recorded error was
`Maximum AI credits exceeded (701.847400 / 700)`, not an invalid Azure key,
despite the CLI's generic authentication message. It recorded 1,108,468 input
tokens (939,912 cached reads) and 12,330 output tokens. The conservative
accounting total was approximately $7.02 equivalent, not a verified Azure bill.
No draft PR or independently validated patch was produced. No retry, ceiling
increase, or production model switch followed. The deployed model passed API
smokes, but this did not establish a successful end-to-end coding canary.

**Automatic Astra-to-Terra failover is not implemented.** The pinned runtime's
model-resolution fallback is not transient-error failover. Keep Terra as the
production default until a separately reviewed trusted router can provide one
bounded fallback on positively identified upstream availability/rate-limit
failures, before streaming starts. It must not replay tool calls or bypass
authentication, content safety, validation, or cost controls, and must account
for both attempts. Missing pricing or a budget rejection must fail closed.

## Cost Controls

- Azure OpenAI is the scheduled provider for GitHub Agentic Workflows issue coding and Copilot documentation/report work. Aider uses the same dedicated coding deployment only when manually dispatched or invoked for existing-PR rework.
- The 06:23 UTC agentic backlog run starts at most one issue-agent session. Manual agentic dispatch targets at most one issue; manual Aider fallback may choose one to three. Public documentation alignment runs at 08:41 UTC. The private companion repository starts security and hygiene sessions at 09:52 UTC. These use Azure tokens, not GitHub Copilot model quota.
- BYOK agent prompts contain the bounded task evidence and may use more Azure input tokens than the former direct JSON client; that trade-off is intentional for a full coding-agent runtime.
- The scheduled agentic lane caps the main run at 700 AI credits, a rolling daily schedule at 1400 AI credits, threat detection at 200 AI credits, `AZWATCH_AGENTIC_MAX_TURNS` tool turns, and three continuations. Timeout and credit limits are enforced by the workflow and compiled runtime; model changes must preserve those controls. AI credits are runtime cost estimates, not an Azure invoice.
- Astra has a model-specific [pricing catalog](../.github/workflows/shared/agentic-models.md), not a catch-all price for unknown models. The [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) reported the following East US 2 Global Standard USD-per-million rates on 2026-09-26:

  | Context tier | Input | Output | Cached read | Cache write |
  | --- | ---: | ---: | ---: | ---: |
  | Short | $10 | $50 | $1 | $12.50 |
  | Long | $20 | $75 | $2 | $25 |

  AWF's Astra budget uses conservative rates of $25/$75/$2/$25 respectively.
  Ordinary input is deliberately overestimated because the pinned Responses
  parser does not separately extract cache-write tokens; the catalog documents
  the input-subset assumption and bound. Missing usage and in-flight requests
  can still defeat invoice-exact accounting: retain Azure Cost Management and
  model usage monitoring rather than treating AI credits as a hard billing cap.
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
