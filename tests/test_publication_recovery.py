import gzip
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from azure_region_monitor.history import update_history
from scripts import publication_recovery as recovery


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def snapshot(root, timestamp, status="available", name="current.json"):
    return put_json(root / name, {
        "timestamp": timestamp,
        "regions": {"eastus": {"compute": {"vmSkus.standard.d2": {"status": status}}}},
    })


def empty_history(root):
    put_json(root / "index.json", {"days": []})
    return root


def history_fixture(root, timestamp="2026-09-01T08:00:00Z"):
    source = snapshot(root.parent, timestamp, "unavailable", name=f"{root.name}-source.json")
    update_history(source, root)
    return root


def bundle(root, history, timestamp, status="available"):
    source = snapshot(root.parent, timestamp, status, name=f"{root.name}-source.json")
    manifest = recovery.create_bundle(source, history, root, provenance="https://example.com/run/1")
    assert manifest["status"] == "complete", manifest
    return root


def tree_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_complete_bundle_preserves_exact_inputs_and_manifest(tmp_path):
    history = history_fixture(tmp_path / "history")
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    before = tree_bytes(history)
    output = tmp_path / "bundle"
    manifest = recovery.create_bundle(source, history, output, provenance="https://example.com/run/2")
    assert recovery.verify_bundle(output) == manifest
    assert (output / "snapshot.json").read_bytes() == source.read_bytes()
    assert tree_bytes(output / "history") == before == tree_bytes(history)
    assert manifest["status"] == "complete"
    assert manifest["observation_timestamp"] == "2026-09-02T09:00:00+00:00"
    assert manifest["history_baseline"]["latest_timestamp"] == "2026-09-01T08:00:00+00:00"
    assert manifest["history_baseline"]["day_count"] == 1
    assert manifest["provenance"] == "https://example.com/run/2"
    assert set(manifest["files"]) == set(tree_bytes(output)) - {"manifest.json"}
    assert "sha256" in manifest["files"]["snapshot.json"]
    assert recovery.main(["verify", "--bundle", str(output)]) == 0


def test_incomplete_history_failure_retains_raw_snapshot_nonzero(tmp_path, capsys):
    history = history_fixture(tmp_path / "history")
    (history / "snapshots" / "2026-09-01.json.gz").unlink()
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    output = tmp_path / "bundle"
    assert recovery.main([
        "create", "--snapshot", str(source), "--history", str(history), "--output", str(output),
    ]) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert "Missing history reference" in manifest["reason"]
    assert (output / "snapshot.json").read_bytes() == source.read_bytes()
    assert "Incomplete recovery bundle retained" in capsys.readouterr().err
    with pytest.raises(ValueError, match="Incomplete"):
        recovery.verify_bundle(output)


def test_explicit_snapshot_only_failure_artifact_cannot_replay(tmp_path):
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    output = tmp_path / "bundle"
    assert recovery.main([
        "create", "--snapshot", str(source), "--output", str(output),
        "--incomplete", "--reason", "history collection timed out",
    ]) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["reason"] == "history collection timed out"
    assert manifest["history_baseline"] is None
    assert list(manifest["files"]) == ["snapshot.json"]
    baseline = empty_history(tmp_path / "baseline")
    with pytest.raises(ValueError, match="Incomplete"):
        recovery.replay_bundles([output], baseline, tmp_path / "replayed")
    assert not (tmp_path / "replayed").exists()


@pytest.mark.parametrize("history_present", [True, False])
def test_allow_incomplete_forces_failure_capture_even_with_valid_stale_history(
    tmp_path, history_present, monkeypatch
):
    history = tmp_path / "history"
    if history_present:
        history_fixture(history)
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    original = tree_bytes(history) if history_present else {}
    output = tmp_path / "bundle"

    def must_not_certify_history(*args, **kwargs):
        raise AssertionError("A failed remote fetch must not validate stale local history")

    monkeypatch.setattr(recovery, "validate_history", must_not_certify_history)
    assert recovery.main([
        "create", "--snapshot", str(source), "--history", str(history), "--output", str(output),
        "--allow-incomplete", "--provenance", "https://example.com/failed-run",
    ]) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert manifest["history_baseline"] is None
    assert "not confirmed complete" in manifest["reason"]
    assert list(manifest["files"]) == ["snapshot.json"]
    assert (output / "snapshot.json").read_bytes() == source.read_bytes()
    assert not (output / "history").exists()
    assert tree_bytes(history) == original
    with pytest.raises(ValueError, match="Incomplete"):
        recovery.verify_bundle(output)


