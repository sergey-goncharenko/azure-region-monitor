"""Create, verify, and chronologically replay local publication recovery bundles.

No command fetches history, contacts Azure, runs probes, or deploys a site.
The caller must materialize a complete history tree before creating a complete bundle.
Legacy dated .json snapshot references may use existing .json.gz objects without inflation.
--allow-incomplete (also --incomplete) always forces snapshot-only incomplete capture,
even when a stale local history tree would pass validation.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from azure_region_monitor.history import update_history
from azure_region_monitor.models import Snapshot

if __package__:
    from .publication_budget import checked_path, regular_files, write_json
else:
    from publication_budget import checked_path, regular_files, write_json

SCHEMA_VERSION = 1


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Observation timestamp must be an explicit ISO-8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Observation timestamp needs an explicit UTC offset: {value}")
    return parsed.astimezone(timezone.utc)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _json(path: Path) -> dict[str, Any]:
    checked_path(path)
    if not path.is_file():
        raise ValueError(f"Missing regular JSON file: {path}")
    try:
        raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (OSError, EOFError, UnicodeError, ValueError, zlib.error) as error:
        raise ValueError(f"Invalid JSON data in {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _snapshot(path: Path) -> tuple[Snapshot, datetime, str]:
    payload = _json(path)
    timestamp = _timestamp(payload.get("timestamp"))
    snapshot = Snapshot.model_validate(payload)
    snapshot.timestamp = timestamp
    canonical = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return snapshot, timestamp, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _relative(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected a nonempty relative file reference: {value!r}")
    parts = PurePosixPath(value).parts
    if (
        "\\" in value or ":" in value or "\x00" in value or "?" in value or "#" in value
        or PureWindowsPath(value).drive or value.startswith("/")
        or any(part in ("", ".", "..") for part in value.split("/"))
        or not parts
    ):
        raise ValueError(f"Unsafe or remote file reference; materialize history locally: {value!r}")
    target = checked_path(root.joinpath(*parts))
    if not target.is_relative_to(root):
        raise ValueError(f"File reference escapes its tree: {value!r}")
    return target


def _references(payload: Any) -> list[str]:
    references: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.endswith("_path") and value is not None:
                if not isinstance(value, str) or not value:
                    raise ValueError(f"Invalid history reference {key}: {value!r}")
                references.append(value)
            else:
                references.extend(_references(value))
    elif isinstance(payload, list):
        for value in payload:
            references.extend(_references(value))
    return references


def _snapshot_metadata(
    path: Path, cache: dict[Path, tuple[datetime, str]]
) -> tuple[datetime, str]:
    if path not in cache:
        _, timestamp, digest = _snapshot(path)
        cache[path] = (timestamp, digest)
    return cache[path]


def _history_reference(
    history: Path, value: Any, cache: dict[Path, tuple[datetime, str]] | None = None
) -> Path:
    target = _relative(history, value)
    if (
        not target.exists()
        and isinstance(value, str)
        and re.fullmatch(r"snapshots/[0-9]{4}-[0-9]{2}-[0-9]{2}\.json", value)
    ):
        expected_date = date.fromisoformat(target.stem)
        compressed = checked_path(target.with_suffix(".json.gz"))
        if compressed.is_file():
            timestamp, _ = _snapshot_metadata(compressed, cache if cache is not None else {})
            if timestamp.date() != expected_date:
                raise ValueError(f"History date does not match compressed snapshot: {compressed}")
            return compressed
    return target


def validate_history(history: Path) -> dict[str, Any]:
    history = checked_path(history)
    files = regular_files(history)
    index = _json(history / "index.json")
    if "archive" in index or "public_recent_days" in index:
        raise ValueError(
            "History index is a public projection; materialize the complete history before recovery"
        )
    days = index.get("days")
    if not isinstance(days, list):
        raise ValueError("History index must contain a days array")
    snapshot_metadata: dict[Path, tuple[datetime, str]] = {}
    for path in files:
        if path.relative_to(history).parts[0] == "snapshots":
            _snapshot_metadata(path, snapshot_metadata)
        elif path.name.endswith((".json", ".json.gz")):
            for reference in _references(_json(path)):
                target = _history_reference(history, reference, snapshot_metadata)
                if not target.is_file():
                    raise ValueError(f"Missing history reference {reference!r} from {path}")
    observations: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for entry in days:
        if not isinstance(entry, dict) or not isinstance(entry.get("date"), str):
            raise ValueError("Each history day must be an object with a date")
        day = entry["date"]
        if date.fromisoformat(day).isoformat() != day or day in seen_dates:
            raise ValueError(f"Invalid or duplicate history date: {day}")
        seen_dates.add(day)
        path = _history_reference(history, entry.get("snapshot_path"), snapshot_metadata)
        timestamp, digest = _snapshot_metadata(path, snapshot_metadata)
        if timestamp.date().isoformat() != day:
            raise ValueError(f"History date does not match snapshot timestamp: {path}")
        if "snapshot_timestamp" in entry and _timestamp(entry["snapshot_timestamp"]) != timestamp:
            raise ValueError(f"History snapshot timestamp does not match: {path}")
        observations.append({
            "timestamp": timestamp, "path": path, "digest": digest,
            "relative_path": entry["snapshot_path"],
        })
    observations.sort(key=lambda item: item["timestamp"])
    if observations:
        latest = observations[-1]
        if index.get("latest_date") != latest["timestamp"].date().isoformat():
            raise ValueError("History latest_date must identify the newest indexed observation")
        if index.get("latest_snapshot_path") != latest["relative_path"]:
            raise ValueError("History latest_snapshot_path must identify the newest observation")
    elif index.get("latest_date") or index.get("latest_snapshot_path"):
        raise ValueError("Empty history index must not claim a latest observation")
    # Validate orphan snapshots too: they must not hide a newer baseline or corrupt evidence.
    for path in files:
        if path.relative_to(history).parts[0] == "snapshots":
            timestamp, digest = _snapshot_metadata(path, snapshot_metadata)
            if not observations or timestamp > observations[-1]["timestamp"]:
                raise ValueError(f"Unindexed snapshot newer than the history baseline: {path}")
            matches = [entry for entry in observations if entry["timestamp"] == timestamp]
            if any(entry["digest"] != digest for entry in matches):
                raise ValueError(f"Conflicting history snapshots at {timestamp.isoformat()}")
    return {
        "latest_timestamp": observations[-1]["timestamp"].isoformat() if observations else None,
        "observations": observations,
    }


def _inventory(root: Path) -> dict[str, dict[str, Any]]:
    entries = {}
    for path in regular_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == "manifest.json":
            continue
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        entries[relative] = {"bytes": size, "sha256": digest.hexdigest()}
    return entries


def _new_output(output: Path, inputs: list[Path]) -> Path:
    output = checked_path(output)
    for source in inputs:
        source = checked_path(source)
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError(f"Output must not overlap an input: {source}")
    if output.exists():
        raise ValueError(f"Output already exists; choose a new directory: {output}")
    return output


def _validate_baseline_observation(
    baseline: dict[str, Any], observed_at: datetime, digest: str
) -> None:
    if baseline["latest_timestamp"] and _timestamp(baseline["latest_timestamp"]) > observed_at:
        raise ValueError("History baseline is newer than the bundled observation")
    if any(
        entry["timestamp"] == observed_at and entry["digest"] != digest
        for entry in baseline["observations"]
    ):
        raise ValueError(f"Conflicting baseline observation at {observed_at.isoformat()}")


def create_bundle(
    snapshot: Path,
    history: Path | None,
    output: Path,
    *,
    provenance: str | None = None,
    incomplete: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    if incomplete and not (reason and reason.strip()):
        raise ValueError("--incomplete requires a nonempty --reason")
    if not incomplete and reason is not None:
        raise ValueError("--reason requires --incomplete")
    if not incomplete and history is None:
        raise ValueError("Complete bundles require --history; use --incomplete --reason for failures")
    snapshot = checked_path(snapshot)
    if snapshot.suffix == ".gz":
        raise ValueError("--snapshot must be uncompressed JSON; history snapshots may be compressed")
    _, observed_at, snapshot_digest = _snapshot(snapshot)
    output = _new_output(output, [snapshot] + ([history] if history is not None else []))
    output.mkdir(parents=True)
    shutil.copyfile(snapshot, output / "snapshot.json")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "incomplete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "observation_timestamp": observed_at.isoformat(),
        "snapshot_path": "snapshot.json",
        "provenance": provenance,
        "history_baseline": None,
        "reason": reason if incomplete else "History validation has not completed.",
        "files": _inventory(output),
    }
    write_json(output / "manifest.json", manifest)
    if not incomplete:
        try:
            if history is None:
                raise ValueError("Complete bundles require a history directory")
            if _snapshot(output / "snapshot.json")[2] != snapshot_digest:
                raise ValueError("Snapshot changed while the bundle was being created")
            regular_files(history)
            shutil.copytree(history, output / "history", symlinks=True)
            # Validate the captured bytes, not a second copy of every historical snapshot.
            copied = validate_history(output / "history")
            _validate_baseline_observation(copied, observed_at, snapshot_digest)
            manifest["history_baseline"] = {
                "index_path": "history/index.json",
                "latest_timestamp": copied["latest_timestamp"],
                "day_count": len(copied["observations"]),
            }
            manifest["status"] = "complete"
            manifest["reason"] = None
        except (OSError, ValueError) as error:
            manifest["reason"] = f"History collection/validation failed: {error}"
    manifest["files"] = _inventory(output)
    write_json(output / "manifest.json", manifest)
    return manifest


def verify_bundle(bundle: Path) -> dict[str, Any]:
    bundle = checked_path(bundle)
    actual = _inventory(bundle)
    manifest = _json(bundle / "manifest.json")
    if (
        type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != SCHEMA_VERSION
    ):
        raise ValueError(f"Unsupported recovery manifest schema: {bundle}")
    if manifest.get("status") != "complete":
        raise ValueError(f"Incomplete recovery bundle cannot be replayed: {manifest.get('reason')}")
    if manifest.get("reason") is not None:
        raise ValueError("A complete bundle must not contain an incomplete reason")
    _timestamp(manifest.get("created_at"))
    if manifest.get("snapshot_path") != "snapshot.json":
        raise ValueError("Manifest snapshot_path must be snapshot.json")
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Manifest files must be a nonempty inventory")
    for reference, metadata in expected.items():
        _relative(bundle, reference)
        if not isinstance(metadata, dict) or set(metadata) != {"bytes", "sha256"}:
            raise ValueError(f"Invalid manifest file metadata: {reference}")
        if type(metadata["bytes"]) is not int or metadata["bytes"] < 0:
            raise ValueError(f"Invalid manifest byte count: {reference}")
        if not isinstance(metadata["sha256"], str) or len(metadata["sha256"]) != 64:
            raise ValueError(f"Invalid manifest hash: {reference}")
    if set(expected) != set(actual):
        raise ValueError(
            f"Bundle inventory mismatch; missing={sorted(set(expected) - set(actual))}, "
            f"unexpected={sorted(set(actual) - set(expected))}"
        )
    for reference in expected:
        if expected[reference] != actual[reference]:
            raise ValueError(f"Bundle hash/size mismatch: {reference}")
    _, timestamp, digest = _snapshot(bundle / "snapshot.json")
    if _timestamp(manifest.get("observation_timestamp")) != timestamp:
        raise ValueError("Manifest observation timestamp does not match its snapshot")
    baseline = validate_history(bundle / "history")
    expected_baseline = {
        "index_path": "history/index.json", "latest_timestamp": baseline["latest_timestamp"],
        "day_count": len(baseline["observations"]),
    }
    if manifest.get("history_baseline") != expected_baseline:
        raise ValueError("Manifest baseline does not match bundled history")
    _validate_baseline_observation(baseline, timestamp, digest)
    return manifest


def replay_bundles(bundles: list[Path], history: Path, output: Path) -> dict[str, Any]:
    if not bundles:
        raise ValueError("Replay requires at least one --bundle")
    history = checked_path(history)
    output = _new_output(output, [history, *bundles])
    baseline = validate_history(history)
    observations: dict[datetime, dict[str, Any]] = {}
    duplicates = 0
    for bundle in bundles:
        bundle = checked_path(bundle)
        manifest = verify_bundle(bundle)
        path = bundle / "snapshot.json"
        _, timestamp, digest = _snapshot(path)
        if timestamp in observations:
            if observations[timestamp]["digest"] != digest:
                raise ValueError(f"Conflicting observations at {timestamp.isoformat()}")
            duplicates += 1
            continue
        observations[timestamp] = {
            "path": path, "digest": digest, "provenance": manifest.get("provenance"),
        }
    timestamps = sorted(observations)
    baseline_timestamp = (
        _timestamp(baseline["latest_timestamp"]) if baseline["latest_timestamp"] else None
    )
    if baseline_timestamp is not None and baseline_timestamp >= timestamps[0]:
        raise ValueError(
            "Replay requires a baseline strictly older than every supplied observation; "
            "supply an earlier verified history tree (or an explicit empty index)."
        )
    gaps = []
    ordered = ([baseline_timestamp] if baseline_timestamp is not None else []) + timestamps
    for before, after in zip(ordered, ordered[1:]):
        absent_days = (after.date() - before.date()).days - 1
        if absent_days > 0:
            gaps.append({
                "after_timestamp": before.isoformat(), "before_timestamp": after.isoformat(),
                "first_unobserved_date": (before.date() + timedelta(days=1)).isoformat(),
                "last_unobserved_date": (after.date() - timedelta(days=1)).isoformat(),
                "days": absent_days,
            })
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "status": "complete",
        "baseline_latest_timestamp": baseline["latest_timestamp"],
        "duplicates_skipped": duplicates,
        "daily_alias_policy": "Latest observation timestamp per UTC date; all raw observations retained.",
        "coverage": (
            "Only supplied observations are replayed. Unobserved changes, including intraday "
            "changes, remain unknown; missing dates are not interpolated."
        ),
        "unobserved_date_ranges": gaps,
        "observations": [], "baseline_observations": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as staging:
        stage = Path(staging)
        shutil.copytree(history, stage / "history", symlinks=True)
        (stage / "observations").mkdir()
        for entry in baseline["observations"]:
            name = entry["timestamp"].strftime("%Y%m%dT%H%M%S.%fZ")
            extension = ".json.gz" if entry["path"].suffix == ".gz" else ".json"
            target = stage / "observations" / f"{name}{extension}"
            shutil.copyfile(entry["path"], target)
            report["baseline_observations"].append({
                "timestamp": entry["timestamp"].isoformat(),
                "snapshot_path": target.relative_to(stage).as_posix(),
            })
        for timestamp in timestamps:
            entry = observations[timestamp]
            name = timestamp.strftime("%Y%m%dT%H%M%S.%fZ") + ".json"
            target = stage / "observations" / name
            shutil.copyfile(entry["path"], target)
            if _snapshot(target)[2] != entry["digest"]:
                raise ValueError(f"Observation changed after verification: {timestamp.isoformat()}")
            update_history(target, stage / "history")
            report["observations"].append({
                "timestamp": timestamp.isoformat(),
                "snapshot_path": target.relative_to(stage).as_posix(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "provenance": entry["provenance"],
            })
        (stage / "snapshots").mkdir()
        shutil.copyfile(observations[timestamps[-1]]["path"], stage / "snapshots" / "latest.json")
        validate_history(stage / "history")
        write_json(stage / "replay-report.json", report)
        stage.rename(output)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Save a snapshot and complete local history")
    create.add_argument("--snapshot", type=Path, required=True)
    create.add_argument("--history", type=Path)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--provenance")
    create.add_argument(
        "--incomplete", "--allow-incomplete", dest="incomplete", action="store_true",
        help="Force snapshot-only incomplete capture even if local history is valid (exit 1)",
    )
    create.add_argument("--reason", help="Explanation for forced incomplete capture")
    verify = commands.add_parser("verify", help="Verify all hashes and history references")
    verify.add_argument("--bundle", type=Path, required=True)
    replay = commands.add_parser("replay", help="Replay into a new directory without modifying inputs")
    replay.add_argument("--bundle", type=Path, action="append", required=True)
    replay.add_argument("--history", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            reason = args.reason
            if args.incomplete and reason is None:
                reason = "History collection was not confirmed complete; incomplete capture requested."
            manifest = create_bundle(
                args.snapshot, args.history, args.output, provenance=args.provenance,
                incomplete=args.incomplete, reason=reason,
            )
            if manifest["status"] != "complete":
                print(
                    f"Incomplete recovery bundle retained at {args.output}: {manifest['reason']}",
                    file=sys.stderr,
                )
                return 1
            print(f"Complete recovery bundle: {args.output}")
        elif args.command == "verify":
            verify_bundle(args.bundle)
            print(f"Verified complete recovery bundle: {args.bundle}")
        else:
            report = replay_bundles(args.bundle, args.history, args.output)
            print(
                f"Replayed {len(report['observations'])} observations into {args.output}; "
                f"skipped {report['duplicates_skipped']} identical duplicates."
            )
    except (OSError, ValueError) as error:
        print(f"Publication recovery error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
