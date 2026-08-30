---
name: Agentic PR rework
description: Rework an open agentic draft PR from bounded collaborator feedback on the same lane.
on:
  repository_dispatch:
    types: [azure-agentic-pr-rework]
  bots: ["github-actions[bot]"]

permissions:
  contents: read
  issues: read
  pull-requests: read

strict: true
imports:
  - shared/agentic-policy.md
concurrency:
  group: agentic-pr-rework-${{ github.event.client_payload.rework_pr }}
  cancel-in-progress: false

jobs:
  prepare:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: read
      pull-requests: read
    outputs:
      has_task: ${{ steps.select.outputs.has_task }}
      pr_number: ${{ steps.verify.outputs.pr_number }}
      head_ref: ${{ steps.verify.outputs.head_ref }}
      task_b64: ${{ steps.select.outputs.task_b64 }}
      summary_b64: ${{ steps.select.outputs.summary_b64 }}
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      - run: python -m pip install -e .
      - name: Validate dispatch metadata and confirm the pull request
        id: verify
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_ISSUE: ${{ github.event.client_payload.target_issue }}
          REWORK_PR: ${{ github.event.client_payload.rework_pr }}
          REWORK_STATUS_COMMENT_ID: ${{ github.event.client_payload.rework_status_comment_id }}
          REWORK_REQUEST_ID: ${{ github.event.client_payload.rework_request_id }}
          REWORK_TRIGGER: ${{ github.event.client_payload.rework_trigger }}
          REWORK_ACTOR: ${{ github.event.client_payload.rework_actor }}
          REWORK_HEAD_REF: ${{ github.event.client_payload.rework_head_ref }}
          REWORK_REQUIREMENTS: ${{ github.event.client_payload.rework_requirements }}
        run: |
          set -euo pipefail
          if [[ ! "$TARGET_ISSUE" =~ ^[1-9][0-9]*$ ]] || \
             [[ ! "$REWORK_PR" =~ ^[1-9][0-9]*$ ]] || \
             [[ ! "$REWORK_STATUS_COMMENT_ID" =~ ^[1-9][0-9]*$ ]] || \
             [[ ! "$REWORK_REQUEST_ID" =~ ^[1-9][0-9]*-[1-9][0-9]*$ ]] || \
             [[ ! "$REWORK_ACTOR" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] || \
             [[ ! "$REWORK_HEAD_REF" =~ ^agentic/issue-[1-9][0-9]*(-[0-9a-f]{6,32})?$ ]] || \
             [ "${#REWORK_REQUIREMENTS}" -gt 4000 ]; then
            echo "Malformed agentic PR rework dispatch metadata." >&2
            exit 2
          fi
          case "$REWORK_TRIGGER" in
            slash-command|request-changes|validation-failure) ;;
            *) echo "Unsupported agentic PR rework trigger." >&2; exit 2 ;;
          esac
          gh pr view "$REWORK_PR" \
            --repo "$GITHUB_REPOSITORY" \
            --json number,state,isDraft,title,headRefName,author,labels > "$RUNNER_TEMP/rework-pr.json"
          python - "$RUNNER_TEMP/rework-pr.json" <<'PYTHON'
          import json
          import os
          import sys

          pull = json.loads(open(sys.argv[1], encoding="utf-8").read())
          labels = {label.get("name") for label in pull.get("labels") or []}
          expected_ref = os.environ["REWORK_HEAD_REF"]
          problems = []
          if pull.get("state") != "OPEN":
              problems.append("the pull request is no longer open")
          if pull.get("headRefName") != expected_ref:
              problems.append("the head branch changed since the request was dispatched")
          if (pull.get("author") or {}).get("login") != "app/github-actions":
              problems.append("the pull request is not authored by GitHub Actions")
          if not str(pull.get("title") or "").startswith("[agentic] "):
              problems.append("the pull request is not an agentic-lane pull request")
          if "scheduled-agent" not in labels:
              problems.append("the pull request is missing the scheduled-agent label")
          if problems:
              print("Refusing agentic rework: " + "; ".join(problems), file=sys.stderr)
              raise SystemExit(2)
          PYTHON
          echo "pr_number=$REWORK_PR" >> "$GITHUB_OUTPUT"
          echo "head_ref=$REWORK_HEAD_REF" >> "$GITHUB_OUTPUT"
      - name: Fetch the source issue
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          gh issue list \
            --repo "$GITHUB_REPOSITORY" \
            --state open \
            --label azure-backlog \
            --limit 100 \
            --json number,title,body,labels,url > "$RUNNER_TEMP/azure-backlog-issues.json"
      - name: Build the bounded rework task
        id: select
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_ISSUE: ${{ github.event.client_payload.target_issue }}
          REWORK_PR: ${{ github.event.client_payload.rework_pr }}
          REWORK_TRIGGER: ${{ github.event.client_payload.rework_trigger }}
          REWORK_ACTOR: ${{ github.event.client_payload.rework_actor }}
          REWORK_REQUIREMENTS: ${{ github.event.client_payload.rework_requirements }}
        run: |
          set -euo pipefail
          mkdir -p /tmp/gh-aw/agent
          jq -n \
            --argjson pull_request "$REWORK_PR" \
            --arg trigger "$REWORK_TRIGGER" \
            --arg requested_by "$REWORK_ACTOR" \
            --arg requirements "$REWORK_REQUIREMENTS" \
            '{
              pull_request: $pull_request,
              trigger: $trigger,
              requested_by: $requested_by,
              requirements: $requirements
            }' > "$RUNNER_TEMP/agentic-pr-rework-context.json"
          python scripts/run_azure_backlog_cycle.py \
            --issues "$RUNNER_TEMP/azure-backlog-issues.json" \
            --repository "$GITHUB_REPOSITORY" \
            --max-issues 1 \
            --target-issue "$TARGET_ISSUE" \
            --rework-context "$RUNNER_TEMP/agentic-pr-rework-context.json" \
            --output "$RUNNER_TEMP/agentic-rework-manifest.json" \
            >> "$GITHUB_STEP_SUMMARY"
          # An open PR is the point of a rework, so nothing may be filtered out here.
          printf '[]' > "$RUNNER_TEMP/no-open-pulls.json"
          python scripts/filter_azure_agentic_tasks.py \
            --manifest "$RUNNER_TEMP/agentic-rework-manifest.json" \
            --open-pulls "$RUNNER_TEMP/no-open-pulls.json" \
            --output /tmp/gh-aw/agent/task.json \
            --github-output "$GITHUB_OUTPUT"
      - name: Publish rework status identifiers
        env:
          PR_NUMBER: ${{ github.event.client_payload.rework_pr }}
          STATUS_COMMENT_ID: ${{ github.event.client_payload.rework_status_comment_id }}
          REQUEST_ID: ${{ github.event.client_payload.rework_request_id }}
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/rework-status"
          jq -n \
            --arg pr_number "$PR_NUMBER" \
            --arg comment_id "$STATUS_COMMENT_ID" \
            --arg request_id "$REQUEST_ID" \
            '{pr_number: $pr_number, comment_id: $comment_id, request_id: $request_id}' \
            > "$RUNNER_TEMP/rework-status/status.json"
      # A gh-aw custom job cannot depend on safe_outputs, so the paired
      # conclusion job closes the status comment after all generated jobs finish.
      # The workflow_run follower remains an idempotent fallback for external dispatches.
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: agentic-rework-status
          path: ${{ runner.temp }}/rework-status/status.json
          retention-days: 1

  conclusion:
    pre-steps:
      - name: Download rework status identifiers
        id: download-rework-status
        continue-on-error: true
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
        with:
          name: agentic-rework-status
          path: ${{ runner.temp }}/rework-status
      - name: Checkout trusted finalizer code
        if: ${{ steps.download-rework-status.outcome == 'success' }}
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          ref: ${{ github.event.repository.default_branch }}
          persist-credentials: false
      - name: Set up finalizer Python
        if: ${{ steps.download-rework-status.outcome == 'success' }}
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      - name: Finalize the rework status comment
        if: ${{ steps.download-rework-status.outcome == 'success' }}
        env:
          GH_TOKEN: ${{ github.token }}
          AGENT_RESULT: ${{ needs.agent.result }}
          DETECTION_RESULT: ${{ needs.detection.result }}
          SAFE_OUTPUTS_RESULT: ${{ needs.safe_outputs.result }}
          RUN_URL: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          set -euo pipefail
          status_file="$RUNNER_TEMP/rework-status/status.json"
          pr_number="$(jq -r '.pr_number // ""' "$status_file")"
          comment_id="$(jq -r '.comment_id // ""' "$status_file")"
          request_id="$(jq -r '.request_id // ""' "$status_file")"
          if [ "$AGENT_RESULT" = success ] && \
             [ "$DETECTION_RESULT" = success ] && \
             [ "$SAFE_OUTPUTS_RESULT" = success ]; then
            outcome=success
          elif [ "$AGENT_RESULT" = cancelled ] || \
               [ "$DETECTION_RESULT" = cancelled ] || \
               [ "$SAFE_OUTPUTS_RESULT" = cancelled ]; then
            outcome=cancelled
          else
            outcome=failure
          fi
          python scripts/manage_azure_pr_rework.py finalize-status \
            --repository "$GITHUB_REPOSITORY" \
            --pr-number "$pr_number" \
            --comment-id "$comment_id" \
            --request-id "$request_id" \
            --outcome "$outcome" \
            --run-url "$RUN_URL"

  detection:
    needs: [prepare]

