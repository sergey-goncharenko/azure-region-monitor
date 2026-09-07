from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/static-site-visual-evidence.yml"


def test_visual_evidence_workflow_is_in_workflow_paths():
    assert WORKFLOW.is_file()
    assert not (REPO_ROOT / "workflow-proposals/static-site-visual-evidence.yml").exists()


def test_visual_evidence_workflow_captures_deterministic_before_and_after_sites():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
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
    assert "static-site-visual-evidence-pr-" in workflow
    assert "retention-days: 14" in workflow
    assert "if: always()" in workflow
    assert "static-site-evidence/manifest.json" in workflow
    assert "static-site-evidence/index.html" in workflow
    assert "static-site-evidence/*-build.log" in workflow
    assert "steps.builds.outcome == 'failure'" in workflow
    assert "steps.screenshots.outcome == 'failure'" in workflow
    assert "this is not a successful comparison" in workflow
