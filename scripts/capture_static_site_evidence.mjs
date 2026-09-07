import { mkdir, readdir, readFile, writeFile, appendFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join, relative } from "node:path";
import { chromium } from "playwright";

const evidenceDir = process.env.EVIDENCE_DIR;
if (!evidenceDir) throw new Error("EVIDENCE_DIR is required.");
for (const name of ["BASE_SHA", "HEAD_SHA"]) {
  if (!/^[0-9a-f]{40}$/.test(process.env[name] || "")) throw new Error(`${name} must be an exact commit SHA.`);
}
const origins = [
  ["before", process.env.BEFORE_URL || "http://127.0.0.1:4173"],
  ["after", process.env.AFTER_URL || "http://127.0.0.1:4174"],
];
for (const [, origin] of origins) {
  const url = new URL(origin);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1") {
    throw new Error("Visual capture must use the local fixture servers.");
  }
}
const roots = ["before-site", "after-site"];
const builds = process.env.BUILD_STATUS_FILE ?
  JSON.parse(await readFile(process.env.BUILD_STATUS_FILE, "utf8")) :
  {before: "success", after: "success"};
for (const label of ["before", "after"]) {
  if (!["success", "failure"].includes(builds[label])) throw new Error(`Invalid ${label} build status.`);
}
const comparable = builds.before === "success" && builds.after === "success";
const digest = data => createHash("sha256").update(data).digest("hex");
const escape = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");

async function htmlFiles(root) {
  const files = [];
  for (const entry of await readdir(root, {withFileTypes: true})) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) files.push(...await htmlFiles(path));
    else if (entry.isFile() && entry.name.endsWith(".html")) files.push(path);
  }
  return files;
}

const pathsByRoot = {};
for (const root of roots) {
  pathsByRoot[root] = builds[root.replace("-site", "")] === "failure" ? [] : (await htmlFiles(join(evidenceDir, root)))
    .map(path => relative(join(evidenceDir, root), path).replaceAll("\\", "/")).sort();
}
const pagePaths = [...new Set(Object.values(pathsByRoot).flat())].sort();
if (!pagePaths.length && comparable) throw new Error("No HTML pages were generated.");
const inputPath = process.env.SNAPSHOT_FILE || join(evidenceDir, "before-site", "api", "latest.json");
const snapshotBytes = await readFile(inputPath);
for (const root of roots) {
  if (builds[root.replace("-site", "")] === "failure") continue;
  const bytes = await readFile(join(evidenceDir, root, "api", "latest.json"));
  if (!bytes.equals(snapshotBytes)) throw new Error("The builds did not use identical snapshot bytes.");
}
const snapshot = JSON.parse(snapshotBytes.toString("utf8"));

const screenshotRelative = (label, path) => {
  const safe = path.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return `${label}/${safe}-${digest(path).slice(0, 12)}.png`;
};
const browser = await chromium.launch({headless: true});
try {
  for (const [label, origin] of origins) {
    if (builds[label] === "failure") continue;
    const sourceRoot = `${label}-site`;
    await mkdir(join(evidenceDir, label), {recursive: true});
    const page = await browser.newPage({
      viewport: {width: 1440, height: 1000}, locale: "en-US", timezoneId: "UTC",
      reducedMotion: "reduce",
    });
    for (const path of pagePaths) {
      if (!pathsByRoot[sourceRoot].includes(path)) continue;
      console.log(`Capturing ${label}/${path}`);
      const response = await page.goto(`${origin}/${path.split("/").map(encodeURIComponent).join("/")}`, {
        waitUntil: "networkidle", timeout: 30000,
      });
      if (!response?.ok()) throw new Error(`${label}/${path} returned ${response?.status() ?? "no response"}`);
      await page.evaluate(async () => { await document.fonts.ready; });
      await page.screenshot({
        fullPage: true, animations: "disabled",
        path: join(evidenceDir, screenshotRelative(label, path)),
      });
    }
    await page.close();
  }
} finally {
  await browser.close();
}

const comparison = [];
for (const path of pagePaths) {
  const before = pathsByRoot["before-site"].includes(path) ? screenshotRelative("before", path) : null;
  const after = pathsByRoot["after-site"].includes(path) ? screenshotRelative("after", path) : null;
  const beforeImage = before ? await readFile(join(evidenceDir, before)) : null;
  const afterImage = after ? await readFile(join(evidenceDir, after)) : null;
  comparison.push({
    path, before, after,
    status: builds.before === "failure" ? "before_build_failed" :
      builds.after === "failure" ? "after_build_failed" :
      !before ? "added" : !after ? "removed" : beforeImage.equals(afterImage) ? "unchanged" : "changed",
    before_sha256: beforeImage ? digest(beforeImage) : null,
    after_sha256: afterImage ? digest(afterImage) : null,
  });
}
const manifest = {
  pull_request: process.env.PR_NUMBER || null,
  base_sha: process.env.BASE_SHA, head_sha: process.env.HEAD_SHA,
  builds, comparable,
  input_snapshot: {
    source: "PR head repository fixture (not a live deployment)",
    timestamp: snapshot.timestamp, sha256: digest(snapshotBytes),
  },
  pages: pagePaths, comparison,
  viewport: {width: 1440, height: 1000}, locale: "en-US", timezone: "UTC",
};
await writeFile(join(evidenceDir, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
const panels = comparison.map(item => `<section><h2>${escape(item.path)}: ${item.status}</h2><div class="pair">${
  [["Before", item.before], ["After", item.after]].map(([title, image]) =>
    `<figure><figcaption>${title}</figcaption>${image ? `<a href="${image}"><img src="${image}" alt="${title}: ${escape(item.path)}"></a>` : `<p>${builds[title.toLowerCase()] === "failure" ? "Build failed; no reliable screenshot." : "Page not present."}</p>`}</figure>`
  ).join("")
}</div></section>`).join("\n");
await writeFile(join(evidenceDir, "index.html"), `<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Paired visual evidence</title>
<style>body{font:16px system-ui;margin:24px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0;min-width:0}img{max-width:100%}section{margin:32px 0}code{overflow-wrap:anywhere}</style>
<h1>Paired visual evidence</h1><p>PR ${escape(manifest.pull_request || "local smoke test")}</p>
<p>Builds: before ${builds.before}, after ${builds.after}. ${comparable ? "Both builds are available for comparison." : "INCOMPLETE: inspect the build logs; this is not a successful comparison."}</p>
<p>Base <code>${manifest.base_sha}</code><br>Head <code>${manifest.head_sha}</code></p>
<p>Common repository fixture: ${escape(snapshot.timestamp)}. These are not live-site screenshots.</p>
<p>Snapshot SHA-256: <code>${manifest.input_snapshot.sha256}</code></p>${panels}</html>`);
if (process.env.GITHUB_STEP_SUMMARY) {
  await appendFile(process.env.GITHUB_STEP_SUMMARY,
    `## Visual evidence\n\nBase: \`${manifest.base_sha}\`\n\nHead: \`${manifest.head_sha}\`\n\n` +
    `${pagePaths.length} page paths; before build ${builds.before}, after build ${builds.after}. ` +
    `Comparable: ${comparable}. Input snapshot: ${snapshot.timestamp}.\n\n` +
    "The paired screenshot artifact includes `index.html`, `manifest.json`, and before/after PNGs. " +
    "The fixture is repository data, not live-site evidence; differences require human review.\n");
}
if (!comparable) process.exitCode = 1;