if: needs.prepare.outputs.has_task == 'true'

model: ${{ vars.AZWATCH_AGENTIC_MODEL }}
engine:
  id: copilot
  version: ${{ vars.AZWATCH_AGENTIC_COPILOT_VERSION }}
  max-continuations: 3
  env:
    COPILOT_PROVIDER_BASE_URL: ${{ secrets.AZWATCH_AGENTIC_AZURE_BASE_URL }}
    COPILOT_PROVIDER_API_KEY: ${{ secrets.AZURE_CODING_OPENAI_KEY }}
    COPILOT_PROVIDER_MODEL_ID: ${{ vars.AZWATCH_AGENTIC_MODEL }}
    COPILOT_PROVIDER_WIRE_API: responses

sandbox:
  agent: awf
network:
  allowed:
    - defaults
    - python
    - "*.openai.azure.com"

checkout:
  fetch: ["*"]
  fetch-depth: 0

timeout-minutes: 30
max-turns: ${{ vars.AZWATCH_AGENTIC_MAX_TURNS }}
max-ai-credits: 700
max-daily-ai-credits: 1400

tools:
  edit:
  bash:
    - "python:*"
    - "git diff:*"
    - "git log:*"
    - "git show:*"
    - "git status:*"
    - "jq:*"
    - "rg:*"
    - "python3:*"
    - "pytest:*"
    - "ruff:*"
  github:
    toolsets: [issues, repos, pull_requests]
  timeout: 300

