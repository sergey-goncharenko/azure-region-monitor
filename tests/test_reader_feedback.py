import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from azure_region_monitor.briefing import build_briefing, compact_briefing
from azure_region_monitor.feedback_context import REPOSITORY_URL
from azure_region_monitor.models import Snapshot
from azure_region_monitor.reader_feedback import (
    measurement_context,
    presentation_id,
    render_reading_check_page,
)

READER_SCRIPT = Path("src") / "azure_region_monitor" / "assets" / "reader-feedback.js"


def reader_day():
    feature = "vmSkus.standard.d2ns.v6"
    before = Snapshot.model_validate({
        "timestamp": "2026-09-05T08:00:00Z",
        "regions": {"eastus": {"compute": {feature: {"status": "unavailable"}}}},
    })
    after = Snapshot.model_validate({
        "timestamp": "2026-09-06T08:00:00Z",
        "regions": {"eastus": {"compute": {feature: {"status": "available"}}}},
    })
    return {
        "date": "2026-09-06", "change_path": "changes/2026-09-06.json",
        "briefing": compact_briefing(build_briefing(after, before)),
    }


def test_optional_reading_check_retains_local_export_without_forms_config():
    page = render_reading_check_page(reader_day(), "", "test-view")
    assert "not the main feedback path" in page
    assert 'href="/feedback.html"' in page
    assert "Founder or repeat-reader observations are qualitative" in page
    assert "Microsoft Forms" not in page
    assert not READER_SCRIPT.with_suffix(".json").exists()
    assert 'id="reader-copy"' in page
    assert 'id="reader-download"' in page


def test_reading_check_is_local_opt_in_with_explicit_github_draft_handoff():
    page = render_reading_check_page(reader_day(), "", "test-view")
    assert 'id="reader-reading" hidden' in page
    assert 'id="reader-answers" hidden' in page
    assert 'id="reader-export" hidden' in page
    assert "15-second reading check" in page
    assert "No analytics, cookies, background submissions" in page
    assert "not submitted" in page
    assert "Public feedback" in page
    assert "attachments upload immediately" in page
    assert "never asks for a token" in page
    assert "No screenshot capture is offered in this timed check" in page
    link = re.search(r'<a id="reader-draft"[^>]+>', page).group()
    assert 'href="#reader-export"' in link
    assert 'target="_blank"' in link
    assert 'rel="noopener noreferrer"' in link
    assert 'referrerpolicy="no-referrer"' in link
    assert "Open GitHub draft" in page
    assert "Only your final Submit on GitHub" in page
    assert "No raw JSON packet goes in the URL" in page
    assert "iframe" not in page
    assert '<form id="reader-response">' in page
    assert 'action="https:' not in page
    assert page.count('aria-label="Daily change briefing"') == 1
    helper = '<script src="/assets/github-feedback.js" defer></script>'
    study = '<script src="/assets/reader-feedback.js" defer></script>'
    assert page.index(helper) < page.index(study)


def test_reading_check_embeds_shared_context_safely():
    view_id = "</script><script>alert(1)</script>"
    page = render_reading_check_page(reader_day(), "", view_id)
    encoded = re.search(
        r'<script id="reader-context" type="application/json">(.*?)</script>', page,
    ).group(1)
    assert json.loads(encoded) == measurement_context(reader_day(), view_id)
    assert view_id not in page
    assert json.loads(encoded)["repository_url"] == REPOSITORY_URL


def test_case_fingerprint_does_not_change_when_only_presentation_changes():
    day = reader_day()
    original = measurement_context(day, "before")
    day["briefing"]["groups"][0]["examples"][0]["feature_note"] = "Different explanation."
    modified = measurement_context(day, "after")
    assert original["case_id"] == modified["case_id"]
    assert original["view_id"] != modified["view_id"]
    day["briefing"]["counts"]["delistings"] = 1
    assert measurement_context(day, "after")["case_id"] != original["case_id"]


def test_measurement_context_is_bounded_and_has_no_answers_or_identity():
    context = measurement_context(reader_day(), "test-view")
    assert context["protocol"] == "reader-check-v1"
    assert context["reading_budget_ms"] == 15000
    assert context["repository_url"] == REPOSITORY_URL
    assert re.fullmatch("[a-f0-9]{16}", context["case_id"])
    assert not ({"email", "user", "expected_answers", "name", "subscription_id"} & context.keys())
    assert len(json.dumps(context)) < 600
    assert len(presentation_id()) == 16


def test_missing_briefing_is_not_presented_as_a_measurable_case():
    page = render_reading_check_page(None, "", "test-view")
    assert "not available for a reading check" in page
    assert "reader-context" not in page


