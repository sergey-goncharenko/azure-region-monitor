import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture_static_site_evidence.mjs"


def capture_fixture(tmp_path, *, mismatch=False, failed=()):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the visual capture orchestration test.")
    tooling = tmp_path / "tooling"
    module = tooling / "node_modules" / "playwright"
    module.mkdir(parents=True)
    (module / "package.json").write_text('{"type":"module","exports":"./index.mjs"}', encoding="utf-8")
    (module / "index.mjs").write_text("""
import { writeFile } from "node:fs/promises";
export const chromium = { async launch() { return {
  async newPage(options) {
    if (options.timezoneId !== "UTC" || options.viewport.width !== 1440) throw Error("Unstable context");
    let path;
    return {
      async goto(url) { path = new URL(url).pathname; return {ok: () => true}; },
      async evaluate() {},
      async screenshot(options) {
        if (!options.fullPage || options.animations !== "disabled") throw Error("Unstable capture");
        await writeFile(options.path, path);
      },
      async close() {},
    };
  },
  async close() {},
}; } };
""", encoding="utf-8")
    script = tooling / "capture.mjs"
    shutil.copyfile(SCRIPT, script)
    evidence = tmp_path / "evidence"
    for label in ("before", "after"):
        site = evidence / f"{label}-site"
        (site / "api").mkdir(parents=True)
        snapshot = {"timestamp": "2026-09-06T00:00:00Z", "regions": {}}
        if label == "after" and mismatch:
            snapshot["regions"] = {"unexpected": {}}
        (site / "api" / "latest.json").write_text(json.dumps(snapshot), encoding="utf-8")
        (site / "index.html").write_text("<h1>Shared page</h1>", encoding="utf-8")
        (site / ("removed.html" if label == "before" else "added.html")).write_text("<p>Fixture</p>", encoding="utf-8")
    statuses = evidence / "build-status.json"
    statuses.write_text(json.dumps({
        label: "failure" if label in failed else "success" for label in ("before", "after")
    }), encoding="utf-8")
    result = subprocess.run(
        [node, str(script)], cwd=tooling, capture_output=True, text=True, encoding="utf-8",
        timeout=30, env={
            **os.environ, "EVIDENCE_DIR": str(evidence), "BASE_SHA": "a" * 40, "HEAD_SHA": "b" * 40,
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.txt"), "PR_NUMBER": "119",
            "BUILD_STATUS_FILE": str(statuses),
            "SNAPSHOT_FILE": str(evidence / "before-site" / "api" / "latest.json"),
        },
    )
    return result, evidence


def test_capture_script_keeps_pair_paths_and_added_removed_statuses(tmp_path):
    result, evidence = capture_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["base_sha"] == "a" * 40
    assert manifest["head_sha"] == "b" * 40
    assert manifest["input_snapshot"]["timestamp"] == "2026-09-06T00:00:00Z"
    comparison = {item["path"]: item for item in manifest["comparison"]}
    assert comparison["index.html"]["status"] == "unchanged"
    assert comparison["added.html"]["status"] == "added"
    assert comparison["removed.html"]["status"] == "removed"
    report = (evidence / "index.html").read_text(encoding="utf-8")
    for item in comparison.values():
        for key in ("before", "after"):
            if item[key]:
                assert (evidence / item[key]).exists()
                assert item[key] in report
    assert "not live-site screenshots" in report


def test_capture_refuses_incomparable_snapshot_inputs(tmp_path):
    result, evidence = capture_fixture(tmp_path, mismatch=True)
    assert result.returncode != 0
    assert "identical snapshot bytes" in result.stderr
    assert not (evidence / "manifest.json").exists()


@pytest.mark.parametrize("failed", [("before",), ("after",), ("before", "after")])
def test_failed_builds_keep_available_evidence_without_false_added_removed_claims(tmp_path, failed):
    result, evidence = capture_fixture(tmp_path, failed=failed)
    assert result.returncode == 1, result.stderr
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["comparable"] is False
    for label in failed:
        assert manifest["builds"][label] == "failure"
        assert not (evidence / label).exists()  # ignore partial HTML from the failed build
    for item in manifest["comparison"]:
        assert item["status"] in {"before_build_failed", "after_build_failed"}
    assert "INCOMPLETE" in (evidence / "index.html").read_text(encoding="utf-8")
    for label in {"before", "after"} - set(failed):
        assert list((evidence / label).glob("*.png"))
