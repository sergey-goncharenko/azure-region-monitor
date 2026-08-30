---
name: Scheduled agentic backlog
description: Compare GitHub Agentic Workflows with the current Azure-funded issue coding lane.
on:
  schedule:
    - cron: "23 6 * * *"
  workflow_dispatch:
    inputs:
      target_issue:
        description: "Optional open azure-backlog issue number"
        required: false
        type: string
        default: ""

permissions:
  contents: read
  issues: read
  pull-requests: read

strict: true
imports:
  - shared/agentic-policy.md
concurrency:
  group: scheduled-agentic-backlog
  cancel-in-progress: false

jobs:
  prepare:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
      pull-requests: read
    outputs:
      has_task: ${{ steps.select.outputs.has_task }}
      issue_number: ${{ steps.select.outputs.issue_number }}
      category: ${{ steps.select.outputs.category }}
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
      - name: Fetch eligible issues and open pull requests
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
          gh pr list \
            --repo "$GITHUB_REPOSITORY" \
            --state open \
            --limit 100 \
            --json number,headRefName,body > "$RUNNER_TEMP/open-pulls.json"
      - name: Build one deterministic issue task
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_ISSUE: ${{ inputs.target_issue || '' }}
        run: |
          set -euo pipefail
          args=(
            --issues "$RUNNER_TEMP/azure-backlog-issues.json"
            --repository "$GITHUB_REPOSITORY"
            --max-issues 3
            --output "$RUNNER_TEMP/azure-byok-task-manifest.json"
          )
          if [ -n "$TARGET_ISSUE" ]; then
            if [[ ! "$TARGET_ISSUE" =~ ^[1-9][0-9]*$ ]]; then
              echo "target_issue must be a positive integer." >&2
              exit 2
            fi
            args+=(--target-issue "$TARGET_ISSUE")
          fi
          python scripts/run_azure_backlog_cycle.py "${args[@]}"
      - name: Skip issues that already have an open coding PR
        id: select
        run: |
          set -euo pipefail
          mkdir -p /tmp/gh-aw/agent
          python scripts/filter_azure_agentic_tasks.py \
            --manifest "$RUNNER_TEMP/azure-byok-task-manifest.json" \
            --open-pulls "$RUNNER_TEMP/open-pulls.json" \
            --output /tmp/gh-aw/agent/task.json \
            --github-output "$GITHUB_OUTPUT"
      - name: Ask maintainers to clarify malformed issue objectives
        id: objective-questions
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_URL: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          python scripts/request_azure_backlog_objectives.py \
            --manifest /tmp/gh-aw/agent/task.json \
            --repository "$GITHUB_REPOSITORY" \
            --run-url "$RUN_URL"
      - name: Report objective clarification failure
        if: ${{ steps.objective-questions.outcome == 'failure' }}
        run: |
          echo "::warning::Could not comment on one or more malformed backlog issues; a later run will retry."
          echo "Objective clarification comments failed; malformed issues remain listed in the stable backlog status." \
            >> "$GITHUB_STEP_SUMMARY"
      - name: Publish stable backlog status
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_URL: https://github.com/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          python scripts/publish_azure_backlog_status.py \
            --manifest /tmp/gh-aw/agent/task.json \
            --repository "$GITHUB_REPOSITORY" \
            --run-url "$RUN_URL"
      - name: Publish the selected issue for the outcome follower
        if: ${{ steps.select.outputs.has_task == 'true' }}
        env:
          ISSUE_NUMBER: ${{ steps.select.outputs.issue_number }}
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/agentic-outcome"
          jq -n --arg issue_number "$ISSUE_NUMBER" '{issue_number: $issue_number}' \
            > "$RUNNER_TEMP/agentic-outcome/selection.json"
      # A gh-aw custom job cannot depend on safe_outputs, so the paired
      # agentic-backlog-outcome.yml workflow_run follower records the result.
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: ${{ steps.select.outputs.has_task == 'true' }}
        with:
          name: agentic-backlog-selection
          path: ${{ runner.temp }}/agentic-outcome/selection.json
          retention-days: 1

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

timeout-minutes: 30
# Runs that reached turn 49-50 were cut off by the proxy mid-task, which the Copilot CLI
# reports as a provider 403; the credit ceilings are sized to cover the wider turn budget.
# Temporarily raised for the 2026-08-12 o4-mini/gpt-5.1-codex/o4-mini comparison so a
# run is never truncated by the cap - otherwise the experiment measures the cap, not the model.
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
    # create_pull_request rejects a run with no commits, so the agent has to be able to
    # branch and commit; run 32006961427 finished the work and lost it without these.
    - "git checkout:*"
    - "git switch:*"
    - "git branch:*"
    - "git add:*"
    - "git commit:*"
    - "jq:*"
    - "rg:*"
    - "python3:*"
    - "pytest:*"
    - "ruff:*"
  github:
    toolsets: [issues, repos, pull_requests]
  timeout: 300

