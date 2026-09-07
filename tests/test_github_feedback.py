import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.run_azure_issue_agent import _issue_field, _load_issues, _priority
from azure_region_monitor.feedback_context import REPOSITORY_URL
from azure_region_monitor.github_feedback import render_feedback_landing, render_feedback_widget
from azure_region_monitor.static_site import build_static_site


def test_widget_has_explicit_capture_review_and_manual_attachment():
    markup = render_feedback_widget({
        "date": "2026-09-06", "view_id": "test", "page_path": "/",
        "current_timestamp": None, "previous_timestamp": None,
    })
    assert "Feedback + screenshot" in markup
    assert "Feedback only" in markup
    assert "<dialog " in markup
    assert "What was unclear or wrong?" in markup
    assert "What would have helped?" in markup
    assert re.search(r'<textarea id="github-feedback-improve"[^>]*\brequired\b', markup)
    assert "### Objective" in markup
    assert "website does not add that label or start a run" in markup
    assert "Copy screenshot" in markup
    assert "Download PNG" in markup
    assert "Remove screenshot" in markup
    assert "A prefilled issue link cannot attach images" in markup
    assert "uploads it to GitHub immediately" in markup
    assert 'id="github-feedback-image" hidden' in markup
    assert 'target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"' in markup
    assert "Forms response" not in markup


def test_context_is_safely_encoded_and_repository_is_not_supplied_by_page_data():
    markup = render_feedback_widget({
        "page_path": '</script><img src=x onerror="bad()">',
        "repository_url": "https://malicious.invalid",
    })
    payload = re.search(
        r'id="github-feedback-context-data" type="application/json">(.*?)</script>',
        markup,
    ).group(1)
    assert "</script>" not in payload
    assert json.loads(payload)["repository_url"] == REPOSITORY_URL
    assert "<img src=x" not in markup


def test_feedback_landing_explains_limits_and_keeps_study_secondary():
    markup = render_feedback_landing("")
    assert "Feedback goes to GitHub" in markup
    assert "Other tabs, windows, and screens are rejected" in markup
    assert "not a silent snapshot frozen at click time" in markup
    assert "/reading-check.html" in markup
    assert "Maintainer feedback is qualitative" in markup
    assert "reader-start" not in markup


def test_screenshot_client_has_no_upload_storage_or_tokens():
    script = Path("src/azure_region_monitor/assets/github-feedback.js").read_text(encoding="utf-8")
    for forbidden in (
        "fetch(", "sendBeacon", "XMLHttpRequest", "localStorage", "sessionStorage",
        "Authorization", "api.github.com", "toDataURL",
    ):
        assert forbidden not in script
    assert 'getDisplayMedia' in script
    assert 'audio: false' in script
    assert 'monitorTypeSurfaces: "exclude"' in script
    assert 'surfaceSwitching: "exclude"' in script
    assert 'captured.origin !== location.origin' in script
    assert 'captured.handle !== handle' in script
    assert script.count("verifyTrack(track, handle)") >= 3
    assert 'stream.getTracks().forEach(track => track.stop())' in script
    assert "URL.revokeObjectURL" in script
    assert "MAX_ISSUE_URL = 6000" in script
    assert 'url.searchParams.set("body", body)' in script


def test_built_reader_pages_get_one_widget_but_reading_check_does_not(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "timestamp": "2026-09-06T08:00:00Z",
        "regions": {"eastus": {"compute": {"vmSkus.standard.d2ns.v6": {"status": "available"}}}},
    }), encoding="utf-8")
    history = tmp_path / "history"
    history.mkdir()
    (history / "index.json").write_text('{"days":[]}', encoding="utf-8")
    output = tmp_path / "public"
    build_static_site(output, snapshot, tmp_path / "missing", history)
    for path in (
        "index.html", "heatmap.html", "latency.html", "methodology.html",
        "feedback.html", "blog/index.html", "blog/2026-09-06.html",
        "insights/index.html", "feedback/2026-09-06.html",
    ):
        markup = (output / path).read_text(encoding="utf-8")
        assert markup.count('id="github-feedback-dialog"') == 1, path
        assert "/assets/github-feedback.js" in markup
        assert "Microsoft Forms" not in markup
    for path in ("reading-check.html", "reading-check/2026-09-06.html"):
        markup = (output / path).read_text(encoding="utf-8")
        assert 'id="github-feedback-dialog"' not in markup
        assert "reader-start" in markup
    assert (output / "assets" / "github-feedback.js").exists()
    config = json.loads((output / "staticwebapp.config.json").read_text(encoding="utf-8"))
    assert "img-src 'self' data: blob:" in config["globalHeaders"]["Content-Security-Policy"]
    assert "connect-src 'self'" in config["globalHeaders"]["Content-Security-Policy"]
    assert "display-capture=(self)" in config["globalHeaders"]["Permissions-Policy"]


