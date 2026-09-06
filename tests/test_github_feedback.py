import json
import re
from pathlib import Path

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
