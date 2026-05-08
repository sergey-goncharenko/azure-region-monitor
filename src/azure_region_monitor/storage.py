from __future__ import annotations

import json
from pathlib import Path

from azure_region_monitor.models import Diff, Snapshot


def load_snapshot(path: Path) -> Snapshot:
    return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))


def write_snapshot(path: Path, snapshot: Snapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_to_json(snapshot), encoding="utf-8")


def load_diff(path: Path) -> Diff:
    return Diff.model_validate_json(path.read_text(encoding="utf-8"))


def write_diff(path: Path, diff: Diff) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_to_json(diff), encoding="utf-8")


def _to_json(model: Snapshot | Diff) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