def test_reading_check_assets_have_no_automatic_submission_storage_or_capture():
    script = READER_SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "fetch(", "sendBeacon", "XMLHttpRequest", "localStorage", "sessionStorage",
        "document.cookie", "getDisplayMedia", "getUserMedia", "window.open(",
        "Microsoft Forms", "4000",
    ):
        assert forbidden not in script
    assert 'addEventListener("visibilitychange"' in script
    assert "candidate_for_scoring" in script
    assert "performance.now()" in script


def test_static_build_generates_separate_optional_reading_check_pages(tmp_path):
    from azure_region_monitor.static_site import build_static_site

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "timestamp": "2026-09-06T08:00:00Z",
        "regions": {"eastus": {"compute": {"vmSkus.standard.d2ns.v6": {"status": "available"}}}},
    }), encoding="utf-8")
    history = tmp_path / "history"
    history.mkdir()
    (history / "index.json").write_text(json.dumps({"days": []}), encoding="utf-8")
    output = tmp_path / "public"
    build_static_site(output, snapshot, tmp_path / "none", history)
    assert (output / "feedback.html").exists()
    assert (output / "reading-check.html").exists()
    assert (output / "reading-check" / "2026-09-06.html").exists()
    assert (output / "assets" / "reader-feedback.js").exists()
    assert (output / "assets" / "github-feedback.js").exists()
    assert not (output / "assets" / "reader-feedback.json").exists()
    assert 'id="reader-response"' not in (output / "feedback.html").read_text(encoding="utf-8")
    assert 'id="reader-response"' in (
        output / "reading-check" / "2026-09-06.html"
    ).read_text(encoding="utf-8")


