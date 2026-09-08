from pathlib import Path
import json
import shutil
import subprocess
import textwrap

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/static-site-visual-evidence.yml"


def test_visual_evidence_workflow_is_in_workflow_paths():
    assert WORKFLOW.is_file()
    assert not (REPO_ROOT / "workflow-proposals/static-site-visual-evidence.yml").exists()


def test_visual_evidence_workflow_captures_deterministic_before_and_after_sites():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "branches: [main]" in workflow
    assert "run-name:" in workflow
    assert 'core.setOutput("comparison_mode", "reference-smoke")' in workflow
    assert 'core.setOutput("base_sha", context.sha)' in workflow
    assert 'core.setOutput("head_sha", context.sha)' in workflow
    assert 'core.setOutput("comparison_mode", "pr-comparison")' in workflow
    assert "pr.base.sha, pr.head.sha" in workflow
    assert "needs.resolve.outputs.base_sha" in workflow
    assert "needs.resolve.outputs.head_sha" in workflow
    assert 'for label in before after' in workflow
    assert 'cd "$source_dir"' in workflow
    assert '--snapshot "$INPUT_DIR/snapshots/latest.json"' in workflow
    assert '--history "$INPUT_DIR/history"' in workflow
    assert 'AI_SUMMARY_ENABLED: "0"' in workflow
    assert "prepare_visual_evidence.py" in workflow
    assert "capture_static_site_evidence.mjs" in workflow


def test_all_checkouts_stay_inside_the_workspace_and_tooling_uses_workflow_revision():
    import re

    workflow = WORKFLOW.read_text(encoding="utf-8")
    paths = re.findall(r"uses: actions/checkout@\S+\n\s+with:\n\s+path: (.+)", workflow)
    assert paths == ["workflow", "head", "base"]
    assert "ref: ${{ github.workflow_sha }}" in workflow
    assert "BASE_DIR: ${{ github.workspace }}/base" in workflow
    assert "HEAD_DIR: ${{ github.workspace }}/head" in workflow
    assert workflow.count("persist-credentials: false") == 3
    assert "pull_request_target" not in workflow
    assert "pull-requests: write" not in workflow
    assert "contents: write" not in workflow


def test_visual_evidence_workflow_uploads_paired_playwright_screenshots():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Cache Playwright tooling" in workflow
    assert ".cache/static-site-browser/node_modules" in workflow
    assert "node22-static-site-visual-evidence-playwright-v1-55-0" in workflow
    assert "grep -q '\"version\": \"1.55.0\"'" in workflow
    assert "playwright@1.55.0" in workflow
    assert "npx --prefix \"$browser_dir\" playwright install --with-deps chromium" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "format('pr-{0}', needs.resolve.outputs.pr_number)" in workflow
    assert "format('ref-{0}', github.sha)" in workflow
    assert "retention-days: 14" in workflow
    assert "if: always()" in workflow
    assert "static-site-evidence/manifest.json" in workflow
    assert "static-site-evidence/index.html" in workflow
    assert "static-site-evidence/*-build.log" in workflow
    assert "steps.builds.outcome == 'failure'" in workflow
    assert "steps.screenshots.outcome == 'failure'" in workflow
    assert "this is not a successful comparison" in workflow


def test_resolver_separates_current_ref_smoke_from_frozen_pr_commits():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute the workflow's GitHub-script resolver.")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = textwrap.dedent(workflow.split("          script: |\n", 1)[1].split("\n  capture:", 1)[0])
    harness = r"""
const fs = require("node:fs");
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const resolve = new AsyncFunction("context", "github", "core", fs.readFileSync(0, "utf8"));
const sha = "a".repeat(40), other = "b".repeat(40);
const pr = {number: 120, base: {sha, repo: {full_name: "org/repo"}}, head: {sha: other}};
const cases = [
  {eventName: "push", payload: {}},
  {eventName: "workflow_dispatch", payload: {inputs: {}}},
  {eventName: "workflow_dispatch", payload: {inputs: {pr_number: "120"}}},
  {eventName: "pull_request", payload: {pull_request: pr}},
  {eventName: "workflow_dispatch", payload: {inputs: {pr_number: "0"}}},
];
(async () => {
  const results = [];
  for (const input of cases) {
    let apiCalls = 0;
    const output = {};
    const github = {rest: {pulls: {get: async () => { apiCalls++; return {data: pr}; }}}};
    try {
      await resolve({...input, sha, repo: {owner: "org", repo: "repo"}}, github,
        {setOutput: (key, value) => { output[key] = String(value); }});
      results.push({output, apiCalls});
    } catch (error) { results.push({error: error.message, apiCalls}); }
  }
  console.log(JSON.stringify(results));
})();
"""
    result = subprocess.run(
        [node, "-e", harness], input=script, text=True, encoding="utf-8",
        capture_output=True, check=True, timeout=20,
    )
    results = json.loads(result.stdout)
    for item in results[:2]:
        assert item["apiCalls"] == 0
        assert item["output"] == {
            "pr_number": "", "base_sha": "a" * 40, "head_sha": "a" * 40,
            "comparison_mode": "reference-smoke",
        }
    for item in results[2:4]:
        assert item["output"]["base_sha"] == "a" * 40
        assert item["output"]["head_sha"] == "b" * 40
        assert item["output"]["comparison_mode"] == "pr-comparison"
        assert item["output"]["pr_number"] == "120"
    assert results[2]["apiCalls"] == 1
    assert results[3]["apiCalls"] == 0
    assert "positive PR number" in results[4]["error"]
