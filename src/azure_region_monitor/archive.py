"""Offline complete archive export and bounded public projection.

Both output roots must be empty and disjoint from each other and all inputs.
Rendering cost and storage still scale with complete history; only the deployable
public artifact is bounded. Uploaders publish every manifest object directly
under the operator-provided archive_base_url publication prefix.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from azure_region_monitor.history import (
    LATENCY_HISTORY_SNAPSHOTS,
    _required_history_paths,
    _resolve_history_reference,
    _safe_history_path,
    _validate_history_object,
    _write_json,
)
from azure_region_monitor.storage import load_snapshot

_BLOB_HOST = re.compile(
    r"[a-z0-9]{3,24}\.blob\.(?:core\.windows\.net|core\.usgovcloudapi\.net|core\.chinacloudapi\.cn)"
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_GENERATION = re.compile(r"[0-9a-f]{64}")
_ASSETS = Path(__file__).parent / "assets"
_CATALOG_PAGE_SIZE = 30


def validate_archive_base_url(value: str) -> str:
    parsed = urlsplit(value)
    parts = parsed.path.strip("/").split("/")
    if (
        any(char.isspace() or ord(char) < 32 for char in value)
        or "//" in parsed.path
        or not parsed.path.startswith("/")
        or parsed.scheme != "https"
        or not _BLOB_HOST.fullmatch(parsed.netloc)
        or parsed.query or parsed.fragment or "?" in value or "#" in value
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", parts[0])
        or "--" in parts[0]
        or any(not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", part) for part in parts)
    ):
        raise ValueError("archive_base_url must be a credential-free HTTPS Azure Blob container/prefix URL")
    return value.rstrip("/")


def archive_history_url(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        raise ValueError("Invalid archive history metadata")
    base = validate_archive_base_url(str(metadata.get("archive_base_url", "")))
    generation = metadata.get("generation")
    if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
        raise ValueError("Invalid archive generation")
    return f"{base}/api/history"


def _validate_roots(outputs: list[Path], inputs: list[Path]) -> None:
    resolved = [path.resolve() for path in outputs]
    for index, output in enumerate(outputs):
        if output.is_symlink() or output.resolve() == Path(output.anchor).resolve():
            raise ValueError("Archive/public output must not be a filesystem root or symlink")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError(f"Archive/public output must be absent or empty: {output}")
        for other in [*resolved[index + 1:], *(path.resolve() for path in inputs)]:
            if resolved[index].is_relative_to(other) or other.is_relative_to(resolved[index]):
                raise ValueError("Archive/public outputs must be disjoint from each other and inputs")


def _history_files(history: Path) -> dict[str, Path]:
    if history.is_symlink():
        raise ValueError("Archive history must not be a symlink")
    files = {}
    for path in sorted(history.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Archive history must not contain symlinks: {path}")
        if path.is_file():
            relative = path.relative_to(history).as_posix()
            _safe_history_path(history, relative)
            files[relative] = path
    if "index.json" not in files:
        raise ValueError("Complete archive requires history/index.json")
    return files


def _validated_history(history: Path) -> dict[str, Path]:
    files = _history_files(history)
    index = _validate_history_object(files["index.json"], "index.json")
    if "archive" in index or "public_recent_days" in index:
        raise ValueError("Complete archive requires full history, not a public projection; fetch history first")
    days = index.get("days")
    if not isinstance(days, list):
        raise ValueError("Complete archive index requires days")
    seen = set()
    for day in days:
        value = day.get("date") if isinstance(day, dict) else None
        if not isinstance(value, str) or not _DATE.fullmatch(value):
            raise ValueError("Archive index contains an invalid observation date")
        date.fromisoformat(value)
        if value in seen:
            raise ValueError(f"Duplicate archive date: {value}")
        seen.add(value)
        if not day.get("snapshot_path") or not day.get("change_path"):
            raise ValueError(f"Complete archive day {value} requires snapshot_path and change_path")
    references = _required_history_paths(index)
    observation_dates = {}
    for relative, path in files.items():
        if not relative.endswith((".json", ".json.gz")):
            raise ValueError(f"Unexpected history object: {relative}")
        value = _validate_history_object(path, relative)
        observation_dates[relative] = (
            str(value.get("timestamp", ""))[:10] if relative.startswith("snapshots/")
            else value.get("date")
        )
        if not relative.startswith("snapshots/"):
            references.update(_required_history_paths(value))
    for relative in references:
        if relative not in files and not (
            relative.startswith("snapshots/") and relative.endswith(".json")
            and relative + ".gz" in files
        ):
            raise ValueError(f"Required archive history object is missing: {relative}")
    for day in days:
        for key in ("snapshot_path", "change_path"):
            relative = day[key]
            actual_date = observation_dates.get(relative, observation_dates.get(relative + ".gz"))
            if actual_date != day["date"]:
                raise ValueError(f"History observation date does not match index: {relative}")
    return files


def _copy_complete_history(files: dict[str, Path], target: Path) -> None:
    for relative, source in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)


def _recent(document: dict[str, Any], cutoff: str) -> dict[str, Any]:
    return {**document, "days": [day for day in document.get("days", []) if day["date"] >= cutoff]}


def _catalog(archive: Path, index: dict[str, Any]) -> None:
    entries = []
    for day in sorted(index["days"], key=lambda item: item["date"], reverse=True):
        links = {"snapshot": f"/api/history/{day['snapshot_path']}", "changes": f"/api/history/{day['change_path']}"}
        for kind in ("blog", "feedback", "reading-check"):
            path = f"{kind}/{day['date']}.html"
            if (archive / path).exists():
                links[kind] = "/" + path
        entries.append({"date": day["date"], "links": links})
    chunks = [entries[index:index + _CATALOG_PAGE_SIZE] for index in range(0, len(entries), _CATALOG_PAGE_SIZE)] or [[]]
    for number, chunk in enumerate(chunks):
        _write_json(archive / "archive" / "catalog" / f"{number + 1}.json", {
            "schema_version": 1,
            "entries": chunk,
            "page": number + 1,
            "total_days": len(entries),
            "next": f"archive/catalog/{number + 2}.json" if number + 1 < len(chunks) else None,
        })


def _write_manifest(archive: Path) -> str:
    files = []
    for path in sorted(archive.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            files.append({
                "path": path.relative_to(archive).as_posix(),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
    generation = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json(archive / "archive-manifest.json", {
        "schema_version": 1, "generation": generation, "files": files,
        "total_bytes": sum(item["size_bytes"] for item in files), "file_count": len(files),
    })
    return generation


def build_archive_publication(
    output_dir: Path, snapshot_path: Path, diff_path: Path, history_path: Path,
    *, archive_output: Path | None, archive_base_url: str | None, recent_days: int,
) -> None:
    from azure_region_monitor.static_site import build_static_site, _write_site_pages

    if archive_output is None or archive_base_url is None:
        raise ValueError("archive_output and archive_base_url must be provided together")
    base = validate_archive_base_url(archive_base_url)
    if isinstance(recent_days, bool) or not isinstance(recent_days, int) or recent_days < 1:
        raise ValueError("archive_recent_days must be a positive integer")
    _validate_roots([output_dir, archive_output], [history_path, snapshot_path, diff_path])
    files = _validated_history(history_path)
    snapshot = load_snapshot(snapshot_path)
    cutoff = (snapshot.timestamp.date() - timedelta(days=recent_days - 1)).isoformat()
    with tempfile.TemporaryDirectory(prefix="azure-archive-") as temporary:
        root = Path(temporary)
        source = root / "history"
        complete = root / "archive"
        public = root / "public"
        _copy_complete_history(files, source)
        build_static_site(complete, snapshot_path, diff_path, source)
        complete_history = complete / "api" / "history"
        for path in source.rglob("*"):
            if path.is_file():
                destination = complete_history / path.relative_to(source)
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
        index = json.loads((complete_history / "index.json").read_bytes())
        current_path = complete_history / "snapshots" / f"{snapshot.timestamp.date()}.json.gz"
        if not current_path.exists():
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_bytes(gzip.compress(snapshot_path.read_bytes(), mtime=0))
        _validated_history(complete_history)
        _catalog(complete, index)
        generation = _write_manifest(complete)
        metadata = {
            "schema_version": 1, "archive_base_url": base, "generation": generation,
            "api_base_path": "/api/archive/", "index_path": "api/history/index.json",
            "public_recent_days": recent_days,
        }
        projected = _recent(index, cutoff)
        recent = _recent(json.loads((complete_history / "recent-changes.json").read_bytes()), cutoff)
        latency_path = complete_history / "latency-history.json"
        latency = json.loads(latency_path.read_bytes()) if latency_path.exists() else None
        if latency is not None:
            latency = {
                **latency,
                "days": sorted(
                    latency.get("days", []),
                    key=lambda day: day.get("timestamp", day.get("date", "")),
                    reverse=True,
                )[:LATENCY_HISTORY_SNAPSHOTS],
            }
        public_history = public / "api" / "history"
        public_history.mkdir(parents=True)
        for path in (complete / "api").iterdir():
            if path.name != "history":
                destination = public / "api" / path.name
                if path.is_dir():
                    shutil.copytree(path, destination)
                else:
                    shutil.copyfile(path, destination)
        _write_json(public_history / "recent-changes.json", recent)
        if latency is not None:
            _write_json(public_history / "latency-history.json", latency)
        retained = {
            day[key] for day in projected["days"] for key in ("snapshot_path", "change_path")
        } | {f"snapshots/{snapshot.timestamp.date()}.json.gz"}
        for relative in sorted(retained):
            source_path = _resolve_history_reference(complete_history, relative)
            target_path = public_history / source_path.relative_to(complete_history)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
        _write_site_pages(public, snapshot, projected, recent, latency)
        _write_json(public / "archive-config.json", metadata)
        shutil.copyfile(_ASSETS / "archive.html", public / "archive.html")
        shutil.copyfile(_ASSETS / "archive-browser.js", public / "assets" / "archive-browser.js")
        notice = (
            '<aside class="archive-notice" aria-label="Complete history archive">'
            f'This publication keeps the latest {recent_days} calendar days locally. '
            '<a href="/archive.html">Browse all recorded dates and complete historical evidence</a>. '
            'Older evidence is preserved in the archive, not discarded.</aside>'
        )
        for path in public.rglob("*.html"):
            markup = path.read_text(encoding="utf-8")
            markup = markup.replace("</header>", "</header>" + notice, 1) if "</header>" in markup else markup.replace("<body>", "<body>" + notice, 1)
            path.write_text(markup, encoding="utf-8")
        config_path = public / "staticwebapp.config.json"
        config = json.loads(config_path.read_bytes())
        config["platform"] = {"apiRuntime": "node:22"}
        config["navigationFallback"] = {
            "rewrite": "/archive.html",
            "exclude": ["/api/*", "/assets/*", "/*.{json,gz,xml,txt,svg,css,js,ico,png,jpg}"],
        }
        _write_json(config_path, config)
        _validate_roots([output_dir, archive_output], [history_path, snapshot_path, diff_path])
        shutil.copytree(complete, archive_output, dirs_exist_ok=True)
        shutil.copytree(public, output_dir, dirs_exist_ok=True)
