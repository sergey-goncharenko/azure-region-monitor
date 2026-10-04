import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.error
from datetime import date, timedelta
from pathlib import Path

import pytest

from azure_region_monitor import history
from azure_region_monitor.archive import archive_history_url, validate_archive_base_url
from azure_region_monitor.static_site import build_static_site

BASE_URL = "https://evidencearchive.blob.core.windows.net/history/publications/123456-1"


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root, count=65):
    history_dir = root / "history"
    latest = root / "latest.json"
    for offset in reversed(range(count)):
        day = date(2026, 9, 30) - timedelta(days=offset)
        _write(latest, {
            "timestamp": f"{day}T00:00:00Z",
            "regions": {
                region: {"compute": {
                    f"vmSkus.standard.fixture-{number:03}": {
                        "status": ("available", "unavailable", "unknown", "partial")[(number + day.day) % 4],
                        "message": "Offline synthetic catalog evidence, not a live probe.",
                    } for number in range(48)
                }} for region in ("eastus", "westus", "northeurope")
            },
        })
        history.update_history(latest, history_dir)
    _write(history_dir / "latency-history.json", {
        "days": [{
            "date": str(date(2026, 9, 30) - timedelta(days=offset)),
            "timestamp": f"{date(2026, 9, 30) - timedelta(days=offset)}T00:00:00+00:00",
            "models": {},
        } for offset in range(80)],
    })
    return latest, history_dir


def _build(root, latest, source):
    public = root / "public"
    archive = root / "archive"
    build_static_site(
        public, latest, root / "missing-diff.json", source,
        archive_output=archive, archive_base_url=BASE_URL,
    )
    return public, archive


def _metrics(root):
    files = [path for path in root.rglob("*") if path.is_file()]
    return {"bytes": sum(path.stat().st_size for path in files), "files": len(files)}


@pytest.fixture(scope="module")
def archive_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("archive-fixture")
    latest, source = _fixture(root, count=65)
    public, archive = _build(root, latest, source)
    return root, latest, source, public, archive


def test_complete_archive_preserves_all_snapshots_records_and_dates_without_inflation(archive_fixture):
    _, _, source, public, archive = archive_fixture
    archived = archive / "api" / "history"
    original_index = json.loads((source / "index.json").read_bytes())
    index = json.loads((archived / "index.json").read_bytes())
    assert [day["date"] for day in index["days"]] == [day["date"] for day in original_index["days"]]
    assert len(index["days"]) == 65
    for day in original_index["days"]:
        path = day["snapshot_path"]
        expected = json.loads(gzip.decompress((source / path).read_bytes()))
        assert json.loads(gzip.decompress((archived / path).read_bytes())) == expected
        assert not (archived / path.removesuffix(".gz")).exists()
        source_day = json.loads((source / day["change_path"]).read_bytes())
        archived_day = json.loads((archived / day["change_path"]).read_bytes())
        assert archived_day["date"] == source_day["date"]
        assert archived_day["previous_date"] == source_day["previous_date"]
        assert archived_day["briefing"]["records"] == source_day["briefing"]["records"]
        for kind in ("blog", "feedback", "reading-check"):
            assert (archive / kind / f"{day['date']}.html").is_file()
    assert not (public / "api" / "history" / "index.json").exists()
    assert sorted(path.stem for path in (public / "api/history/changes").glob("*.json")) == sorted(
        day["date"] for day in index["days"][:30]
    )
    latency = json.loads((public / "api" / "history" / "latency-history.json").read_bytes())
    assert len(latency["days"]) == 60
    assert not (public / "blog" / "2026-07-28.html").exists()
    assert (archive / "blog" / "2026-07-28.html").exists()
    assert (archive / "assets" / "briefing.js").is_file()