steps:
  - name: Install pinned ripgrep
    shell: bash
    run: |
      set -euo pipefail
      if command -v rg >/dev/null 2>&1; then
        exit 0
      fi
      version="15.2.0"
      target="x86_64-unknown-linux-musl"
      archive="ripgrep-${version}-${target}.tar.gz"
      archive_path="${RUNNER_TEMP}/${archive}"
      extract_dir="${RUNNER_TEMP}/ripgrep-${version}"
      bin_dir="${RUNNER_TEMP}/gh-aw/bin"
      rm -rf "$extract_dir"
      mkdir -p "$extract_dir" "$bin_dir"
      curl --fail --location --silent --show-error \
        --retry 3 \
        --retry-all-errors \
        --connect-timeout 10 \
        --max-time 60 \
        "https://github.com/BurntSushi/ripgrep/releases/download/${version}/${archive}" \
        --output "$archive_path"
      printf '%s  %s\n' \
        '33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c' \
        "$archive_path" | sha256sum --check -
      tar -xzf "$archive_path" -C "$extract_dir"
      install -m 0755 "${extract_dir}/ripgrep-${version}-${target}/rg" "${bin_dir}/rg"
      echo "$bin_dir" >> "$GITHUB_PATH"
      "${bin_dir}/rg" --version
  - name: Restore deterministic issue task
    env:
      TASK_B64: ${{ needs.prepare.outputs.task_b64 }}
      SUMMARY_B64: ${{ needs.prepare.outputs.summary_b64 }}
    run: |
      set -euo pipefail
      mkdir -p /tmp/gh-aw/agent
      printf '%s' "$TASK_B64" | base64 --decode > /tmp/gh-aw/agent/task.json
      printf '%s' "$SUMMARY_B64" | base64 --decode > /tmp/gh-aw/agent/task-summary.md
  - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
    with:
      python-version: "3.11"
  - run: |
      python -m pip install -e .
      python -m pip install "httpx>=0.27,<1" "pytest>=8.2,<9" "ruff>=0.6,<1"

