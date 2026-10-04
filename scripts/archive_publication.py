"""Opt-in immutable Blob archive generations for dashboard publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".publication"


def archive_root(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", parsed.netloc)
        or not re.fullmatch(r"/[a-z0-9][a-z0-9-]{1,61}[a-z0-9]/?", parsed.path)
        or parsed.query or parsed.fragment
    ):
        raise ValueError("Archive URL must be an HTTPS Azure Blob container URL without credentials.")
    return value.rstrip("/")


def _json_url(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Archive publication pointer is not an object.")
    return result


def sources(
    root: str, snapshot_url: str, history_url: str, *, bootstrap: bool = False,
    snapshot_override: bool = False, history_override: bool = False,
) -> dict[str, str]:
    if not root:
        return {"snapshot_url": snapshot_url, "history_url": history_url, "archive_base_url": ""}
    root = archive_root(root)
    try:
        pointer = _json_url(root + "/publication-latest.json")
    except urllib.error.HTTPError as error:
        if error.code != 404 or not bootstrap:
            raise RuntimeError("Cannot read archive pointer; publication must not omit history.") from error
        print("Archive bootstrap explicitly enabled: preserving history from the existing public site.")
        pointer = None
    if pointer is not None:
        base = pointer.get("archive_base_url", "")
        if (
            pointer.get("schema_version") != 1
            or not isinstance(base, str)
            or not re.fullmatch(re.escape(root) + r"/publications/[0-9]+-[0-9]+", base)
            or not re.fullmatch(r"[0-9a-f]{64}", str(pointer.get("manifest_sha256", "")))
        ):
            raise ValueError("Archive pointer has invalid schema, generation URL, or manifest digest.")
        with urllib.request.urlopen(base + "/_publication-manifest.json", timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != pointer["manifest_sha256"]:
            raise ValueError("Archive generation manifest does not match its committed pointer.")
        if not snapshot_override:
            snapshot_url = base + "/api/latest.json"
        if not history_override:
            history_url = base + "/api/history"
    run, attempt = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not re.fullmatch(r"[0-9]+", run) or not re.fullmatch(r"[0-9]+", attempt):
        raise ValueError("A unique GitHub run ID and attempt are required for archive publication.")
    return {
        "snapshot_url": snapshot_url,
        "history_url": history_url,
        "archive_base_url": f"{root}/publications/{run}-{attempt}",
    }


def build(base: str) -> None:
    from azure_region_monitor.static_site import build_static_site

    if base:
        WORK.mkdir(exist_ok=True)
        build_static_site(
            ROOT / "public", archive_output=WORK / "archive", archive_base_url=base
        )
        api = WORK / "api"
        if api.exists():
            raise ValueError("Archive API output already exists; use a fresh publication workspace.")
        shutil.copytree(ROOT / "api", api)
        generation = _export_generation(WORK / "archive")
        (api / "archive-config.json").write_text(
            json.dumps({"archive_base_url": base, "generation": generation}) + "\n", encoding="utf-8"
        )
    else:
        build_static_site(ROOT / "public")


def inventory(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Archive staging directory must be an existing real directory.")
    entries = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Archive contains a symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Archive contains a non-regular file: {path}")
        relative = path.relative_to(directory).as_posix()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        entries[relative] = {"bytes": path.stat().st_size, "sha256": digest}
    if "api/latest.json" not in entries or "api/history/index.json" not in entries:
        raise ValueError("Archive lacks its current snapshot or complete history index.")
    return entries


def _export_generation(directory: Path) -> str:
    manifest = json.loads((directory / "archive-manifest.json").read_text(encoding="utf-8"))
    generation = manifest.get("generation")
    if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{64}", generation):
        raise ValueError("Archive export lacks a valid content generation.")
    return generation


def _az(*args: str) -> None:
    completed = subprocess.run(
        ["az", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if completed.returncode:
        raise RuntimeError(f"Azure archive operation failed: {completed.stderr.strip()}")


def _verify_object(item: tuple[str, dict[str, Any]], base: str) -> None:
    relative, expected = item
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(
        base + "/" + urllib.parse.quote(relative, safe="/"),
        headers={"Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > expected["bytes"]:
                raise ValueError(f"Published archive object is larger than expected: {relative}.")
            digest.update(chunk)
    if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError(f"Published archive verification failed for {relative}.")


def upload(root: str, base: str, directory: Path) -> None:
    root = archive_root(root)
    if not re.fullmatch(re.escape(root) + r"/publications/[0-9]+-[0-9]+", base):
        raise ValueError("Archive generation is outside the configured container.")
    generation = _export_generation(directory)
    entries = inventory(directory)
    manifest_path = directory / "_publication-manifest.json"
    if manifest_path.exists():
        raise ValueError("Archive generation manifest already exists; do not overwrite generations.")
    manifest = {
        "schema_version": 1, "files": entries,
        "total_bytes": sum(item["bytes"] for item in entries.values()),
        "file_count": len(entries),
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    parsed = urllib.parse.urlsplit(root)
    account = parsed.hostname.split(".")[0]
    container = parsed.path.strip("/")
    prefix = base.removeprefix(root + "/")
    _az(
        "storage", "blob", "upload-batch", "--account-name", account,
        "--destination", container, "--destination-path", prefix,
        "--source", str(directory), "--auth-mode", "login",
        "--overwrite", "false", "--validate-content", "--no-progress", "--only-show-errors",
    )
    manifest_payload = manifest_path.read_bytes()
    verification = {
        **entries,
        "_publication-manifest.json": {
            "bytes": len(manifest_payload), "sha256": hashlib.sha256(manifest_payload).hexdigest(),
        },
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: _verify_object(item, base), verification.items()))
    pointer = {
        "schema_version": 1, "archive_base_url": base,
        "generation": generation,
        "manifest_sha256": verification["_publication-manifest.json"]["sha256"],
        "run_url": (
            f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
            f"{os.environ.get('GITHUB_RUN_ID', '')}"
        ),
    }
    pointer_path = directory.parent / "publication-latest.json"
    pointer_path.write_text(json.dumps(pointer, sort_keys=True) + "\n", encoding="utf-8")
    _az(
        "storage", "blob", "upload", "--account-name", account,
        "--container-name", container, "--name", "publication-latest.json",
        "--file", str(pointer_path), "--auth-mode", "login", "--overwrite", "true",
        "--validate-content", "--content-type", "application/json",
        "--content-cache-control", "no-cache", "--no-progress", "--only-show-errors",
    )
    if _json_url(root + "/publication-latest.json") != pointer:
        raise ValueError("Archive recovery pointer verification failed; do not deploy.")
    print(f"Verified {len(verification)} archive objects before committing the recovery pointer.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("sources")
    resolve.add_argument("--snapshot-url", required=True)
    resolve.add_argument("--history-url", required=True)
    resolve.add_argument("--github-output", type=Path, required=True)
    resolve.add_argument("--snapshot-override", action="store_true")
    resolve.add_argument("--history-override", action="store_true")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--archive-base-url", default="")
    publish = sub.add_parser("upload")
    publish.add_argument("--archive-base-url", required=True)
    args = parser.parse_args()
    root = os.environ.get("AZWATCH_ARCHIVE_BASE_URL", "")
    if args.command == "sources":
        result = sources(
            root, args.snapshot_url, args.history_url,
            bootstrap=os.environ.get("AZWATCH_ARCHIVE_BOOTSTRAP", "").lower() == "true",
            snapshot_override=args.snapshot_override, history_override=args.history_override,
        )
        with args.github_output.open("a", encoding="utf-8") as stream:
            for key, value in result.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("Publication source URL contains a newline.")
                stream.write(f"{key}={value}\n")
    elif args.command == "build":
        build(args.archive_base_url)
    else:
        upload(root, args.archive_base_url, WORK / "archive")


if __name__ == "__main__":
    main()
