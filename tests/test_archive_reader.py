from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_archive_api_contracts_and_failure_paths():
    script = r"""
const assert = require("node:assert/strict");
const {respond, archiveUrl} = require("./api/reader");
const generation = "a".repeat(64);
const config = {archive_base_url: "https://example.blob.core.windows.net/archive/publications/123-1", generation};
const req = {method: "GET", url: "https://site/api/history/snapshots/2026-05-10.json.gz",
             params: {path: "snapshots/2026-05-10.json.gz"}};
(async () => {
  let called;
  const response = await respond(req, config, async (url, method) => {
    called = [url.href, method];
    return {status: 200, headers: {}, body: Buffer.from([31, 139, 0, 255])};
  });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, Buffer.from([31, 139, 0, 255]));
  assert.deepEqual(called, [config.archive_base_url + "/api/history/snapshots/2026-05-10.json.gz", "GET"]);
  assert.equal(response.headers["Content-Type"], "application/gzip");
  assert.equal(response.headers["X-Archive-Generation"], generation);
  for (const [status, expected] of [[404,404], [403,502], [500,502], [302,502]]) {
    assert.equal((await respond(req, config, async () => ({status,headers:{},body:Buffer.alloc(0)}))).status, expected);
  }
  assert.equal((await respond(req, config, async () => {throw Error("offline")})).status, 502);
  assert.equal((await respond(req, {})).status, 503);
  const head = await respond({...req,method:"HEAD"}, config, async () => ({status:200,headers:{},body:Buffer.from("x")}));
  assert.equal(head.status, 200); assert.equal(head.body, undefined);
  assert.equal((await respond({...req,method:"POST"},config)).status,405);
  assert.equal((await respond({...req,method:"OPTIONS"},config)).status,204);
  for (const invalid of ["../secrets", "api/history/../private", "api/history/%2e%2e/x",
                          "api/history/a\\b", "api/history//x", "api/history/x?token=secret"]) {
    assert.equal(archiveUrl(config.archive_base_url, invalid), null);
  }
  for (const base of ["http://example.blob.core.windows.net/archive/publications/1",
                      "https://example.com/archive/publications/1",
                      config.archive_base_url + "?sig=secret"]) {
    assert.throws(() => archiveUrl(base, "api/history/index.json"));
  }
  const article = await respond({method:"GET",url:"https://site/api/archive/blog/2026-05-10.html",
      params:{path:"blog/2026-05-10.html"}},config,async (url) => {
    assert.equal(url.href,config.archive_base_url+"/blog/2026-05-10.html");
    return {status:200,headers:{},body:Buffer.from("<h1>Historical evidence</h1>")};
  });
  assert.equal(article.status,200); assert.match(article.headers["Content-Type"],/text\/html/);
  const catalog = await respond({method:"GET",url:"https://site/api/archive/archive/catalog/1.json",
      params:{path:"archive/catalog/1.json"}},config,async (url) => {
    assert.equal(url.href,config.archive_base_url+"/archive/catalog/1.json");
    return {status:200,headers:{},body:Buffer.from('{"entries":[]}')};
  });
  assert.equal(catalog.status,200);
  assert.equal(catalog.headers["X-Archive-Generation"],generation);
  const latest = await respond({method:"GET",url:"https://site/api/latest.json",
      params:{path:"latest.json"}},config,async (url) => {
    assert.equal(url.href,config.archive_base_url+"/api/latest.json");
    return {status:200,headers:{},body:Buffer.from("{}")};
  });
  assert.equal(latest.status,200);
  const gzip = require("node:zlib");
  const original = '{"regions":{"test":{"status":"unknown"}}}';
  const legacy = await respond({...req, url:"https://site/api/history/snapshots/2026-05-10.json",
      params:{path:"snapshots/2026-05-10.json"}}, config, async (url) =>
      url.href.endsWith(".gz") ? {status:200,headers:{},body:gzip.gzipSync(original)} :
        {status:404,headers:{},body:Buffer.alloc(0)});
  assert.equal(legacy.status,200);
  assert.equal(legacy.headers["Content-Encoding"],"gzip");
  assert.match(legacy.headers["Content-Type"],/application\/json/);
  assert.equal(gzip.gunzipSync(legacy.body).toString(),original);
})().catch((error) => {console.error(error); process.exit(1)});
"""
    completed = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_archive_api_is_read_only_and_uses_supported_runtime():
    package = json.loads((ROOT / "api" / "package.json").read_text())
    assert package["engines"]["node"] == "22.x"
    assert "dependencies" not in package
    for name in ("history", "archive", "public-data"):
        function = json.loads((ROOT / "api" / name / "function.json").read_text())
        trigger = function["bindings"][0]
        assert trigger["methods"] == ["get", "head", "options"]
        assert trigger["route"] == ("{*path}" if name == "public-data" else f"{name}/{{*path}}")
