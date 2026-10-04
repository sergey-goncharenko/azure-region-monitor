import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.publication_budget import (
    MAX_BYTES,
    MAX_FILES,
    WARN_BYTES,
    WARN_FILES,
    checked_path,
    main,
    measure_budget,
)


def put(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_exact_counts_categories_and_largest_files_are_deterministic(tmp_path):
    root = tmp_path / "public"
    put(root, "index.html", b"1234")
    put(root, "api/latest.json", b"123456")
    put(root, "api/history/snapshots/a.json.gz", b"abc")
    put(root, "api/history/changes/a.json", b"xyz")
    put(root, "assets/empty", b"")
    (root / "empty-directory").mkdir()
    report = measure_budget(root, largest=4)
    assert report["total_bytes"] == 16
    assert report["file_count"] == 5
    assert report["status"] == "pass"
    assert report["limits"] == {
        "warn_bytes": WARN_BYTES, "max_bytes": MAX_BYTES,
        "warn_files": WARN_FILES, "max_files": MAX_FILES,
    }
    assert report["largest_files"] == [
        {"path": "api/latest.json", "bytes": 6},
        {"path": "index.html", "bytes": 4},
        {"path": "api/history/changes/a.json", "bytes": 3},
        {"path": "api/history/snapshots/a.json.gz", "bytes": 3},
    ]
    assert sum(category["bytes"] for category in report["categories"]) == 16
    assert sum(category["file_count"] for category in report["categories"]) == 5
    assert [category["name"] for category in report["categories"]] == [
        "api/latest.json", "site", "api/history/changes", "api/history/snapshots", "assets",
    ]


@pytest.mark.parametrize(("amount", "status"), [(9, "pass"), (10, "pass"), (11, "warning")])
@pytest.mark.parametrize("metric", ["bytes", "files"])
def test_warning_threshold_below_equal_above(tmp_path, metric, amount, status):
    root = tmp_path / "public"
    for index in range(amount if metric == "files" else 1):
        put(root, str(index), b"x" * (amount if metric == "bytes" else 0))
    report = measure_budget(root, warn_bytes=10, max_bytes=20, warn_files=10, max_files=20)
    assert report["status"] == status


@pytest.mark.parametrize(("amount", "status"), [(9, "pass"), (10, "pass"), (11, "blocked")])
@pytest.mark.parametrize("metric", ["bytes", "files"])
def test_block_threshold_below_equal_above(tmp_path, metric, amount, status):
    root = tmp_path / "public"
    for index in range(amount if metric == "files" else 1):
        put(root, str(index), b"x" * (amount if metric == "bytes" else 0))
    report = measure_budget(root, warn_bytes=10, max_bytes=10, warn_files=10, max_files=10)
    assert report["status"] == status


def test_cli_retains_actionable_blocking_report_outside_tree(tmp_path, capsys):
    root = tmp_path / "public"
    put(root, "index.html", b"123")
    report = tmp_path / "artifacts" / "budget.json"
    arguments = [
        "--root", str(root), "--report", str(report),
        "--warn-bytes", "1", "--max-bytes", "2",
    ]
    assert main(arguments) == 1
    data = json.loads(report.read_text())
    assert (data["total_bytes"], data["file_count"], data["status"]) == (3, 1, "blocked")
    assert "Do not deploy" in capsys.readouterr().err
    assert main(arguments) == 1
    assert json.loads(report.read_text())["file_count"] == 1


def test_report_cannot_be_written_in_deploy_tree(tmp_path, capsys):
    put(tmp_path, "index.html", b"x")
    report = tmp_path / "budget.json"
    assert main(["--root", str(tmp_path), "--report", str(report)]) == 2
    assert not report.exists()
    assert "outside" in capsys.readouterr().err


@pytest.mark.parametrize("limits", [
    {"warn_bytes": -1}, {"max_files": -1}, {"warn_files": 15, "max_files": 14},
    {"warn_bytes": 15, "max_bytes": 14}, {"largest": 0}, {"max_bytes": True},
])
def test_invalid_limits_fail_explicitly(tmp_path, limits):
    put(tmp_path, "index.html", b"x")
    with pytest.raises(ValueError):
        measure_budget(tmp_path, **limits)


def test_missing_empty_and_file_roots_fail_explicitly(tmp_path):
    file = put(tmp_path, "index.html", b"x")
    for root in [tmp_path / "missing", file]:
        with pytest.raises(ValueError, match="directory"):
            measure_budget(root)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no regular files"):
        measure_budget(empty)


def symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("Host does not allow creating symlinks")


def test_symlink_files_roots_ancestors_and_reports_are_rejected(tmp_path):
    root = tmp_path / "public"
    source = put(root, "index.html", b"x")
    link = tmp_path / "link"
    symlink_or_skip(link, root, directory=True)
    with pytest.raises(ValueError, match="Symlinks"):
        measure_budget(link)
    with pytest.raises(ValueError, match="Symlinks"):
        checked_path(link / "nested" / "new.json")
    assert main(["--root", str(root), "--report", str(link / "report.json")]) == 2
    symlink_or_skip(root / "aliased.html", source)
    with pytest.raises(ValueError, match="Symlinks"):
        measure_budget(root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not supported on this host")
def test_non_regular_entries_are_rejected(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="regular"):
        measure_budget(tmp_path)


@pytest.mark.parametrize("root_option", [[], ["--root"]])
def test_standalone_cli_works(tmp_path, root_option):
    put(tmp_path / "public", "index.html", b"ok")
    script = Path(__file__).resolve().parents[1] / "scripts" / "publication_budget.py"
    result = subprocess.run(
        [sys.executable, str(script), *root_option, str(tmp_path / "public"),
         "--report", str(tmp_path / "budget.json")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "budget.json").read_text())["total_bytes"] == 2


@pytest.mark.parametrize("arguments", [
    [], ["public", "--root", "another-public"],
])
def test_cli_requires_one_unambiguous_deployment_root(tmp_path, arguments):
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--report", str(tmp_path / "report.json")])
    assert error.value.code == 2
    assert not (tmp_path / "report.json").exists()
