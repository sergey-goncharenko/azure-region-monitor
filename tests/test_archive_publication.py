from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_publication", ROOT / "scripts" / "archive_publication.py")
assert SPEC and SPEC.loader
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)
BASE = "https://example.blob.core.windows.net/archive"
PREFIX = BASE + "/publications/123-1"
DIGEST = "a" * 64
GENERATION = PREFIX


def _stage(root):
    history = root / "api" / "history"
    history.mkdir(parents=True)
    (history / "index.json").write_text('{"days":[]}', encoding="utf-8")
    (root / "api" / "latest.json").write_text('{"timestamp":"2026-10-04"}', encoding="utf-8")
    (root / "archive-manifest.json").write_text(
        json.dumps({"schema_version": 1, "generation": DIGEST}), encoding="utf-8"
    )
    return root


def test_sources_disabled_does_not_contact_azure(monkeypatch):
    monkeypatch.setattr(publication, "_json_url", lambda _: pytest.fail("No archive request expected"))
    assert publication.sources("", "https://site/snapshot", "https://site/history") == {
        "snapshot_url": "https://site/snapshot", "history_url": "https://site/history",
        "archive_base_url": "",
    }


def test_first_archive_requires_explicit_bootstrap(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")

    def missing(url):
        raise urllib.error.HTTPError(url, 404, "missing", {}, None)

    monkeypatch.setattr(publication, "_json_url", missing)
    with pytest.raises(RuntimeError, match="omit history"):
        publication.sources(BASE, "https://site/snapshot", "https://site/history")
    sources = publication.sources(BASE, "https://site/snapshot", "https://site/history", bootstrap=True)
    assert sources["history_url"] == "https://site/history"
    assert sources["archive_base_url"] == PREFIX


def test_sources_use_committed_archive_even_if_last_site_upload_failed(monkeypatch):
    manifest = b'{"schema_version":1,"files":{}}'
    pointer = {"schema_version": 1, "archive_base_url": GENERATION,
               "manifest_sha256": hashlib.sha256(manifest).hexdigest()}
    monkeypatch.setattr(publication, "_json_url", lambda _: pointer)
    monkeypatch.setattr(publication.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(manifest))
    monkeypatch.setenv("GITHUB_RUN_ID", "124")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    resolved = publication.sources(BASE, "https://stale/snapshot", "https://stale/history")
    assert resolved["snapshot_url"] == GENERATION + "/api/latest.json"
    assert resolved["history_url"] == GENERATION + "/api/history"
    assert resolved["archive_base_url"] == BASE + "/publications/124-2"
    overridden = publication.sources(
        BASE, "https://recovery/snapshot", "https://recovery/history",
        snapshot_override=True, history_override=True,
    )
    assert overridden["snapshot_url"] == "https://recovery/snapshot"
    assert overridden["history_url"] == "https://recovery/history"


def test_sources_reject_corrupt_or_cross_origin_pointer(monkeypatch):
    pointer = {"schema_version": 1, "archive_base_url": "https://untrusted.example/publications/1",
               "manifest_sha256": "a" * 64}
    monkeypatch.setattr(publication, "_json_url", lambda _: pointer)
    with pytest.raises(ValueError, match="invalid schema"):
        publication.sources(BASE, "", "")
    pointer["archive_base_url"] = GENERATION
    monkeypatch.setattr(publication.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="manifest does not match"):
        publication.sources(BASE, "", "")


def test_empty_pointer_is_not_implicit_bootstrap(monkeypatch):
    monkeypatch.setattr(publication, "_json_url", lambda _: {})
    with pytest.raises(ValueError, match="invalid schema"):
        publication.sources(BASE, "", "", bootstrap=True)


def test_bootstrap_does_not_hide_archive_outage(monkeypatch):
    def outage(url):
        raise urllib.error.HTTPError(url, 503, "unavailable", {}, None)

    monkeypatch.setattr(publication, "_json_url", outage)
    with pytest.raises(RuntimeError, match="must not omit history"):
        publication.sources(BASE, "https://stale/snapshot", "https://stale/history", bootstrap=True)


def test_inventory_requires_baseline_and_hashes_exact_files(tmp_path):
    with pytest.raises(ValueError, match="lacks its current snapshot"):
        publication.inventory(tmp_path)
    stage = _stage(tmp_path)
    inventory = publication.inventory(stage)
    for relative, entry in inventory.items():
        payload = (stage / relative).read_bytes()
        assert entry == {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


@pytest.mark.parametrize("url", [
    "http://example.blob.core.windows.net/archive", BASE + "?sig=secret",
    BASE + "/../archive", "https://example.org/archive", "https://user:pass@example.blob.core.windows.net/archive",
    "https://example.blob.core.windows.net:443/archive", BASE + "#fragment",
])
def test_archive_root_rejects_credentials_traversal_and_non_azure(url):
    with pytest.raises(ValueError):
        publication.archive_root(url)


def test_upload_verifies_every_object_before_advancing_pointer(tmp_path, monkeypatch):
    stage = _stage(tmp_path / "archive")
    calls = []
    verified = []
    monkeypatch.setattr(publication, "_az", lambda *args: calls.append(args))
    monkeypatch.setattr(
        publication, "_verify_object", lambda item, base: verified.append((item[0], base))
    )
    monkeypatch.setattr(
        publication, "_json_url",
        lambda _: json.loads((tmp_path / "publication-latest.json").read_text()),
    )
    publication.upload(BASE, PREFIX, stage)
    assert len(calls) == 2
    assert calls[0][:3] == ("storage", "blob", "upload-batch")
    assert calls[1][:3] == ("storage", "blob", "upload")
    for command in calls:
        assert command[command.index("--auth-mode") + 1] == "login"
        assert "--validate-content" in command
        assert "--account-key" not in command
    assert calls[0][calls[0].index("--overwrite") + 1] == "false"
    assert {name for name, _ in verified} == {
        "api/latest.json", "api/history/index.json", "archive-manifest.json", "_publication-manifest.json",
    }
    manifest = json.loads((stage / "_publication-manifest.json").read_text())
    assert manifest["file_count"] == 3
    assert manifest["total_bytes"] == sum(entry["bytes"] for entry in manifest["files"].values())


def test_missing_or_corrupt_public_object_does_not_advance_pointer(tmp_path, monkeypatch):
    stage = _stage(tmp_path / "archive")
    calls = []
    monkeypatch.setattr(publication, "_az", lambda *args: calls.append(args))
    monkeypatch.setattr(
        publication, "_verify_object", lambda *args: (_ for _ in ()).throw(ValueError("corrupt"))
    )
    with pytest.raises(ValueError, match="corrupt"):
        publication.upload(BASE, PREFIX, stage)
    assert len(calls) == 1
    assert not (tmp_path / "publication-latest.json").exists()


def test_object_verification_uses_exact_wire_bytes(monkeypatch):
    payload = b"\x1f\x8bcompressed bytes"
    monkeypatch.setattr(publication.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    expected = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    publication._verify_object(("api/history/a.json.gz", expected), GENERATION)
    with pytest.raises(ValueError, match="larger than expected"):
        publication._verify_object(("api/history/a.json.gz", {**expected, "bytes": 1}), GENERATION)
    with pytest.raises(ValueError, match="verification failed"):
        publication._verify_object(("api/history/a.json.gz", {**expected, "sha256": "0" * 64}), GENERATION)


def test_all_publication_workflows_share_guard_and_recovery_order():
    for filename in (
        "daily-scan.yml", "regional-probe-run.yml", "azure-latency-tests.yml", "dashboard-redeploy.yml",
    ):
        workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        assert "uses: ./.github/actions/publish-dashboard" in workflow
        assert "group: dashboard-publication" in workflow
        assert "--require-existing" in workflow
        assert workflow.index("archive_publication.py sources") < workflow.index("--require-existing")
        assert "steps.sources.outputs.history_url" in workflow
        assert "always() && steps." in workflow
        assert "du -sh public" not in workflow
        for budget in ("MAX_BYTES", "WARN_BYTES", "MAX_FILES", "WARN_FILES"):
            assert (
                f"AZWATCH_PUBLICATION_{budget}: "
                f"${{{{ vars.AZWATCH_PUBLICATION_{budget} }}}}"
            ) in workflow
    action = (ROOT / ".github" / "actions" / "publish-dashboard" / "action.yml").read_text()
    positions = [
        action.index(text) for text in (
            "publication_recovery.py create", "Retain candidate snapshot",
            "archive_publication.py build", "publication_budget.py public",
            "archive_publication.py upload", "Azure/static-web-apps-deploy@v1",
        )
    ]
    assert positions == sorted(positions)
    assert "set -euo pipefail" in action
    assert "retention-days: 90" in action
    assert action.count("include-hidden-files: true") == 2
    assert "api_location:" in action
    assert "${{ vars." not in action


def test_real_export_publisher_and_next_run_use_identical_generation(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    snapshots = workspace / "data" / "snapshots"
    snapshots.mkdir(parents=True)
    shutil.copytree(ROOT / "api", workspace / "api")
    snapshot_path = snapshots / "latest.json"
    environment = {
        name: value for name, value in os.environ.items()
        if not name.startswith(("AZURE_", "OPENAI_", "AI_SUMMARY_", "HISTORY_BASE_URL"))
    }
    environment["PYTHONPATH"] = str(ROOT / "src")
    for day, status in (("2026-10-03", "unknown"), ("2026-10-04", "available")):
        snapshot_path.write_text(json.dumps({
            "timestamp": day + "T00:00:00Z",
            "regions": {"eastus": {"compute": {"Standard_D2s_v5": {"status": status}}}},
        }), encoding="utf-8")
        command = subprocess.run(
            [sys.executable, "-c", "from azure_region_monitor.cli import main; main()",
             "update-history", "--snapshot", str(snapshot_path),
             "--history-dir", str(workspace / "data" / "history"),
             *(["--require-existing"] if day == "2026-10-04" else [])],
            cwd=workspace, env=environment, capture_output=True, text=True, check=False,
        )
        assert command.returncode == 0, command.stdout + command.stderr
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(publication, "ROOT", workspace)
    monkeypatch.setattr(publication, "WORK", workspace / ".publication")
    publication.build(PREFIX)
    stage = workspace / ".publication" / "archive"
    browser = json.loads((workspace / "public" / "archive-config.json").read_text())
    api = json.loads((workspace / ".publication" / "api" / "archive-config.json").read_text())
    actual_base = PREFIX
    assert api["archive_base_url"] == actual_base
    assert api["generation"] == browser["generation"]
    assert browser["archive_base_url"] == PREFIX
    assert not (workspace / "public" / "api" / "history" / "index.json").exists()
    complete_index = json.loads((stage / "api" / "history" / "index.json").read_text())
    assert len(complete_index["days"]) == 2
    assert (stage / "archive" / "catalog" / "1.json").is_file()

    calls = []
    monkeypatch.setattr(publication, "_az", lambda *args: calls.append(args))

    def public_read(request, **_kwargs):
        url = request.full_url if hasattr(request, "full_url") else request
        assert url.startswith(actual_base + "/")
        return (stage / url.removeprefix(actual_base + "/")).open("rb")

    monkeypatch.setattr(publication.urllib.request, "urlopen", public_read)
    monkeypatch.setattr(
        publication, "_json_url",
        lambda _: json.loads((workspace / ".publication" / "publication-latest.json").read_text()),
    )
    publication.upload(BASE, PREFIX, stage)
    assert calls[0][calls[0].index("--destination-path") + 1] == actual_base.removeprefix(BASE + "/")
    monkeypatch.setenv("GITHUB_RUN_ID", "124")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    next_run = publication.sources(BASE, "https://stale/snapshot", "https://stale/history")
    assert next_run["history_url"] == actual_base + "/api/history"
    assert next_run["snapshot_url"] == actual_base + "/api/latest.json"