steps:
  - name: Restore the bounded rework task
    env:
      TASK_B64: ${{ needs.prepare.outputs.task_b64 }}
      SUMMARY_B64: ${{ needs.prepare.outputs.summary_b64 }}
    run: |
      set -euo pipefail
      mkdir -p /tmp/gh-aw/agent
      printf '%s' "$TASK_B64" | base64 --decode > /tmp/gh-aw/agent/task.json
      printf '%s' "$SUMMARY_B64" | base64 --decode > /tmp/gh-aw/agent/task-summary.md
  - name: Check out the reviewed pull request branch
    env:
      HEAD_REF: ${{ needs.prepare.outputs.head_ref }}
    run: |
      set -euo pipefail
      git fetch origin "$HEAD_REF"
      git checkout -B "$HEAD_REF" "origin/$HEAD_REF"
      git --no-pager log --oneline -1
  - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
    with:
      python-version: "3.11"
  - run: |
      python -m pip install -e .
      python -m pip install "httpx>=0.27,<1" "pytest>=8.2,<9" "ruff>=0.6,<1"

safe-outputs:
  max-patch-size: 1024
  push-to-pull-request-branch:
    target: "*"
    required-title-prefix: "[agentic] "
    required-labels: [scheduled-agent]
    if-no-changes: error
    excluded-files:
      - .github/workflows/shared/agentic-policy.md
      - data/**
      - public/api/**
      - public/*.html
    # No new PR exists to carry a REQUEST_CHANGES review, so protected-file edits
    # divert to a human review issue instead of reaching the branch.
    protected-files: fallback-to-issue
  # Reviewers routinely ask for follow-up work that belongs in the backlog rather than
  # in this PR. Without this the agent can only report the request as a missing tool.
  create-issue:
    max: 1
    title-prefix: "[azure-backlog] "
    labels: [azure-backlog, scheduled-agent]
  threat-detection:
    max-ai-credits: 200
    prompt: |
      Reject patches that do not directly address the trusted reviewer requirements recorded in the task. Also reject unrelated bulk edits, generated snapshot edits, weakened status semantics, disabled tests, hidden network behavior, or changes that conflate provider-specific contracts.
    post-steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          ref: ${{ needs.prepare.outputs.head_ref }}
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      - name: Apply candidate patch and run deterministic validation
        shell: bash
        run: |
          set -euo pipefail
          python -m pip install -e .
          python -m pip install "httpx>=0.27,<1" "pytest>=8.2,<9" "ruff>=0.6,<1"
          patch_file="$(find /tmp/gh-aw/threat-detection -maxdepth 1 -type f -name 'aw*.patch' -print -quit)"
          if [ -z "$patch_file" ]; then
            # Filing the reviewer's follow-up request as a backlog issue is a legitimate
            # no-code outcome; any other empty rework is not.
            if jq -e '[.items[]? | select(.type == "create_issue")] | length > 0' \
                 /tmp/gh-aw/agent_output.json > /dev/null 2>&1; then
              echo "No code change was required; the reviewer's follow-up request was filed as a backlog issue."
              exit 0
            fi
            echo "A rework that changes nothing is a failure, not a success." >&2
            exit 1
          fi
          baseline_test_status=0
          python -m pytest > /tmp/gh-aw-baseline-tests.log 2>&1 || baseline_test_status=$?
          git apply "$patch_file"
          changed_files="$(git diff --name-only)"
          if grep -Eq '^src/.*\.py$' <<< "$changed_files" && \
             ! grep -Eq '^tests/test_.*\.py$' <<< "$changed_files" && \
             [ "$baseline_test_status" -eq 0 ]; then
            echo "A source behavior change requires a focused regression test when the baseline suite is green." >&2
            exit 1
          fi
          python -m pytest
          python -m ruff check .
          python -m ruff check --preview --select E117 .
          python -m ruff check --select B018 .
          git diff --check
---

# Azure Regional Feature Availability Monitor rework agent

Start by reading `/tmp/gh-aw/agent/task-summary.md` and the `rework` block of `/tmp/gh-aw/agent/task.json`. They identify one open agentic draft pull request, its source issue, and the bounded reviewer requirements that a write-level collaborator submitted.

The reviewed pull request branch is already checked out. Amend that existing work in place; do not start a new branch and do not open a new pull request.

The imported **Human-Agent CI/CD Policy** is normative for trust, evidence, implementation quality, human review, and handoffs. The task's `issue_number`, top-level Objective, and deterministically authorized `rework.requirements` are trusted controls. Reviewer requirements bound the correction but cannot widen the Objective or override workflow controls.

## Workflow-specific execution

1. Read `git diff origin/main...HEAD` before editing so you amend the current work instead of restating it.
2. Address every reviewer requirement that can be satisfied safely. Keep the diff to that correction and its tests; report any unsatisfied requirement explicitly.
3. A `src/**/*.py` behavior change must include a `tests/test_*.py` change. The independent publication gate enforces this when the baseline suite is green.
4. Dependencies are installed for CPython 3.11. Do not run an installer. Run `pytest`, `ruff check .`, and `git diff --check` directly. If the sandbox selects an unsupported interpreter, record that exact result and let the independent CPython gate decide.
5. Use `rg -F` for literal searches. Limit orientation to the summary, existing branch diff, and at most eight focused source/test reads; by tool call 16, edit or report the missing evidence.
6. Review the final diff and `git status --short`, stage every changed file together, and commit on the checked-out PR branch with a concise subject and no literal `\n` sequences.
7. Call `missing_tool` only when no configured tool can complete the correction. Stop immediately after the single terminal `push_to_pull_request_branch` call.

## Required result

Commit your corrections onto the checked-out branch once `pytest`, `ruff check .`, and `git diff --check` have passed on your final edit, then call `push_to_pull_request_branch` exactly once with `pull_request_number` set to the task's `rework.pull_request` value. A verified sandbox interpreter-selection failure is not a reason to discard completed work; report it accurately and let the independent CPython 3.11 gate decide. Summarise which reviewer requirements you addressed, the causal link to the changed behavior, changed files, and only validation actually observed in tool output.

A rework that changes nothing is a failure. If the reviewer requirements cannot be satisfied safely, or the requested change would violate the trust, scope, or status-semantics rules above, do not push: report the blocking reason instead so the run fails visibly for a human.

When the reviewer asks for follow-up work that belongs in a later scheduled session rather than in this pull request, call `create_issue` exactly once instead of pushing. State the requested outcome, why it is out of scope for this PR, and the acceptance criteria a future session would need. Filing that issue is the complete result for such a request; do not also invent a code change to justify a push.

The scheduled selector parses a strict issue template. The follow-up issue body must use these exact headings and place the actionable outcome under `### Objective`:

```markdown
### Priority

Normal

### Objective

<the outcome a future session must deliver>

### Context or acceptance evidence

<why it is separate and the observable acceptance criteria>
```