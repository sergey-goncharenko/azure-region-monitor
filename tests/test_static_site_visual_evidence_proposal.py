from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/static-site-visual-evidence.yml"


def test_visual_evidence_workflow_is_in_workflow_paths():
    assert WORKFLOW.is_file()
    assert not (REPO_ROOT / "workflow-proposals/static-site-visual-evidence.yml").exists()


def test_visual_evidence_workflow_captures_deterministic_before_and_after_sites():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "The head data is intentionally used for both builds" in workflow
    assert 'cp -a "$HEAD_DIR/$path" "$BASE_DIR/$path"' in workflow
    assert 'before-site' in workflow
    assert 'after-site' in workflow
    assert '[["before", 4173], ["after", 4174]]' in workflow
    assert 'status: beforeImage.equals(afterImage) ? "unchanged" : "changed"' in workflow
    assert 'status: "added"' in workflow
    assert 'status: "removed"' in workflow


def test_visual_evidence_workflow_uploads_paired_playwright_screenshots():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Cache Playwright tooling" in workflow
    assert ".cache/static-site-browser/node_modules" in workflow
    assert "node22-static-site-visual-evidence-playwright-v1-55-0" in workflow
    assert "grep -q '\"version\": \"1.55.0\"'" in workflow
    assert "playwright@1.55.0" in workflow
    assert "npx --prefix \"$browser_dir\" playwright install chromium" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "static-site-visual-evidence-pr-" in workflow
    assert "retention-days: 14" in workflow