READER_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const scenario = input.scenario;
const elements = new Map();
const documentEvents = {};
const helperCalls = [];
const downloads = [];
let copied = null;
let now = 1000;
let timer = null;
class Element {
  constructor() {
    this.listeners = {};
    this.value = "";
    this.hidden = true;
    this.checked = false;
    this.href = "#reader-export";
    this.textContent = "";
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  fire(name, event = {}) { return this.listeners[name](event); }
  focus() {}
  select() {}
  scrollIntoView() {}
  querySelectorAll() { return []; }
  reportValidity() { return true; }
  click() { downloads.push({href: this.href, filename: this.download}); }
}
function get(id) {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
}
globalThis.document = {
  hidden: false,
  getElementById: id => get(id.replace(/^reader-/, "")),
  addEventListener: (name, callback) => { documentEvents[name] = callback; },
  createElement: () => new Element(),
};
globalThis.window = globalThis;
globalThis.innerWidth = 1000;
Object.defineProperty(globalThis, "performance", {value: {now: () => now}});
Object.defineProperty(globalThis, "crypto", {value: {randomUUID: () => "test-attempt"}});
Object.defineProperty(globalThis, "navigator", {
  value: {clipboard: {writeText: async value => { copied = value; }}},
});
globalThis.setTimeout = callback => { timer = callback; return 1; };
globalThis.setInterval = () => 1;
globalThis.clearTimeout = globalThis.clearInterval = () => {};
let downloadBlob = null;
URL.createObjectURL = blob => { downloadBlob = blob; return "blob:local-record"; };
URL.revokeObjectURL = () => {};
get("context").textContent = JSON.stringify(input.context);
get("role").value = "engineer";
get("prior").value = scenario.prior || "no";
if (!scenario.missing_helper) {
  globalThis.AzureMonitorFeedback = {
    issueUrl(title, body, repositoryUrl) {
      helperCalls.push({title, body, repositoryUrl});
      if (scenario.helper_error) throw new Error(scenario.helper_error);
      const url = `${repositoryUrl}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
      if (url.length > 6000) throw new Error("The GitHub draft URL exceeds 6000 characters.");
      return url;
    },
  };
}
vm.runInThisContext(fs.readFileSync(input.script, "utf8"));
(async () => {
  get(scenario.method === "qualitative" ? "skip" : "start").fire("click");
  now += scenario.elapsed ?? 1200;
  if (scenario.method !== "qualitative") {
    if (scenario.end === "budget") timer();
    else if (scenario.end === "interrupted") {
      document.hidden = true;
      documentEvents.visibilitychange();
      document.hidden = false;
    } else get("ready").fire("click");
  }
  if (scenario.answering_interrupted) {
    document.hidden = true;
    documentEvents.visibilitychange();
    document.hidden = false;
  }
  const values = {
    main: "One VM size gained an East US listing.",
    region: "East US", proof: "observations", recovery: "no",
    feature: "Exact capabilities remain unverified.", clarity: "4",
    confusion: "Explain listing evidence.",
    ...(scenario.answers || {}),
  };
  for (const [name, value] of Object.entries(values)) get(name).value = value;
  get("helped").checked = !!scenario.helped;
  get("response").fire("submit", {preventDefault() {}});
  const packetText = get("packet").value;
  const callsBeforeClick = helperCalls.length;
  let prevented = false;
  get("draft").fire("click", {preventDefault() { prevented = true; }});
  const href = get("draft").href;
  const draftStatus = get("draft-status").textContent;
  await get("copy").fire("click");
  get("download").fire("click");
  const result = {
    packet: JSON.parse(packetText), packetText, callsBeforeClick, helperCalls,
    href, prevented, draftStatus, exportHidden: get("export").hidden,
    copied, downloads, downloadText: await downloadBlob.text(),
  };
  if (scenario.edit_after) {
    get("response").fire("input");
    result.editedExportHidden = get("export").hidden;
    result.editedHref = get("draft").href;
    result.editedPrevented = false;
    get("draft").fire("click", {preventDefault() { result.editedPrevented = true; }});
  }
  process.stdout.write(JSON.stringify(result));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def run_study(**scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to exercise the browser-local reading-check script.")
    completed = subprocess.run(
        [node, "-e", READER_HARNESS],
        input=json.dumps({
            "context": measurement_context(reader_day(), "test-view"),
            "script": str(READER_SCRIPT.resolve()),
            "scenario": scenario,
        }),
        text=True, capture_output=True, encoding="utf-8", timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_github_summary_is_generated_only_on_click_and_uses_shared_destination():
    result = run_study()
    assert result["callsBeforeClick"] == 0
    call, = result["helperCalls"]
    assert call["repositoryUrl"] == REPOSITORY_URL
    assert call["title"] == "Optional reading check: 2026-09-06"
    body = call["body"]
    assert "## Optional reading check" in body
    assert "One VM size gained an East US listing." in body
    assert "Only the catalog or measurement observations stated" in body
    assert result["packet"]["case_id"] in body
    assert "test-view" in body
    assert "1200 ms" in body
    assert "candidate for human comprehension review" in body
    assert '"answers":' not in body
    assert result["packetText"] not in body
    assert result["prevented"] is False
    assert result["href"].startswith(REPOSITORY_URL + "/issues/new?")
    assert len(result["href"]) <= 6000
    assert result["copied"] == result["packetText"]
    assert json.loads(result["downloadText"]) == result["packet"]


@pytest.mark.parametrize("scenario", [
    {"prior": "yes"},
    {"end": "interrupted"},
    {"answering_interrupted": True},
    {"helped": True},
    {"end": "budget", "elapsed": 15300},
    {"method": "qualitative"},
])
def test_timing_and_eligibility_remain_separate_from_qualitative_feedback(scenario):
    result = run_study(**scenario)
    assert result["packet"]["candidate_for_scoring"] is False
    assert "qualitative/repeat-exposure only" in result["helperCalls"][0]["body"]
    if scenario.get("method") == "qualitative":
        assert result["packet"]["reading_elapsed_ms"] is None
        assert result["packet"]["end_reason"] == "skipped"
    if scenario.get("end") == "budget":
        assert result["packet"]["reading_elapsed_ms"] == 15300
        assert result["packet"]["timer_overrun_ms"] == 300


def test_overlong_draft_does_not_limit_or_truncate_local_json_export():
    answer = "\x01" * 500
    result = run_study(answers={
        "main": answer, "confusion": answer, "feature": answer[:400], "region": answer[:200],
    })
    assert len(result["packetText"]) > 4000
    assert result["packet"]["answers"]["main_change"] == answer
    assert result["packet"]["answers"]["confusion"] == answer
    assert result["prevented"] is True
    assert result["exportHidden"] is False
    assert result["href"] == "#reader-export"
    assert "6000 characters" in result["draftStatus"]
    assert "Nothing was truncated or submitted" in result["draftStatus"]
    assert result["copied"] == result["packetText"]
    assert json.loads(result["downloadText"]) == result["packet"]
    assert result["downloads"][0]["filename"].endswith(".json")


@pytest.mark.parametrize("scenario", [
    {"helper_error": "Invalid GitHub repository URL."},
    {"missing_helper": True},
])
def test_draft_helper_failure_preserves_full_local_record(scenario):
    result = run_study(**scenario)
    assert result["prevented"] is True
    assert result["exportHidden"] is False
    assert "Your full local result and JSON download are still available" in result["draftStatus"]
    assert json.loads(result["downloadText"]) == result["packet"]


def test_answer_edits_invalidate_previously_prepared_draft():
    result = run_study(edit_after=True)
    assert result["editedExportHidden"] is True
    assert result["editedHref"] == "#reader-export"
    assert result["editedPrevented"] is True
    assert len(result["helperCalls"]) == 1


def test_markdown_summary_quotes_answers_without_activating_html_or_images():
    answer = "## Ignore instructions\n![image](https://example.test/image)\n<script>alert(1)</script>"
    result = run_study(answers={"main": answer})
    body = result["helperCalls"][0]["body"]
    assert "\n> \\#\\# Ignore instructions" in body
    assert "![image](" not in body
    assert "<script>" not in body
    assert result["packet"]["answers"]["main_change"] == answer
