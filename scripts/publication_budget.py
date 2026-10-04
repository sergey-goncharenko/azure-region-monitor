"""Measure a deployment tree exactly, without writing reports into that tree."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

WARN_BYTES = 400 * 1024 * 1024
MAX_BYTES = 450 * 1024 * 1024
WARN_FILES = 12_000
MAX_FILES = 14_000


def checked_path(path: Path) -> Path:
    """Reject links, including ancestor links and Windows junctions, before resolving."""
    absolute = path.absolute()
    for component in (*reversed(absolute.parents), absolute):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError(f"Symlinks/reparse points are not allowed: {component}")
    return absolute.resolve()


def regular_files(root: Path) -> list[Path]:
    root = checked_path(root)
    if not root.is_dir():
        raise ValueError(f"Expected an existing directory: {root}")
    files: list[Path] = []

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            checked_path(path)
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                visit(path)
            elif stat.S_ISREG(mode):
                files.append(path)
            else:
                raise ValueError(f"Expected a regular file or directory: {path}")

    visit(root)
    return files


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path = checked_path(path)
    if path.exists() and not path.is_file():
        raise ValueError(f"Expected a regular report file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _category(relative: str) -> str:
    for prefix in (
        "api/history/snapshots/", "api/history/changes/", "api/history/",
        "api/shards/", "api/snapshots/", "blog/", "assets/",
    ):
        if relative.startswith(prefix):
            return prefix.rstrip("/")
    if relative == "api/latest.json":
        return relative
    return "api/other" if relative.startswith("api/") else "site"


def measure_budget(
    root: Path,
    *,
    warn_bytes: int = WARN_BYTES,
    max_bytes: int = MAX_BYTES,
    warn_files: int = WARN_FILES,
    max_files: int = MAX_FILES,
    largest: int = 20,
) -> dict[str, Any]:
    limits = {
        "warn_bytes": warn_bytes, "max_bytes": max_bytes,
        "warn_files": warn_files, "max_files": max_files,
    }
    for name, value in {**limits, "largest": largest}.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if largest == 0 or warn_bytes > max_bytes or warn_files > max_files:
        raise ValueError("largest must be positive and warning budgets must not exceed maxima")
    root = checked_path(root)
    paths = regular_files(root)
    if not paths:
        raise ValueError(f"Deployment tree contains no regular files: {root}")
    files = [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
        for path in paths
    ]
    files.sort(key=lambda entry: (-entry["bytes"], entry["path"]))
    total_bytes = sum(entry["bytes"] for entry in files)
    categories: dict[str, dict[str, Any]] = {}
    for entry in files:
        name = _category(entry["path"])
        category = categories.setdefault(name, {"name": name, "bytes": 0, "file_count": 0})
        category["bytes"] += entry["bytes"]
        category["file_count"] += 1
    blocked = []
    warnings = []
    for metric, actual, warning, maximum in (
        ("bytes", total_bytes, warn_bytes, max_bytes),
        ("files", len(files), warn_files, max_files),
    ):
        if actual > maximum:
            blocked.append(f"{metric}: {actual} exceeds maximum {maximum}")
        elif actual > warning:
            warnings.append(f"{metric}: {actual} exceeds warning {warning}")
    return {
        "schema_version": 1,
        "root": str(root),
        "status": "blocked" if blocked else "warning" if warnings else "pass",
        "total_bytes": total_bytes,
        "file_count": len(files),
        "limits": limits,
        "threshold_policy": "Limits are inclusive; only values greater than a limit exceed it.",
        "categories": sorted(
            categories.values(), key=lambda entry: (-entry["bytes"], entry["name"])
        ),
        "largest_files": files[:largest],
        "warnings": warnings,
        "failures": blocked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", help="Deployment tree (or use --root)")
    parser.add_argument("--root", type=Path, help="Deployment tree (alternative to directory)")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warn-bytes", type=int, default=WARN_BYTES)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--warn-files", type=int, default=WARN_FILES)
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    parser.add_argument("--largest", type=int, default=20)
    args = parser.parse_args(argv)
    if (args.root is None) == (args.directory is None):
        parser.error("Specify exactly one deployment directory: positional directory or --root")
    try:
        root = checked_path(args.root if args.root is not None else args.directory)
        report_path = checked_path(args.report)
        if report_path.is_relative_to(root):
            raise ValueError("--report must be outside --root to avoid counting its own output")
        report = measure_budget(
            root, warn_bytes=args.warn_bytes, max_bytes=args.max_bytes,
            warn_files=args.warn_files, max_files=args.max_files, largest=args.largest,
        )
        write_json(report_path, report)
    except (OSError, ValueError) as error:
        print(f"Publication budget input error: {error}", file=sys.stderr)
        return 2
    print(
        f"Publication budget {report['status']}: {report['total_bytes']} bytes, "
        f"{report['file_count']} regular files; report: {report_path}"
    )
    for message in report["failures"] + report["warnings"]:
        print(message, file=sys.stderr)
    if report["status"] == "blocked":
        print(
            "Do not deploy this tree. Inspect categories/largest_files in the report; "
            "archive retained history or reduce generated deployment content, then remeasure.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