@pytest.mark.parametrize("mode", ["missing", "corrupt", "unexpected"])
def test_bundle_file_inventory_detects_missing_corrupt_and_extra_data(tmp_path, mode):
    baseline = history_fixture(tmp_path / "history")
    archived = bundle(tmp_path / "bundle", baseline, "2026-09-02T09:00:00Z")
    data = archived / "history" / "snapshots" / "2026-09-01.json.gz"
    if mode == "missing":
        data.unlink()
    elif mode == "corrupt":
        data.write_bytes(b"corrupt")
    else:
        (archived / "unexpected.json").write_text("{}")
    with pytest.raises(ValueError, match="inventory mismatch|hash/size mismatch"):
        recovery.verify_bundle(archived)
    with pytest.raises(ValueError):
        recovery.replay_bundles([archived], baseline, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("reference", [
    "../escape.json", "https://example.com/snapshot.json", "/absolute.json",
    "C:/absolute.json", "snapshots\\bad.json", "snapshots/./bad.json",
])
def test_unsafe_or_remote_history_refs_never_make_complete_bundle(tmp_path, reference):
    history = history_fixture(tmp_path / "history")
    index = json.loads((history / "index.json").read_text())
    index["days"][0]["previous_snapshot_path"] = reference
    put_json(history / "index.json", index)
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    result = recovery.create_bundle(source, history, tmp_path / "bundle")
    assert result["status"] == "incomplete"
    assert "Unsafe or remote" in result["reason"]


def test_even_hash_consistent_bundle_must_have_full_valid_references(tmp_path):
    history = history_fixture(tmp_path / "history")
    archived = bundle(tmp_path / "bundle", history, "2026-09-02T09:00:00Z")
    change_path = archived / "history" / "changes" / "2026-09-01.json"
    change = json.loads(change_path.read_text())
    change["previous_snapshot_path"] = "snapshots/missing.json"
    put_json(change_path, change)
    manifest = json.loads((archived / "manifest.json").read_text())
    manifest["files"] = recovery._inventory(archived)
    put_json(archived / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Missing history reference"):
        recovery.verify_bundle(archived)


@pytest.mark.parametrize(("marker", "value"), [
    ("archive", {"archive_base_url": "https://example.com/publication", "generation": "a" * 64}),
    ("public_recent_days", 30),
])
def test_public_projection_markers_never_certify_complete_history(tmp_path, marker, value):
    history = history_fixture(tmp_path / "history")
    archived = bundle(tmp_path / "complete", history, "2026-09-02T09:00:00Z")
    index = json.loads((history / "index.json").read_text())
    index[marker] = value
    put_json(history / "index.json", index)
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    manifest = recovery.create_bundle(source, history, tmp_path / "incomplete")
    assert manifest["status"] == "incomplete"
    assert "public projection" in manifest["reason"]
    assert (tmp_path / "incomplete" / "snapshot.json").read_bytes() == source.read_bytes()
    put_json(archived / "history" / "index.json", index)
    forged = json.loads((archived / "manifest.json").read_text())
    forged["files"] = recovery._inventory(archived)
    put_json(archived / "manifest.json", forged)
    with pytest.raises(ValueError, match="public projection"):
        recovery.verify_bundle(archived)


def test_corrupt_gzip_history_is_incomplete_even_if_not_referenced(tmp_path):
    history = history_fixture(tmp_path / "history")
    (history / "snapshots" / "orphan.json.gz").write_bytes(b"\x1f\x8bnot-gzip")
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    result = recovery.create_bundle(source, history, tmp_path / "bundle")
    assert result["status"] == "incomplete"
    assert "Invalid JSON" in result["reason"]


def test_same_timestamp_conflicting_baseline_cannot_be_complete(tmp_path):
    history = history_fixture(tmp_path / "history")
    source = snapshot(tmp_path, "2026-09-01T08:00:00Z")
    result = recovery.create_bundle(source, history, tmp_path / "bundle")
    assert result["status"] == "incomplete"
    assert "Conflicting baseline" in result["reason"]


def use_legacy_snapshot_references(history):
    for path in history.rglob("*.json"):
        if path.parent.name != "snapshots":
            path.write_text(
                path.read_text(encoding="utf-8").replace(".json.gz", ".json"), encoding="utf-8"
            )


def test_compressed_only_legacy_refs_capture_verify_and_replay_without_inflation(tmp_path):
    history = history_fixture(tmp_path / "history")
    use_legacy_snapshot_references(history)
    original = tree_bytes(history)
    archived = bundle(tmp_path / "bundle", history, "2026-09-02T09:00:00Z")
    manifest = recovery.verify_bundle(archived)
    assert "history/snapshots/2026-09-01.json.gz" in manifest["files"]
    assert "history/snapshots/2026-09-01.json" not in manifest["files"]
    assert tree_bytes(archived / "history") == original
    assert json.loads((archived / "history" / "index.json").read_text())[
        "latest_snapshot_path"
    ] == "snapshots/2026-09-01.json"
    before_bundle = tree_bytes(archived)
    output = tmp_path / "output"
    recovery.replay_bundles([archived], history, output)
    assert not list((output / "history" / "snapshots").glob("*.json"))
    assert tree_bytes(history) == original
    assert tree_bytes(archived) == before_bundle


@pytest.mark.parametrize("problem", ["missing", "corrupt", "wrong-date", "wrong-timestamp"])
def test_legacy_reference_requires_valid_compressed_snapshot(tmp_path, problem):
    history = history_fixture(tmp_path / "history")
    use_legacy_snapshot_references(history)
    compressed = history / "snapshots" / "2026-09-01.json.gz"
    if problem == "missing":
        compressed.unlink()
    elif problem == "corrupt":
        compressed.write_bytes(b"corrupt")
    else:
        payload = json.loads(gzip.decompress(compressed.read_bytes()))
        payload["timestamp"] = (
            "2026-09-02T08:00:00Z" if problem == "wrong-date" else "2026-09-01T09:00:00Z"
        )
        compressed.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
    source = snapshot(tmp_path, "2026-09-03T09:00:00Z")
    manifest = recovery.create_bundle(source, history, tmp_path / "bundle")
    assert manifest["status"] == "incomplete"
    assert not (history / "snapshots" / "2026-09-01.json").exists()


def test_existing_raw_original_remains_required_by_exact_bundle_inventory(tmp_path):
    history = history_fixture(tmp_path / "history")
    raw = history / "snapshots" / "2026-09-01.json"
    raw.write_bytes(gzip.decompress((raw.with_suffix(".json.gz")).read_bytes()))
    use_legacy_snapshot_references(history)
    original = tree_bytes(history)
    archived = bundle(tmp_path / "bundle", history, "2026-09-02T09:00:00Z")
    manifest = recovery.verify_bundle(archived)
    assert "history/snapshots/2026-09-01.json" in manifest["files"]
    assert "history/snapshots/2026-09-01.json.gz" in manifest["files"]
    assert tree_bytes(history) == original == tree_bytes(archived / "history")
    (archived / "history" / "snapshots" / "2026-09-01.json").unlink()
    with pytest.raises(ValueError, match="inventory mismatch"):
        recovery.verify_bundle(archived)


def test_corrupt_raw_original_is_not_hidden_by_valid_compressed_alternative(tmp_path):
    history = history_fixture(tmp_path / "history")
    raw = history / "snapshots" / "2026-09-01.json"
    raw.write_text("corrupt", encoding="utf-8")
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    manifest = recovery.create_bundle(source, history, tmp_path / "bundle")
    assert manifest["status"] == "incomplete"
    assert "Invalid JSON" in manifest["reason"]


def test_equal_identical_baseline_is_valid_for_capture_but_not_replay(tmp_path):
    history = history_fixture(tmp_path / "history")
    source = snapshot(tmp_path, "2026-09-01T08:00:00Z", "unavailable")
    output = tmp_path / "bundle"
    assert recovery.create_bundle(source, history, output)["status"] == "complete"
    recovery.verify_bundle(output)
    with pytest.raises(ValueError, match="strictly older"):
        recovery.replay_bundles([output], history, tmp_path / "replayed")


def test_shuffled_multiday_replay_preserves_intraday_observations_gaps_and_inputs(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline replay must not access the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    history = history_fixture(tmp_path / "history")
    morning = bundle(tmp_path / "morning", history, "2026-09-02T09:00:00Z")
    evening = bundle(tmp_path / "evening", history, "2026-09-02T18:00:00Z", "unavailable")
    later = bundle(tmp_path / "later", history, "2026-09-04T12:00:00Z")
    inputs = [history, morning, evening, later]
    before = [tree_bytes(path) for path in inputs]
    output = tmp_path / "output"
    report = recovery.replay_bundles([later, evening, morning, later], history, output)
    assert [item["timestamp"] for item in report["observations"]] == [
        "2026-09-02T09:00:00+00:00", "2026-09-02T18:00:00+00:00", "2026-09-04T12:00:00+00:00",
    ]
    assert report["duplicates_skipped"] == 1
    assert report["unobserved_date_ranges"][0]["first_unobserved_date"] == "2026-09-03"
    assert "unknown" in report["coverage"]
    assert [tree_bytes(path) for path in inputs] == before
    assert (output / "snapshots" / "latest.json").read_bytes() == (later / "snapshot.json").read_bytes()
    index = json.loads((output / "history" / "index.json").read_text())
    assert [day["date"] for day in index["days"]] == ["2026-09-04", "2026-09-02", "2026-09-01"]
    assert not (output / "history" / "changes" / "2026-09-03.json").exists()
    alias = json.loads(gzip.decompress(
        (output / "history" / "snapshots" / "2026-09-02.json.gz").read_bytes()
    ))
    assert alias["timestamp"].startswith("2026-09-02T18:00:00")
    for item, archived in zip(report["observations"], [morning, evening, later]):
        assert (output / item["snapshot_path"]).read_bytes() == (archived / "snapshot.json").read_bytes()
    assert len(list((output / "observations").iterdir())) == 4


def test_same_instant_with_different_offsets_and_json_formatting_is_idempotent(tmp_path):
    history = empty_history(tmp_path / "history")
    first = bundle(tmp_path / "first", history, "2026-09-02T09:00:00Z")
    same = bundle(tmp_path / "same", history, "2026-09-02T11:00:00+02:00")
    report = recovery.replay_bundles([same, first, first], history, tmp_path / "output")
    assert len(report["observations"]) == 1
    assert report["duplicates_skipped"] == 2


def test_conflicting_same_timestamp_fails_before_any_output_mutation(tmp_path):
    history = history_fixture(tmp_path / "history")
    first = bundle(tmp_path / "first", history, "2026-09-02T09:00:00Z")
    conflict = bundle(tmp_path / "conflict", history, "2026-09-02T11:00:00+02:00", "unavailable")
    before = tree_bytes(tmp_path)
    with pytest.raises(ValueError, match="Conflicting observations"):
        recovery.replay_bundles([first, conflict], history, tmp_path / "new-parent" / "output")
    assert tree_bytes(tmp_path) == before
    assert not (tmp_path / "new-parent").exists()


@pytest.mark.parametrize("baseline_time", ["2026-09-02T09:00:00Z", "2026-09-03T09:00:00Z"])
def test_equal_or_newer_replay_baseline_is_rejected(tmp_path, baseline_time):
    old = history_fixture(tmp_path / "old")
    archived = bundle(tmp_path / "bundle", old, "2026-09-02T09:00:00Z")
    baseline = history_fixture(tmp_path / "baseline", baseline_time)
    with pytest.raises(ValueError, match="strictly older"):
        recovery.replay_bundles([archived], baseline, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_earlier_same_day_baseline_is_preserved_separately(tmp_path):
    baseline = history_fixture(tmp_path / "history", "2026-09-02T08:00:00Z")
    archived = bundle(tmp_path / "bundle", baseline, "2026-09-02T09:00:00Z")
    original = tree_bytes(baseline)
    report = recovery.replay_bundles([archived], baseline, tmp_path / "output")
    assert len(report["baseline_observations"]) == 1
    saved = tmp_path / "output" / report["baseline_observations"][0]["snapshot_path"]
    assert saved.read_bytes() == original["snapshots/2026-09-02.json.gz"]
    assert tree_bytes(baseline) == original


def test_replay_failure_never_exposes_partial_success_output(tmp_path, monkeypatch):
    baseline = history_fixture(tmp_path / "history")
    archived = bundle(tmp_path / "bundle", baseline, "2026-09-02T09:00:00Z")
    before = tree_bytes(tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("simulated history update failure")

    monkeypatch.setattr(recovery, "update_history", fail)
    with pytest.raises(ValueError, match="simulated"):
        recovery.replay_bundles([archived], baseline, tmp_path / "output")
    assert tree_bytes(tmp_path) == before
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".output-*"))


@pytest.mark.parametrize("payload", [
    {"regions": {}}, {"timestamp": "2026-09-02T09:00:00", "regions": {}},
    {"timestamp": "invalid", "regions": {}}, {"timestamp": "2026-09-02T09:00:00Z", "regions": []},
])
def test_invalid_snapshots_fail_without_claiming_completion(tmp_path, payload):
    source = put_json(tmp_path / "snapshot.json", payload)
    assert recovery.main([
        "create", "--snapshot", str(source), "--output", str(tmp_path / "bundle"),
        "--incomplete", "--reason", "history unavailable",
    ]) == 2
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("payload", [
    b"not json", b"[]", b'{"timestamp":"2026-09-01T00:00:00Z","regions":NaN}',
    b'{"timestamp":"2026-09-01T00:00:00Z","regions":{},"regions":{}}',
])
def test_malformed_json_is_explicit_invalid_input(tmp_path, payload):
    source = tmp_path / "snapshot.json"
    source.write_bytes(payload)
    assert recovery.main([
        "create", "--snapshot", str(source), "--output", str(tmp_path / "bundle"),
        "--incomplete", "--reason", "history unavailable",
    ]) == 2
    assert not (tmp_path / "bundle").exists()


def test_missing_history_without_explicit_incomplete_is_not_success(tmp_path):
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    with pytest.raises(ValueError, match="require --history"):
        recovery.create_bundle(source, None, tmp_path / "output")
    with pytest.raises(ValueError, match="nonempty --reason"):
        recovery.create_bundle(source, None, tmp_path / "output", incomplete=True)
    result = recovery.create_bundle(source, tmp_path / "missing", tmp_path / "retained")
    assert result["status"] == "incomplete"
    assert (tmp_path / "retained" / "snapshot.json").read_bytes() == source.read_bytes()


def test_output_cannot_overlap_inputs_or_overwrite_existing_data(tmp_path):
    history = history_fixture(tmp_path / "history")
    archived = bundle(tmp_path / "bundle", history, "2026-09-02T09:00:00Z")
    for output in (history, history / "output", archived / "output", tmp_path):
        with pytest.raises(ValueError, match="overlap"):
            recovery.replay_bundles([archived], history, output)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        recovery.replay_bundles([archived], history, existing)


def test_symlink_history_is_rejected_and_raw_snapshot_retained(tmp_path):
    history = history_fixture(tmp_path / "history")
    link = history / "alias.json"
    try:
        link.symlink_to(history / "index.json")
    except (OSError, NotImplementedError):
        pytest.skip("Host does not allow creating symlinks")
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    result = recovery.create_bundle(source, history, tmp_path / "bundle")
    assert result["status"] == "incomplete"
    assert "Symlinks" in result["reason"]
    assert (tmp_path / "bundle" / "snapshot.json").read_bytes() == source.read_bytes()


def test_standalone_recovery_cli_create_verify_replay(tmp_path):
    history = history_fixture(tmp_path / "history")
    source = snapshot(tmp_path, "2026-09-02T09:00:00Z")
    script = Path(__file__).resolve().parents[1] / "scripts" / "publication_recovery.py"
    commands = [
        ["create", "--snapshot", str(source), "--history", str(history),
         "--output", str(tmp_path / "bundle")],
        ["verify", "--bundle", str(tmp_path / "bundle")],
        ["replay", "--bundle", str(tmp_path / "bundle"), "--history", str(history),
         "--output", str(tmp_path / "replayed")],
    ]
    for command in commands:
        result = subprocess.run(
            [sys.executable, str(script), *command], capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONPATH": str(script.parents[1] / "src")},
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "replayed" / "snapshots" / "latest.json").exists()
