import json
from pathlib import Path

import pytest

from azure_region_monitor.static_site import build_static_site
from scripts.prepare_visual_evidence import prepare_inputs


def fixture_data(root):
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    for date, status in (("2026-09-05", "unavailable"), ("2026-09-06", "available")):
        snapshot = {
            "timestamp": f"{date}T08:00:00Z",
            "regions": {"eastus": {"compute": {"vmSkus.standard.d2ns.v6": {"status": status}}}},
        }
        (snapshots / f"{date}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (snapshots / "latest.json").write_bytes((snapshots / "2026-09-06.json").read_bytes())
    return root


def test_shared_inputs_seed_raw_history_and_leave_checkout_untouched(tmp_path):
    source = fixture_data(tmp_path / "head" / "data")
    original = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    output = prepare_inputs(source, tmp_path / "shared")
    assert not (source / "history").exists()
    index = json.loads((output / "history" / "index.json").read_text(encoding="utf-8"))
    assert [day["date"] for day in index["days"]] == ["2026-09-06", "2026-09-05"]
    assert all("briefing" not in day and "narrative" not in day for day in index["days"])
    assert (output / "history" / "snapshots" / "2026-09-06.json").read_bytes() == original[Path("snapshots/latest.json")]
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()} == original


def test_both_actual_builds_use_same_raw_inputs_and_render_a_daily_change(tmp_path):
    source = fixture_data(tmp_path / "head" / "data")
    inputs = prepare_inputs(source, tmp_path / "shared")
    for label in ("before", "after"):
        output = tmp_path / f"{label}-site"
        build_static_site(
            output, snapshot_path=inputs / "snapshots" / "latest.json",
            diff_path=inputs / "diffs" / "latest.json", history_path=inputs / "history",
        )
        page = (output / "blog" / "2026-09-06.html").read_text(encoding="utf-8")
        assert "Daily change briefing" in page
        assert "D2ns" in page
    assert (tmp_path / "before-site" / "api" / "latest.json").read_bytes() == (
        tmp_path / "after-site" / "api" / "latest.json"
    ).read_bytes()
    assert "briefing" not in (inputs / "history" / "index.json").read_text(encoding="utf-8")


def test_provided_history_is_preserved_instead_of_reconstructed(tmp_path):
    source = fixture_data(tmp_path / "source")
    (source / "history").mkdir()
    existing = b'{"days": [], "provided_fixture": true}\n'
    (source / "history" / "index.json").write_bytes(existing)
    output = prepare_inputs(source, tmp_path / "shared")
    assert (output / "history" / "index.json").read_bytes() == existing


def test_input_paths_cannot_overlap_or_overwrite_an_existing_directory(tmp_path):
    source = fixture_data(tmp_path / "source")
    with pytest.raises(ValueError, match="outside"):
        prepare_inputs(source, source / "generated")
    with pytest.raises(ValueError, match="outside"):
        prepare_inputs(source, tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        prepare_inputs(source, output)


def test_missing_latest_snapshot_is_an_explicit_failure(tmp_path):
    with pytest.raises(ValueError, match="repository snapshot"):
        prepare_inputs(tmp_path / "empty", tmp_path / "shared")