def test_manifest_verifies_every_exact_object_and_generation(archive_fixture):
    _, _, _, public, archive = archive_fixture
    manifest = json.loads((archive / "archive-manifest.json").read_bytes())
    assert {item["path"] for item in manifest["files"]} == {
        path.relative_to(archive).as_posix() for path in archive.rglob("*")
        if path.is_file() and path.name != "archive-manifest.json"
    }
    for item in manifest["files"]:
        payload = (archive / item["path"]).read_bytes()
        assert item["size_bytes"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
    generation = hashlib.sha256(json.dumps(
        manifest["files"], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert manifest["generation"] == generation
    assert manifest["total_bytes"] == sum(item["size_bytes"] for item in manifest["files"])
    config = json.loads((public / "archive-config.json").read_bytes())
    assert config["generation"] == generation
    assert config["archive_base_url"] == BASE_URL
    assert archive_history_url(config) == f"{BASE_URL}/api/history"
    hosting = json.loads((public / "staticwebapp.config.json").read_bytes())
    assert hosting["platform"] == {"apiRuntime": "node:22"}
    assert hosting["navigationFallback"]["rewrite"] == "/archive.html"
    assert "/api/*" in hosting["navigationFallback"]["exclude"]
    assert "/assets/*" in hosting["navigationFallback"]["exclude"]
    default_hosting = json.loads((archive / "staticwebapp.config.json").read_bytes())
    assert hosting["globalHeaders"] == default_hosting["globalHeaders"]


def test_catalog_pages_reach_every_date_and_public_views_disclose_archive(archive_fixture):
    _, _, source, public, archive = archive_fixture
    next_path = "archive/catalog/1.json"
    dates = []
    while next_path:
        page = json.loads((archive / next_path).read_bytes())
        assert len(page["entries"]) <= 30
        for entry in page["entries"]:
            dates.append(entry["date"])
            for link in entry["links"].values():
                path = archive / link.lstrip("/")
                assert path.is_file() or (
                    link.startswith("/api/history/snapshots/")
                    and path.with_suffix(".json.gz").is_file()
                )
        next_path = page["next"]
    assert dates == [day["date"] for day in json.loads((source / "index.json").read_bytes())["days"]]
    for path in ("index.html", "blog/index.html", "insights/index.html"):
        text = (public / path).read_text(encoding="utf-8")
        assert 'href="/archive.html"' in text
        assert "not discarded" in text
        assert 'href="/blog/2026-07-28.html"' not in text
    for path in ("sitemap.xml", "blog/feed.xml", "llms-full.txt"):
        assert "2026-07-28" not in (public / path).read_text(encoding="utf-8")


def test_public_bytes_and_files_do_not_grow_with_older_retention(archive_fixture, tmp_path):
    _, _, first_source, first_public, first_archive = archive_fixture
    latest, source = _fixture(tmp_path, count=95)
    extended = json.loads((source / "index.json").read_bytes())
    original = json.loads((first_source / "index.json").read_bytes())
    original_dates = {day["date"] for day in original["days"]}
    extended["days"] = original["days"] + [
        day for day in extended["days"] if day["date"] not in original_dates
    ]
    shutil.copytree(first_source, source, dirs_exist_ok=True)
    _write(source / "index.json", {**original, "days": extended["days"]})
    second_public, second_archive = _build(tmp_path, latest, source)
    first = _metrics(first_public)
    second = _metrics(second_public)
    assert second == first
    assert _metrics(second_archive)["bytes"] > _metrics(first_archive)["bytes"]
    assert _metrics(second_archive)["files"] > _metrics(first_archive)["files"]
    full = tmp_path / "default"
    build_static_site(full, latest, tmp_path / "missing.json", source)
    assert _metrics(second_public)["bytes"] < _metrics(full)["bytes"]
    print(json.dumps({"public_65": first, "public_95": second,
                      "archive_65": _metrics(first_archive), "archive_95": _metrics(second_archive),
                      "default_95": _metrics(full)}, sort_keys=True))


@pytest.mark.parametrize("damage", [
    "missing", "gzip", "json", "unsafe", "missing-previous", "wrong-date", "empty-change",
])
def test_invalid_archive_fails_before_writing_outputs(tmp_path, damage):
    latest, source = _fixture(tmp_path, count=3)
    if damage == "missing":
        (source / "changes" / "2026-09-29.json").unlink()
    elif damage == "gzip":
        (source / "snapshots" / "2026-09-29.json.gz").write_bytes(b"not-gzip")
    elif damage == "json":
        (source / "changes" / "2026-09-29.json").write_text("{broken", encoding="utf-8")
    elif damage in {"wrong-date", "empty-change"}:
        _write(source / "changes" / "2026-09-29.json",
               {"date": "2026-09-28"} if damage == "wrong-date" else {})
    else:
        path = source / "index.json"
        index = json.loads(path.read_bytes())
        index["days"][0]["previous_snapshot_path"] = "../escape.json" if damage == "unsafe" else "snapshots/missing.json.gz"
        _write(path, index)
    with pytest.raises(ValueError):
        _build(tmp_path, latest, source)
    assert not (tmp_path / "public").exists()
    assert not (tmp_path / "archive").exists()


def test_legacy_json_alias_reference_is_recovered_losslessly(tmp_path):
    latest, source = _fixture(tmp_path, count=3)
    path = source / "changes" / "2026-09-29.json"
    day = json.loads(path.read_bytes())
    day["previous_snapshot_path"] = day["previous_snapshot_path"].removesuffix(".gz")
    _write(path, day)
    _, archive = _build(tmp_path, latest, source)
    archived = archive / "api/history"
    assert not (archived / day["previous_snapshot_path"]).exists()
    restored = history._load_previous_snapshot(archived, {"snapshot_path": day["previous_snapshot_path"]})
    assert restored == history._load_previous_snapshot(source, {"snapshot_path": day["previous_snapshot_path"]})
    assert restored.timestamp.date().isoformat() == "2026-09-28"


def test_archive_preserves_original_raw_extras_without_generating_more(tmp_path):
    latest, source = _fixture(tmp_path, count=3)
    compressed = source / "snapshots/2026-09-28.json.gz"
    previous_observation = json.loads(gzip.decompress(compressed.read_bytes()))
    previous_observation["timestamp"] = "2026-09-28T00:01:00Z"
    original = json.dumps(previous_observation, indent=3).encode()
    raw = compressed.with_suffix("")
    raw.write_bytes(original)
    _, archive = _build(tmp_path, latest, source)
    exported = archive / "api/history/snapshots"
    assert raw.read_bytes() == original
    assert (exported / raw.name).read_bytes() == original
    assert [path.name for path in exported.glob("*.json")] == [raw.name]
    assert (exported / compressed.name).read_bytes() == compressed.read_bytes()


@pytest.mark.parametrize("url", [
    "http://evidencearchive.blob.core.windows.net/history",
    "https://user:secret@evidencearchive.blob.core.windows.net/history",
    BASE_URL + "?sig=secret", BASE_URL + "?", BASE_URL + "#fragment",
    BASE_URL + "/../escape", BASE_URL + "/%2e%2e/escape",
    "https://evidencearchive.blob.core.windows.net.evil.test/history",
    "https://evidencearchive.blob.core.windows.net:443/history",
    "https://evidencearchive.blob.core.windows.net/", BASE_URL + "//prefix",
    BASE_URL + "/prefix\\escape",
    BASE_URL + "\n", "https://evidencearchive.blob.core.windows.net//history",
])
def test_rejects_untrusted_blob_urls(url):
    with pytest.raises(ValueError, match="HTTPS Azure Blob"):
        validate_archive_base_url(url)


@pytest.mark.parametrize("url", [
    BASE_URL, BASE_URL + "/prefix",
    "https://evidencearchive.blob.core.usgovcloudapi.net/history",
    "https://evidencearchive.blob.core.chinacloudapi.cn/history",
])
def test_accepts_credential_free_blob_urls(url):
    assert validate_archive_base_url(url + "/") == url


@pytest.mark.parametrize("kind", ["same", "nested", "input-parent", "inside-history", "nonempty"])
def test_outputs_are_disjoint_and_never_delete_existing_data(tmp_path, kind):
    latest, source = _fixture(tmp_path, count=2)
    public, archive = tmp_path / "public", tmp_path / "archive"
    if kind == "same":
        archive = public
    elif kind == "nested":
        archive = public / "archive"
    elif kind == "input-parent":
        public = tmp_path
    elif kind == "inside-history":
        archive = source / "archive"
    else:
        public.mkdir()
        (public / "keep.txt").write_text("unrelated", encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError):
        build_static_site(public, latest, tmp_path / "diff.json", source,
                          archive_output=archive, archive_base_url=BASE_URL)
    assert all(path.read_bytes() == payload for path, payload in before.items())


def test_default_build_keeps_all_history_and_has_no_archive_fallback(tmp_path):
    latest, source = _fixture(tmp_path, count=2)
    output = tmp_path / "public"
    build_static_site(output, latest, tmp_path / "missing.json", source)
    assert not (output / "archive-config.json").exists()
    assert not (output / "archive.html").exists()
    config = json.loads((output / "staticwebapp.config.json").read_bytes())
    assert "navigationFallback" not in config
    assert "platform" not in config
    assert len(json.loads((output / "api/history/index.json").read_bytes())["days"]) == 2
    build_static_site(output, latest, tmp_path / "missing.json", source)


def test_archive_rejects_public_projection_as_complete_input(tmp_path):
    latest, source = _fixture(tmp_path, count=2)
    index = json.loads((source / "index.json").read_bytes())
    _write(source / "index.json", {**index, "public_recent_days": 30})
    with pytest.raises(ValueError, match="not a public projection"):
        _build(tmp_path, latest, source)


def test_archive_can_publish_valid_empty_bootstrap(tmp_path):
    latest = tmp_path / "latest.json"
    _write(latest, {"timestamp": "2026-09-30T00:00:00Z", "regions": {}})
    source = tmp_path / "history"
    _write(source / "index.json", {"days": []})
    public, archive = _build(tmp_path, latest, source)
    assert not (public / "api/history/index.json").exists()
    assert json.loads((archive / "api/history/index.json").read_bytes())["latest_date"] == "2026-09-30"
    assert json.loads(gzip.decompress((archive / "api/history/snapshots/2026-09-30.json.gz").read_bytes())) == json.loads(latest.read_bytes())


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def _mock_remote(monkeypatch, payloads):
    calls = []

    def open_url(url, timeout=None):
        calls.append(url)
        if url not in payloads:
            raise urllib.error.HTTPError(url, 404, "missing", {}, None)
        return _Response(payloads[url])

    monkeypatch.setattr(history.urllib.request, "urlopen", open_url)
    return calls


@pytest.mark.parametrize("damage", ["missing", "gzip", "json", "unsafe"])
def test_fetch_is_atomic_for_required_object_failures(tmp_path, monkeypatch, damage):
    local = tmp_path / "history"
    _write(local / "index.json", {"days": [], "existing": True})
    before = (local / "index.json").read_bytes()
    remote = "https://example.test/api/history"
    relative = "../outside.json" if damage == "unsafe" else "snapshots/2026-09-29.json.gz"
    payloads = {remote + "/index.json": json.dumps({"days": [{"snapshot_path": relative}]}).encode(),
                remote + "/recent-changes.json": b"{}"}
    if damage != "missing":
        payloads[remote + "/" + relative] = b"broken" if damage == "gzip" else gzip.compress(b"not-json")
    _mock_remote(monkeypatch, payloads)
    with pytest.raises(ValueError):
        history.fetch_history(local, remote, require_existing=True)
    assert (local / "index.json").read_bytes() == before
    assert not (tmp_path / "outside.json").exists()
    assert not list(tmp_path.glob(".history-fetch-*"))


def test_fetch_requires_existing_index_only_when_requested(tmp_path, monkeypatch):
    remote = "https://example.test/api/history"
    _mock_remote(monkeypatch, {})
    assert not history.fetch_history(tmp_path / "history", remote)
    with pytest.raises(ValueError, match="Required history index"):
        history.fetch_history(tmp_path / "history", remote, require_existing=True)


def test_update_requires_existing_local_index_but_accepts_explicit_empty_history(tmp_path):
    snapshot = tmp_path / "latest.json"
    _write(snapshot, {"timestamp": "2026-09-30T00:00:00Z", "regions": {}})
    target = tmp_path / "history"
    with pytest.raises(ValueError, match="Required local history index"):
        history.update_history(snapshot, target, require_existing=True)
    assert not target.exists()
    _write(target / "index.json", {"days": []})
    history.update_history(snapshot, target, require_existing=True)
    assert json.loads((target / "index.json").read_bytes())["latest_date"] == "2026-09-30"


def test_strict_update_remote_bootstrap_failure_does_not_modify_local_history(tmp_path, monkeypatch):
    remote = "https://example.test/api/history"
    target = tmp_path / "history"
    _write(target / "index.json", {"days": [], "existing": True})
    before = (target / "index.json").read_bytes()
    _mock_remote(monkeypatch, {})
    with pytest.raises(ValueError, match="Required history index"):
        history.update_history(tmp_path / "latest.json", target, remote, require_existing=True)
    assert (target / "index.json").read_bytes() == before


def test_fetch_resolves_legacy_json_reference_without_inflating_snapshot(tmp_path, monkeypatch):
    remote = "https://example.test/api/history"
    relative = "snapshots/2026-09-29.json"
    snapshot = {"timestamp": "2026-09-29T00:00:00Z", "regions": {}}
    compressed = gzip.compress(json.dumps(snapshot).encode())
    _mock_remote(monkeypatch, {
        remote + "/index.json": json.dumps({
            "latest_snapshot_path": relative, "days": [{"snapshot_path": relative}]
        }).encode(),
        remote + "/recent-changes.json": b"{}",
        remote + "/" + relative + ".gz": compressed,
    })
    target = tmp_path / "history"
    assert history.fetch_history(target, remote, require_existing=True)
    assert not (target / relative).exists()
    assert (target / (relative + ".gz")).read_bytes() == compressed
    restored = history._load_previous_snapshot(target, {"snapshot_path": relative})
    assert restored.timestamp.date().isoformat() == "2026-09-29"
    assert json.loads((target / "index.json").read_bytes())["latest_snapshot_path"] == relative


def test_fetch_archive_metadata_bootstraps_all_dates_atomically(archive_fixture, tmp_path, monkeypatch):
    _, _, _, public, archive = archive_fixture
    config = json.loads((public / "archive-config.json").read_bytes())
    remote = "https://example.test/api/history"
    archive_url = archive_history_url(config)
    payloads = {remote + "/index.json": json.dumps({"archive": config}).encode()}
    payloads.update({
        archive_url + "/" + path.relative_to(archive / "api/history").as_posix(): path.read_bytes()
        for path in (archive / "api/history").rglob("*") if path.is_file()
    })
    calls = _mock_remote(monkeypatch, payloads)
    target = tmp_path / "download"
    assert history.fetch_history(target, remote, require_existing=True)
    assert len(json.loads((target / "index.json").read_bytes())["days"]) == 65
    assert calls[1] == archive_url + "/index.json"
    assert (target / "snapshots/2026-07-28.json.gz").is_file()
    assert len(json.loads((target / "latency-history.json").read_bytes())["days"]) == 80


def test_proxy_backed_complete_index_bootstraps_all_dates(archive_fixture, tmp_path, monkeypatch):
    _, _, _, public, archive = archive_fixture
    assert not (public / "api/history/index.json").exists()
    remote = "https://example.test/api/history"
    payloads = {
        remote + "/" + path.relative_to(archive / "api/history").as_posix(): path.read_bytes()
        for path in (archive / "api/history").rglob("*") if path.is_file()
    }
    calls = _mock_remote(monkeypatch, payloads)
    target = tmp_path / "download"
    assert history.fetch_history(target, remote, require_existing=True)
    assert len(json.loads((target / "index.json").read_bytes())["days"]) == 65
    assert calls[0] == remote + "/index.json"


def test_archive_browser_rejects_arbitrary_routes_and_surfaces_fetch_failure():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for browser control-flow checks")
    script = Path(__file__).parents[1] / "src/azure_region_monitor/assets/archive-browser.js"
    harness = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const code = fs.readFileSync(process.argv[1], "utf8");
async function run(path) {
  const elements = {};
  const calls = [];
  const context = {
    document: {getElementById: id => elements[id] ||= {textContent: "", setAttribute() {}, addEventListener() {}}},
    location: {pathname: path},
    fetch: async url => {calls.push(url); throw new Error("offline");},
    Date, Number,
  };
  vm.runInNewContext(code, context);
  await new Promise(resolve => setImmediate(resolve));
  return {elements, calls};
}
(async () => {
  for (const path of ["/unknown", "/admin.html", "/blog/no-date.html", "/blog/2026-02-30.html", "/api/history/missing.json"]) {
    const {elements, calls} = await run(path);
    assert.equal(calls.length, 0);
    assert.match(elements["archive-status"].textContent, /Page not found/);
  }
  for (const path of ["/archive.html", "/blog/2026-07-28.html", "/feedback/2026-07-28.html", "/reading-check/2026-07-28.html"]) {
    const {elements, calls} = await run(path);
    assert.deepEqual(calls, ["/archive-config.json"]);
    assert.match(elements["archive-status"].textContent, /Archive unavailable: offline/);
    assert.equal(elements["archive-retry"].hidden, false);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run([node, "-e", harness, str(script)], check=True, capture_output=True, text=True)
