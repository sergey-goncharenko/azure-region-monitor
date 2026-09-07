"""Prepare one shared repository fixture without running probes or model calls."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def prepare_inputs(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Visual evidence inputs must be copied outside the source data directory.")
    latest = source / "snapshots" / "latest.json"
    if not latest.is_file():
        raise ValueError(f"Visual evidence needs a repository snapshot: {latest}")
    destination.mkdir(parents=True, exist_ok=False)
    for name in ("snapshots", "diffs", "history"):
        path = source / name
        if path.is_dir():
            shutil.copytree(path, destination / name)

    history = destination / "history"
    if (history / "index.json").exists():
        return destination

    # Raw dated snapshots let each revision derive its own briefing schema. Do not
    # feed head-generated briefing objects to older base rendering code.
    history.mkdir(exist_ok=True)
    archive = history / "snapshots"
    archive.mkdir(exist_ok=True)
    by_date: dict[str, dict[str, str]] = {}
    paths = sorted(path for path in (destination / "snapshots").glob("*.json") if path.name != "latest.json")
    paths.append(destination / "snapshots" / "latest.json")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        timestamp = datetime.fromisoformat(payload["timestamp"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        date = timestamp.date().isoformat()
        name = f"{date}.json"
        shutil.copyfile(path, archive / name)
        by_date[date] = {
            "date": date, "snapshot_timestamp": timestamp.isoformat(),
            "snapshot_path": f"snapshots/{name}",
        }
    days = sorted(by_date.values(), key=lambda item: item["date"], reverse=True)
    index = {
        "latest_date": days[0]["date"],
        "latest_snapshot_path": days[0]["snapshot_path"],
        "days": days,
    }
    (history / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare_inputs(args.source, args.output))


if __name__ == "__main__":
    main()