safe-outputs:
  max-patch-size: 1024
  create-pull-request:
    title-prefix: "[agentic] "
    labels: [scheduled-agent]
    draft: true
    fallback-as-issue: false
    auto-close-issue: false
    normalize-closing-keywords: true
    if-no-changes: error
    allowed-branches:
      - agentic/issue-*
    max-patch-files: 50
    max-patch-size: 1024
    excluded-files:
      - .github/workflows/shared/agentic-policy.md
      - data/**
      - public/api/**
      - public/*.html
    protected-files: request_review
  threat-detection:
    steps:
      - name: Install pinned ripgrep
        if: always() && steps.detection_guard.outputs.run_detection == 'true'
        shell: bash
        run: |
          set -euo pipefail
          if command -v rg >/dev/null 2>&1; then
            exit 0
          fi
          version="15.2.0"
          target="x86_64-unknown-linux-musl"
          archive="ripgrep-${version}-${target}.tar.gz"
          archive_path="${RUNNER_TEMP}/${archive}"
          extract_dir="${RUNNER_TEMP}/ripgrep-${version}"
          bin_dir="${RUNNER_TEMP}/gh-aw/bin"
          rm -rf "$extract_dir"
          mkdir -p "$extract_dir" "$bin_dir"
          curl --fail --location --silent --show-error \
            --retry 3 \
            --retry-all-errors \
            --connect-timeout 10 \
            --max-time 60 \
            "https://github.com/BurntSushi/ripgrep/releases/download/${version}/${archive}" \
            --output "$archive_path"
          printf '%s  %s\n' \
            '33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c' \
            "$archive_path" | sha256sum --check -
          tar -xzf "$archive_path" -C "$extract_dir"
          install -m 0755 "${extract_dir}/ripgrep-${version}-${target}/rg" "${bin_dir}/rg"
          echo "$bin_dir" >> "$GITHUB_PATH"
          "${bin_dir}/rg" --version
    max-ai-credits: 200
    prompt: |
      Reject patches that do not directly address the trusted Objective or cited live error evidence. Also reject unrelated bulk edits, generated snapshot edits, weakened status semantics, disabled tests, hidden network behavior, or changes that conflate provider-specific contracts.
    post-steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      # Blocking checks protect the repository. Quality findings are advisory and travel
      # with the draft pull request, because a discarded run leaves the same issue at the
      # front of the queue and produces nothing a human can review.
      - name: Apply candidate patch and record advisory validation
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/validation"
          python -m pip install -e .
          python -m pip install "httpx>=0.27,<1" "pytest>=8.2,<9" "ruff>=0.6,<1"
          patch_file="$(find /tmp/gh-aw/threat-detection -maxdepth 1 -type f -name 'aw*.patch' -print -quit)"
          if [ -z "$patch_file" ]; then
            echo "No candidate patch was produced; this is a noop run."
            exit 0
          fi
          git apply "$patch_file"
          git diff --name-only > "$RUNNER_TEMP/validation/changed-files.txt"
          if grep -Eq '^scripts/check(_[a-z]+)?\.py$' "$RUNNER_TEMP/validation/changed-files.txt"; then
            echo "The scripts/check*.py validators are the gate itself and are not agent-editable." >&2
            exit 1
          fi
          check_status=0
          python scripts/check.py > "$RUNNER_TEMP/validation/check.log" 2>&1 || check_status=$?
          python scripts/summarize_agentic_validation.py \
            --changed-files "$RUNNER_TEMP/validation/changed-files.txt" \
            --check-status "$check_status" \
            --check-log "$RUNNER_TEMP/validation/check.log" \
            --run-url "https://github.com/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}" \
            --output-dir "$RUNNER_TEMP/validation" \
            >> "$GITHUB_STEP_SUMMARY"
          cat "$RUNNER_TEMP/validation/validation.md" >> "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        if: ${{ always() }}
        with:
          name: agentic-validation
          path: ${{ runner.temp }}/validation
          retention-days: 7
          if-no-files-found: ignore
---

# Azure Regional Feature Availability Monitor issue agent

Start by reading `/tmp/gh-aw/agent/task-summary.md`. It identifies exactly one deterministically selected open `azure-backlog` issue and explains why it won the issue queue. If it contains live unknown evidence, that evidence enriches the selected source issue; it did not create or select a task independently.

Read `/tmp/gh-aw/agent/task.json` only if the summary lacks evidence required for a decision. It is formatted JSON; use one targeted `jq` query rather than dumping or repeatedly reading the full file.

The imported **Human-Agent CI/CD Policy** is normative for trust, evidence, implementation quality, human review, and handoffs. The task's `kind`, `category`, `issue_number`, top-level Objective, recurrence flag, and test list are trusted controls. You may inspect and edit the full repository; `allowed_paths` are relevance hints, not a write boundary.

## Workflow-specific execution

- Implement one atomic, independently reviewable correction.
- `pytest` and `ruff` are not importable from this sandbox. Do not report that as a blocker. Run `python scripts/check_css.py` and `git diff --check`; the independent gate applies the patch and runs `python scripts/check.py` under CPython 3.11.
- Use `rg -F` for literal searches. Do not retry malformed expressions or out-of-range reads.
- If roughly forty tool calls pass without a justified edit, call `noop` and identify the missing evidence.
- Before publishing, review the final diff, then run `git checkout -b agentic/issue-<issue_number>`, `git add -A`, and one `git commit` with a concise single-line subject. The safe output rejects an uncommitted tree with "no commits were found".
- If a command is denied, use an allowed equivalent. Call `missing_tool` only when no configured tool can complete the task, and never alongside `create_pull_request` or `noop`.
- Stop immediately after the single terminal `create_pull_request` or `noop` call.

## Required result

If you implemented a safe correction, commit it on `agentic/issue-<issue_number>` and call `create_pull_request` exactly once. Publish even when something still looks unresolved: an imperfect draft is reviewable and repairable, an abandoned run is not. Never abandon completed work because a command was denied or a tool was missing - say so in the PR body and publish anyway. State plainly what you observed failing. Reserve `noop` for the case where no change is justified at all.

When you do publish:

- use branch `agentic/issue-<issue_number>`;
- make the PR a small draft suitable for human review;
- include `<!-- azure-agentic-source:issue-<issue_number> -->` and `Source issue: #<issue_number>` in the body;
- explain source-issue queue selection, the causal link from Objective/evidence to changed behavior, implementation, alternatives and risks, changed files, and only validation actually observed in tool output;
- include a closing keyword only when `recurring` is false.

Call `noop` exactly once, with a concise reason, only when no safe change is justified, the task is already satisfied, or the evidence required to act is unavailable. Never create a placeholder PR.