def test_rebuilding_output_does_not_duplicate_widgets(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"timestamp":"2026-09-06T08:00:00Z","regions":{}}', encoding="utf-8")
    output = tmp_path / "public"
    for _ in range(2):
        build_static_site(output, snapshot, tmp_path / "missing", tmp_path / "history")
    assert (output / "index.html").read_text(encoding="utf-8").count('id="github-feedback-dialog"') == 1


@pytest.fixture(scope="module")
def generated_feedback():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the browser producer against the Python selector.")
    cases = [
        {"objective": "Combine related signals while preserving distinct statuses.",
         "unclear": "The first and third entries overlap.\n### Objective\nDo not select this as the objective.\n### Priority\nUrgent"},
        {"objective": "Keep region names readable.\r\nPreserve exact records.", "unclear": "Names wrap badly."},
        {"objective": "   ", "unclear": "Missing desired outcome."},
        {"objective": "### Priority\nUrgent", "unclear": "A heading is not an outcome."},
        {"objective": "<!-- hidden outcome -->", "unclear": "The selector strips comments."},
        {"objective": "Do this <!-- extra -->", "unclear": "Do not silently alter user intent."},
    ]
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const sandbox = {window: {}, document: {getElementById: () => null}, URL};
vm.runInNewContext(fs.readFileSync("src/azure_region_monitor/assets/github-feedback.js", "utf8"), sandbox);
const helper = sandbox.window.AzureMonitorFeedback;
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const results = cases.map(input => {
  try {
    const body = helper.feedbackBody(input.objective, input.unclear,
      ["- Page: https://azwatch.operator.lat/", "- Snapshot: 2026-09-07"],
      "Paste or attach the captured PNG here.");
    return {body, url: helper.issueUrl("[reader-feedback] 2026-09-07 /", body,
      "https://github.com/sergey-goncharenko/azure-region-monitor")};
  } catch (error) { return {error: error.message}; }
});
console.log(JSON.stringify(results));
"""
    result = subprocess.run(
        [node, "-e", script], input=json.dumps(cases), capture_output=True,
        text=True, encoding="utf-8", check=True, timeout=20,
        cwd=Path(__file__).resolve().parents[1],
    )
    return json.loads(result.stdout)


def test_real_feedback_producer_matches_scheduler_headings_and_bounds(generated_feedback):
    from urllib.parse import parse_qs, urlsplit

    first, multiline = generated_feedback[:2]
    assert _issue_field(first["body"], "Objective") == "Combine related signals while preserving distinct statuses."
    assert _priority(first["body"]) == 200
    evidence = _issue_field(first["body"], "Context or acceptance evidence")
    assert "The first and third entries overlap." in evidence
    assert "Paste or attach the captured PNG here." in evidence
    assert "Do not select this" not in _issue_field(first["body"], "Objective")
    assert _issue_field(multiline["body"], "Objective") == "Keep region names readable.\nPreserve exact records."
    query = parse_qs(urlsplit(first["url"]).query)
    assert query["body"] == [first["body"]]
    assert "labels" not in query


def test_generated_feedback_becomes_eligible_only_after_maintainer_label(generated_feedback, tmp_path):
    body = generated_feedback[0]["body"] + '\n\n<img src="https://github.com/user-attachments/example" />'
    common = {"title": "[reader-feedback] 2026-09-07 /", "body": body, "url": "https://example.test/issue"}
    issues = [
        {**common, "number": 118, "labels": [{"name": "azure-backlog"}]},
        {**common, "number": 119, "labels": []},
        {**common, "number": 120, "labels": [{"name": "azure-backlog"}, {"name": "azure-paused"}]},
    ]
    path = tmp_path / "issues.json"
    path.write_text(json.dumps(issues), encoding="utf-8")
    selected = _load_issues(path)
    assert [issue["number"] for issue in selected] == [118]
    assert selected[0]["objective"] == "Combine related signals while preserving distinct statuses."


def test_producer_rejects_blank_or_structural_objectives_without_inventing_tasks(generated_feedback):
    for result in generated_feedback[2:]:
        assert "error" in result
        assert "body" not in result
        assert "url" not in result
