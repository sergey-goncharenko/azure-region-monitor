from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from azure_region_monitor.history import copy_history_to_api
from azure_region_monitor.models import Snapshot
from azure_region_monitor.storage import load_snapshot


_COUNTRY_NAMES = {
  "AE": "United Arab Emirates",
  "AT": "Austria",
  "AU": "Australia",
  "BE": "Belgium",
  "BR": "Brazil",
  "CA": "Canada",
  "CH": "Switzerland",
  "CL": "Chile",
  "CN": "China",
  "DE": "Germany",
  "DK": "Denmark",
  "ES": "Spain",
  "FI": "Finland",
  "FR": "France",
  "GB": "United Kingdom",
  "GR": "Greece",
  "HK": "Hong Kong",
  "ID": "Indonesia",
  "IE": "Ireland",
  "IL": "Israel",
  "IN": "India",
  "IT": "Italy",
  "JP": "Japan",
  "KR": "Korea",
  "MX": "Mexico",
  "MY": "Malaysia",
  "NL": "Netherlands",
  "NO": "Norway",
  "NZ": "New Zealand",
  "PL": "Poland",
  "PT": "Portugal",
  "QA": "Qatar",
  "SE": "Sweden",
  "SG": "Singapore",
  "TW": "Taiwan",
  "US": "United States",
  "ZA": "South Africa",
}

_LARGE_EXTENSION_GROUP_THRESHOLD = 10
_PRIMARY_EXTENSION_GROUPS = {"microsoft"}
_REPOSITORY_URL = "https://github.com/sergey-goncharenko/azure-region-monitor"
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'; "
    "img-src 'self' data:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "upgrade-insecure-requests"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()",
}
_API_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "public, must-revalidate, max-age=60",
}


def build_static_site(
    output_dir: Path,
    snapshot_path: Path = Path("data/snapshots/latest.json"),
    diff_path: Path = Path("data/diffs/latest.json"),
    history_path: Path = Path("data/history"),
) -> None:
    snapshot = load_snapshot(snapshot_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    api_dir = output_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(snapshot_path, api_dir / "latest.json")
    if diff_path.exists():
        shutil.copyfile(diff_path, api_dir / "diff.json")
    copy_history_to_api(history_path, api_dir / "history")

    recent_changes = _load_recent_changes(history_path)
    (output_dir / "index.html").write_text(
        _render_index(snapshot, recent_changes=recent_changes), encoding="utf-8"
    )
    (output_dir / "heatmap.html").write_text(_render_heatmap_page(snapshot), encoding="utf-8")
    (output_dir / "methodology.html").write_text(_render_methodology_page(snapshot), encoding="utf-8")
    _write_static_web_app_config(output_dir)


def _write_static_web_app_config(output_dir: Path) -> None:
    config = {
        "globalHeaders": _SECURITY_HEADERS,
        "routes": [
            {
                "route": "/api/*",
                "headers": _API_HEADERS,
            }
        ],
        "mimeTypes": {
            ".json": "application/json",
        },
    }
    (output_dir / "staticwebapp.config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


def _render_index(snapshot: Snapshot, recent_changes: dict[str, Any] | None = None) -> str:
    rows = _flatten_snapshot(snapshot)
    status_counts = _status_counts(rows)
    status_total = sum(status_counts.values())
    available_percent = (
        round((status_counts.get("available", 0) / status_total) * 100, 1) if status_total else 0
    )
    regions = _sort_regions(snapshot.regions)
    unique_features = sorted({str(row["feature"]) for row in rows})
    modality_rows = "\n".join(_render_modality_row(row) for row in _modality_summaries(rows))
    regional_availability_tables = _render_regional_availability_tables(rows, regions)
    large_extension_group_tables = _render_large_extension_group_tables(rows, regions)
    recent_changes_panel = _render_recent_changes_panel(recent_changes)
    group_rows = "\n".join(_render_group_row(row) for row in _feature_group_summaries(rows))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Azure Regional Feature Availability Monitor</title>
  {_style_block()}
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Azure Regional Feature Availability Monitor</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="methodology.html">Status meanings</a>
        <a href="heatmap.html">Detailed heatmap</a>
        <a href="api/latest.json">api/latest.json</a>
        <a href="{_REPOSITORY_URL}">GitHub repository</a>
      </nav>
    </header>
    <section class="repo-callout" aria-label="Project repository">
      <div>
        <h2>Open Source Monitor</h2>
        <p>Source code, methodology notes, workflows, and release tracking are public in the GitHub repository.</p>
      </div>
      <a href="{_REPOSITORY_URL}">View repository</a>
    </section>
    <section class="metrics" aria-label="Availability summary">
      {_render_metric("Regions", len(regions))}
      {_render_metric("Unique features", len(unique_features))}
      {_render_metric("Checks", len(rows))}
      {_render_metric("Available", f"{available_percent}%")}
    </section>
    <section class="status-strip" aria-label="Status totals">
      {_render_metric("Available", status_counts.get("available", 0))}
      {_render_metric("Unavailable", status_counts.get("unavailable", 0))}
      {_render_metric("Partial", status_counts.get("partial", 0))}
      {_render_metric("Unknown", status_counts.get("unknown", 0))}
    </section>
    {recent_changes_panel}
    <section class="layout" aria-label="Coverage overview">
      <div class="panel">
        <div class="panel-header">
          <h2>Modalities</h2>
          <div class="panel-subtitle">Feature families across all regions</div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Modality</th>
                <th class="number">Features</th>
                <th class="number">Checks</th>
                <th class="number">Available</th>
                <th class="number">Unavailable</th>
                <th class="number">Partial</th>
                <th class="number">Unknown</th>
              </tr>
            </thead>
            <tbody>{modality_rows}</tbody>
          </table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-header">
          <h2>Feature Groups</h2>
          <div class="panel-subtitle">Publisher, version, and SKU-family aggregation</div>
        </div>
        <div class="table-wrap compact-table">
          <table>
            <thead>
              <tr>
                <th>Modality</th>
                <th>Group</th>
                <th class="number">Features</th>
                <th class="number">Available</th>
                <th class="number">Checks</th>
              </tr>
            </thead>
            <tbody>{group_rows}</tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="availability-stack" aria-label="Region modality availability">
      <div class="section-heading">
        <h2>Regional Availability By Modality</h2>
        <div class="panel-subtitle">Each modality has its own group / region matrix</div>
      </div>
    </section>
    {regional_availability_tables}
    {large_extension_group_tables}
  </main>
  <script>
{_index_script()}
  </script>
</body>
</html>
"""


def _render_heatmap_page(snapshot: Snapshot) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Azure Regional Feature Heatmap</title>
  {_style_block()}
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Azure Regional Feature Heatmap</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="index.html">Summary</a>
        <a href="methodology.html">Status meanings</a>
        <a href="api/latest.json">api/latest.json</a>
      </nav>
    </header>
    <section class="panel" aria-label="Heatmap filters">
      <div class="panel-header">
        <h2>Filters</h2>
        <div id="load-status" class="panel-subtitle">Loading snapshot...</div>
      </div>
      <div class="toolbar heatmap-toolbar">
        <input id="search" type="search" placeholder="Search region, group, feature, or message" aria-label="Search checks">
        <select id="modality" aria-label="Filter by modality"><option value="">All modalities</option></select>
        <select id="group" aria-label="Filter by group"><option value="">All groups</option></select>
        <select id="status" aria-label="Filter by status">
          <option value="">All statuses</option>
          <option value="available">Available</option>
          <option value="unavailable">Unavailable</option>
          <option value="partial">Partial</option>
          <option value="unknown">Unknown</option>
        </select>
        <select id="page-size" aria-label="Rows per page">
          <option value="50">50 rows</option>
          <option value="100" selected>100 rows</option>
          <option value="250">250 rows</option>
          <option value="500">500 rows</option>
        </select>
      </div>
    </section>
    <section class="panel matrix" aria-label="Detailed regional heatmap">
      <div class="panel-header">
        <h2>Heatmap</h2>
        <div id="heatmap-count" class="panel-subtitle"></div>
      </div>
      <div class="pager">
        <button id="heatmap-prev" type="button">Previous</button>
        <span id="heatmap-page"></span>
        <button id="heatmap-next" type="button">Next</button>
      </div>
      <div class="table-wrap heatmap-wrap">
        <table id="heatmap-table"></table>
      </div>
    </section>
    <section class="panel" aria-label="Paged check details">
      <div class="panel-header">
        <h2>Check Details</h2>
        <div id="detail-count" class="panel-subtitle"></div>
      </div>
      <div class="pager">
        <button id="details-prev" type="button">Previous</button>
        <span id="details-page"></span>
        <button id="details-next" type="button">Next</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th>Modality</th>
              <th>Group</th>
              <th>Feature</th>
              <th>Status</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody id="details-rows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
{_heatmap_script()}
  </script>
</body>
</html>
"""


def _render_methodology_page(snapshot: Snapshot) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Azure Regional Feature Monitor Status Meanings</title>
  {_style_block()}
</head>
<body>
  <main class="content-page">
    <header>
      <div>
        <h1>Status Meanings</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <nav class="links" aria-label="Dashboard links">
        <a href="index.html">Summary</a>
        <a href="heatmap.html">Detailed heatmap</a>
        <a href="api/latest.json">api/latest.json</a>
      </nav>
    </header>
    <section class="panel prose" aria-label="Plain-language status guide">
      <div class="panel-header">
        <h2>Plain-language guide</h2>
        <div class="panel-subtitle">What the dashboard can and cannot prove</div>
      </div>
      <div class="prose-body">
        <p>This dashboard is a regional rollout monitor. Most checks are read-only catalog checks: they ask Azure which locations, versions, SKUs, or extension types are advertised by Azure control-plane APIs or Azure CLI commands. They are fast and cheap, but they are not the same thing as a full deployment test.</p>
        <h3>Overall statuses</h3>
        <table>
          <thead><tr><th>Status</th><th>Meaning</th><th>What it does not prove</th></tr></thead>
          <tbody>
            <tr><td><span class="status status-available">available</span></td><td>The feature was listed or matched by the read-only probe for that region.</td><td>It does not guarantee that a later deployment will pass quota, capacity, policy, identity, or provider-registration checks.</td></tr>
            <tr><td><span class="status status-unavailable">unavailable</span></td><td>The probe completed successfully, but the feature was absent from the catalog or location list used by that probe.</td><td>It does not necessarily mean the service is impossible forever, globally blocked, or failing because of quota.</td></tr>
            <tr><td><span class="status status-partial">partial</span></td><td>Reserved for checks where some required sub-conditions pass and others fail.</td><td>Current read-only probes rarely emit this because they usually test one listed item at a time.</td></tr>
            <tr><td><span class="status status-unknown">unknown</span></td><td>The probe could not produce reliable evidence, usually because Azure CLI failed, timed out, returned invalid JSON, or the provider endpoint was not available.</td><td>It should not be treated as unavailable. It means the monitor did not get a trustworthy answer.</td></tr>
          </tbody>
        </table>
        <h3>Azure Functions Flex Consumption</h3>
        <p>The <code>hostingPlans.flexConsumption</code> row comes from <code>az functionapp list-flexconsumption-locations --output json</code>. Azure CLI describes this command as listing available locations for running function apps on the Flex Consumption plan.</p>
        <p>If a region is absent from that list, the dashboard marks Flex Consumption as <span class="status status-unavailable">unavailable</span>. In plain language, that means Azure did not advertise that region as a Flex Consumption location to this command at scan time. It is not a quota result.</p>
        <p>The runtime rows, such as <code>runtimes.python.3.14</code> or <code>runtimes.node.24</code>, are tied to the Flex location signal. If Flex is not listed for a region, every Functions runtime row is marked unavailable for that region because there is no Flex hosting target in the read-only evidence. If Flex is listed, runtime availability is checked against <code>az functionapp list-runtimes --os linux --output json</code>.</p>
        <div class="note"><strong>Quota is separate.</strong> A region can be listed as available here and still fail a real deployment because of subscription quota, regional capacity, Azure Policy, provider registration, RBAC, or service-specific constraints. A quota or capacity signal needs a separate probe, probably using usage APIs and eventually a controlled create/delete deployment check.</div>
        <h3>Other modalities</h3>
        <table>
          <thead><tr><th>Modality</th><th>Available means</th><th>Unavailable means</th></tr></thead>
          <tbody>
            <tr><td>AKS extensions</td><td>The extension type was listed by the AKS extension catalog for the region.</td><td>The catalog call succeeded but did not list that extension type in the region.</td></tr>
            <tr><td>AKS Kubernetes versions</td><td><code>az aks get-versions</code> listed a Kubernetes version matching the configured prefix.</td><td>The version listing succeeded, but no matching version prefix was present.</td></tr>
            <tr><td>Azure AI models</td><td><code>az cognitiveservices model list --location &lt;region&gt;</code> listed the model/version in the region.</td><td>The model/version was not present in the regional catalog, or the regional <code>locations/models</code> endpoint reported that the region is outside its supported locations.</td></tr>
            <tr><td>Container Apps</td><td><code>az provider show --namespace Microsoft.App --expand resourceTypes/locations</code> advertised the resource type in the region.</td><td>The provider metadata call succeeded, but the resource type was not advertised in that region.</td></tr>
            <tr><td>VM SKUs</td><td><code>az vm list-sizes</code> listed the SKU in the region.</td><td>The size listing succeeded, but the SKU was not present in that regional size list.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _style_block() -> str:
    return """<style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #607086;
      --line: #dce3ec;
      --line-strong: #c4cfdd;
      --available-bg: #e5f6ee;
      --available-text: #116339;
      --unavailable-bg: #fdecec;
      --unavailable-text: #9d1c20;
      --partial-bg: #fff5d8;
      --partial-text: #76520b;
      --unknown-bg: #edf1f6;
      --unknown-text: #4f5f73;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    main { max-width: 1440px; margin: 0 auto; padding: 28px 18px 42px; }
    header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-end; margin-bottom: 18px; }
    h1 { margin: 0 0 6px; font-size: 28px; line-height: 1.2; font-weight: 650; letter-spacing: 0; }
    a { color: #2759a5; }
    button { min-height: 34px; border: 1px solid var(--line-strong); border-radius: 6px; padding: 5px 10px; color: var(--text); background: #fff; font: inherit; cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: 0.45; }
    .links { display: flex; gap: 14px; flex-wrap: wrap; }
    .timestamp, .panel-subtitle { color: var(--muted); font-size: 14px; }
    .repo-callout { display: flex; justify-content: space-between; align-items: center; gap: 18px; background: #eef4fb; border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin: 0 0 18px; }
    .repo-callout p { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
    .repo-callout a { white-space: nowrap; font-weight: 650; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 10px; margin: 18px 0; }
    .metric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
    .metric-value { font-size: 24px; font-weight: 650; }
    .metric-label { color: var(--muted); font-size: 13px; margin-top: 2px; }
    .status-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; }
    .layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 1fr); gap: 14px; align-items: start; margin-bottom: 14px; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
    .panel-header { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; padding: 14px 14px 0; }
    .section-heading { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin: 18px 0 10px; }
    h2 { margin: 0; font-size: 16px; line-height: 1.3; font-weight: 650; letter-spacing: 0; }
    .table-wrap { overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
    .panel .table-wrap { border: 0; border-radius: 0; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; font-weight: 650; text-transform: uppercase; }
    tr:last-child td { border-bottom: 0; }
    code { color: var(--text); }
    .number { text-align: right; font-variant-numeric: tabular-nums; }
    .compact-table { max-height: 460px; }
    .toolbar { display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 10px; padding: 14px; border-top: 1px solid var(--line); }
    input, select { width: 100%; min-height: 36px; border: 1px solid var(--line-strong); border-radius: 6px; padding: 6px 10px; font: inherit; color: var(--text); background: #fff; }
    .pager { display: flex; gap: 10px; align-items: center; padding: 10px 14px; color: var(--muted); font-size: 13px; }
    .heatmap-wrap { max-height: 640px; }
    .matrix table { min-width: 980px; }
    .matrix th, .matrix td { text-align: center; }
    .matrix th:first-child, .matrix td:first-child, .matrix th:nth-child(2), .matrix td:nth-child(2) { text-align: left; }
    .matrix th { position: sticky; top: 0; z-index: 2; background: var(--panel); }
    .matrix th:first-child, .matrix td:first-child { position: sticky; left: 0; z-index: 1; background: var(--panel); min-width: 110px; }
    .matrix th:nth-child(2), .matrix td:nth-child(2) { position: sticky; left: 110px; z-index: 1; background: var(--panel); min-width: 260px; max-width: 360px; }
    .matrix th:first-child, .matrix th:nth-child(2) { z-index: 3; }
    .status { display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border-radius: 999px; font-size: 13px; font-weight: 650; }
    .status-available { background: var(--available-bg); color: var(--available-text); }
    .status-unavailable { background: var(--unavailable-bg); color: var(--unavailable-text); }
    .status-partial { background: var(--partial-bg); color: var(--partial-text); }
    .status-unknown { background: var(--unknown-bg); color: var(--unknown-text); }
    .change-highlights { max-width: 460px; color: var(--muted); font-size: 12px; line-height: 1.45; }
    .change-highlight { display: inline; }
    .change-highlight + .change-highlight::before { content: "; "; }
    .status-dot { display: inline-flex; width: 22px; height: 22px; border-radius: 50%; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; line-height: 1; }
    .availability-section .panel-header { padding-bottom: 10px; }
    .matrix-scroll-top { overflow-x: auto; overflow-y: hidden; height: 16px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: #f9fbfd; }
    .matrix-scroll-top > div { height: 1px; }
    .availability-matrix table { min-width: max-content; }
    .availability-matrix th, .availability-matrix td { text-align: center; }
    .availability-matrix th:first-child, .availability-matrix td:first-child { text-align: left; }
    .availability-matrix th { position: sticky; top: 0; z-index: 2; background: var(--panel); }
    .availability-matrix th:first-child, .availability-matrix td:first-child { position: sticky; left: 0; z-index: 1; min-width: 120px; background: var(--panel); }
    .availability-matrix th:first-child { z-index: 3; }
    .extension-feature-matrix th:first-child, .extension-feature-matrix td:first-child { min-width: 260px; max-width: 360px; }
    .extension-feature-matrix td:first-child code { white-space: normal; word-break: break-word; }
    .extension-group-summary { cursor: pointer; list-style: none; padding-bottom: 10px; }
    .extension-group-summary::-webkit-details-marker { display: none; }
    .extension-group-summary h2::before { content: ">"; display: inline-block; width: 16px; color: var(--muted); }
    details[open] > .extension-group-summary h2::before { content: "v"; }
    .lazy-matrix-placeholder { padding: 16px 14px; color: var(--muted); border-top: 1px solid var(--line); }
    .region-header { min-width: 52px; width: 52px; padding-left: 6px; padding-right: 6px; }
    .region-heading { display: inline-grid; justify-items: center; gap: 2px; line-height: 1.05; text-transform: none; }
    .region-flag { width: 18px; height: 18px; object-fit: cover; border-radius: 50%; box-shadow: 0 0 0 1px rgba(23, 32, 51, 0.12); }
    .region-flag-fallback { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: var(--unknown-bg); color: var(--unknown-text); font-size: 10px; font-weight: 700; }
    .region-label { max-width: 48px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; color: var(--muted); }
    .availability-badge { display: inline-flex; gap: 5px; align-items: center; justify-content: center; min-height: 24px; padding: 3px 7px; border-radius: 999px; border: 1px solid transparent; font-size: 12px; font-weight: 650; white-space: nowrap; }
    .availability-label { max-width: 96px; overflow: hidden; text-overflow: ellipsis; }
    .availability-count { font-variant-numeric: tabular-nums; opacity: 0.82; }
    .availability-good { background: #e5f6ee; border-color: #b6e4ca; color: #116339; }
    .availability-warn { background: #fff7ce; border-color: #ecd56b; color: #6e5500; }
    .availability-caution { background: #ffefd8; border-color: #f2bd72; color: #8a4a05; }
    .availability-poor { background: #fdecec; border-color: #efb8ba; color: #9d1c20; }
    .availability-empty { background: #edf1f6; border-color: #d0d8e3; color: #4f5f73; }
    .empty { color: var(--muted); text-align: center; padding: 24px; }
    .content-page { max-width: 980px; }
    .prose .panel-header { padding-bottom: 10px; }
    .prose-body { padding: 0 14px 16px; }
    .prose-body p { color: var(--text); line-height: 1.55; max-width: 860px; }
    .prose-body h3 { margin: 22px 0 8px; font-size: 15px; line-height: 1.3; }
    .prose-body table { min-width: 0; margin: 10px 0 16px; }
    .prose-body th, .prose-body td { text-align: left; }
    .note { margin: 14px 0; padding: 12px 14px; border: 1px solid #b9d6f2; border-radius: 8px; background: #edf6ff; color: #17365d; line-height: 1.5; }
    @media (max-width: 720px) {
      main { padding: 20px 12px 32px; }
      header { display: block; }
      h1 { font-size: 22px; }
      .repo-callout { align-items: flex-start; flex-direction: column; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .layout { grid-template-columns: 1fr; }
      .toolbar { grid-template-columns: 1fr; }
    }
  </style>"""


def _flatten_snapshot(snapshot: Snapshot) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for region, services in sorted(snapshot.regions.items()):
        for service, features in sorted(services.items()):
            for feature, result in sorted(features.items()):
                rows.append(
                    {
                        "region": region,
                        "service": service,
                        "category": _feature_category(feature),
                        "group": _feature_group(feature),
                        "feature": feature,
                        "status": result.status,
                        "latency_ms": result.latency_ms,
                        "message": result.message or result.error_code or "",
                    }
                )
    return rows


def _status_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def _render_metric(label: str, value: int | str) -> str:
    return f"""<div class="metric">
          <div class="metric-value">{html.escape(str(value))}</div>
        <div class="metric-label">{html.escape(label)}</div>
      </div>"""


def _load_recent_changes(history_path: Path) -> dict[str, Any] | None:
    recent_path = history_path / "recent-changes.json"
    if not recent_path.exists():
        return None
    try:
        return json.loads(recent_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _render_recent_changes_panel(recent_changes: dict[str, Any] | None) -> str:
    if not recent_changes:
        return ""

    days = [day for day in recent_changes.get("days", []) if isinstance(day, dict)]
    if not days:
        return ""

    rows = "\n".join(_render_recent_change_row(day) for day in days[:10])
    return f"""<section class="panel" aria-label="Recent availability changes">
      <div class="panel-header">
        <h2>Recent Changes</h2>
        <div class="panel-subtitle">Today plus previous change days</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th class="number">Changes</th>
              <th class="number">New</th>
              <th class="number">Regressions</th>
              <th class="number">Status</th>
              <th>Highlights</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>"""


def _render_recent_change_row(day: dict[str, Any]) -> str:
    counts = day.get("change_type_counts") if isinstance(day.get("change_type_counts"), dict) else {}
    date = str(day.get("date", ""))
    change_path = str(day.get("change_path", ""))
    total_changes = int(day.get("total_changes", 0))
    new_availability = int(counts.get("new_availability", 0))
    regressions = int(counts.get("regression", 0))
    status_changes = int(counts.get("status_change", 0))
    date_cell = html.escape(date)
    if change_path:
        date_cell = f'<a href="api/history/{html.escape(change_path)}">{date_cell}</a>'
    return f"""<tr>
                <td>{date_cell}</td>
                <td class="number">{total_changes:,}</td>
                <td class="number">{new_availability:,}</td>
                <td class="number">{regressions:,}</td>
                <td class="number">{status_changes:,}</td>
                <td>{_render_change_highlights(day.get("highlights", []))}</td>
              </tr>"""


def _render_change_highlights(highlights: object) -> str:
    if not isinstance(highlights, list) or not highlights:
        return '<span class="change-highlights">No changes detected.</span>'

    rendered = []
    for item in highlights[:3]:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region", ""))
        group = str(item.get("group", ""))
        feature = str(item.get("feature", ""))
        current = str(item.get("current", ""))
        previous = str(item.get("previous", ""))
        label = _compact_feature_label(feature, group)
        rendered.append(
            '<span class="change-highlight">'
            f"{html.escape(region)} {html.escape(label)} "
            f"{html.escape(previous)} -> {html.escape(current)}"
            "</span>"
        )
    if not rendered:
        return '<span class="change-highlights">No changes detected.</span>'
    rendered_highlights = "".join(rendered)
    return f'<div class="change-highlights">{rendered_highlights}</div>'


def _compact_feature_label(feature: str, group: str) -> str:
    if feature.startswith("extensionTypes."):
        label = feature.removeprefix("extensionTypes.")
        group_prefix = f"{group}."
        return label.removeprefix(group_prefix) if label.startswith(group_prefix) else label
    if feature.startswith("kubernetesVersions."):
        return feature.removeprefix("kubernetesVersions.")
    if feature.startswith("hostingPlans."):
        return feature.removeprefix("hostingPlans.")
    if feature.startswith("runtimes."):
        return feature.removeprefix("runtimes.")
    if feature.startswith("aiModels."):
      return feature.removeprefix("aiModels.")
    if feature.startswith("vmSkus."):
        return feature.removeprefix("vmSkus.")
    return feature


def _feature_category(feature: str) -> str:
    if feature == "extensionCatalog":
        return "AKS extensions"
    if _is_extension_feature(feature):
        return "AKS extensions"
    if feature.startswith("kubernetesVersions."):
        return "AKS Kubernetes versions"
    if feature.startswith("hostingPlans.") or feature.startswith("runtimes."):
      return "Azure Functions"
    if feature.startswith("aiModels."):
      return "Azure AI models"
    if feature.startswith("containerApps."):
        return "Container Apps"
    if feature.startswith("vmSkus."):
        return "VM SKUs"
    return feature.split(".", 1)[0]


def _feature_group(feature: str) -> str:
    if feature.startswith("extensionTypes."):
        parts = feature.removeprefix("extensionTypes.").split(".")
        return parts[0] if parts else "unknown"
    if feature.startswith("extensions."):
        return "curated"
    if feature.startswith("kubernetesVersions."):
        return feature.removeprefix("kubernetesVersions.")
    if feature.startswith("hostingPlans."):
        return "hosting plans"
    if feature.startswith("runtimes."):
        parts = feature.removeprefix("runtimes.").split(".")
        return parts[0] if parts else "runtime"
    if feature.startswith("aiModels."):
      parts = feature.removeprefix("aiModels.").split(".")
      return parts[0] if parts else "unknown"
    if feature.startswith("containerApps."):
      if feature.endswith("daprComponents"):
        return "dapr"
      if feature.endswith("connectedEnvironments"):
        return "connected environments"
      return "core"
    if feature.startswith("vmSkus."):
        return _vm_sku_family(feature)
    return feature.split(".", 1)[0]


def _vm_sku_family(feature: str) -> str:
    sku = feature.removeprefix("vmSkus.").removeprefix("standard.")
    match = re.match(r"([a-z]+)", sku)
    return match.group(1).upper() if match else "Other"


def _modality_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        category = str(row["category"])
        summary = summaries.setdefault(
            category,
            {"category": category, "features": set(), "checks": 0, "statuses": {}},
        )
        summary["features"].add(str(row["feature"]))
        summary["checks"] = int(summary["checks"]) + 1
        statuses = summary["statuses"]
        status = str(row["status"])
        statuses[status] = statuses.get(status, 0) + 1
    return sorted(summaries.values(), key=lambda item: str(item["category"]))


def _render_modality_row(row: dict[str, object]) -> str:
    statuses = row["statuses"]
    return f"""<tr>
                <td>{html.escape(str(row["category"]))}</td>
                <td class="number">{len(row["features"])}</td>
                <td class="number">{row["checks"]}</td>
                <td class="number">{statuses.get("available", 0)}</td>
                <td class="number">{statuses.get("unavailable", 0)}</td>
                <td class="number">{statuses.get("partial", 0)}</td>
                <td class="number">{statuses.get("unknown", 0)}</td>
              </tr>"""


def _region_modality_group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        region = str(row["region"])
        category = str(row["category"])
        group = str(row["group"])
        summary = summaries.setdefault(
            (category, group), {"category": category, "group": group, "regions": {}}
        )
        region_summary = summary["regions"].setdefault(region, {"available": 0, "total": 0})
        region_summary["total"] += 1
        if row["status"] == "available":
            region_summary["available"] += 1
    return sorted(
        summaries.values(),
        key=lambda item: (str(item["category"]), str(item["group"])),
    )


def _render_regional_availability_tables(rows: list[dict[str, object]], regions: list[str]) -> str:
    summaries = _region_modality_group_summaries(rows)
    summaries_by_modality: dict[str, list[dict[str, object]]] = {}
    for summary in summaries:
        summaries_by_modality.setdefault(str(summary["category"]), []).append(summary)

    return "\n".join(
        _render_modality_availability_table(modality, summaries_by_modality[modality], regions)
        for modality in _sorted_modalities(summaries_by_modality)
    )


def _sorted_modalities(summaries_by_modality: dict[str, list[dict[str, object]]]) -> list[str]:
    preferred_order = [
        "AKS extensions",
        "AKS Kubernetes versions",
        "Azure Functions",
        "Azure AI models",
        "Container Apps",
        "VM SKUs",
    ]
    ordered = [modality for modality in preferred_order if modality in summaries_by_modality]
    ordered.extend(sorted(set(summaries_by_modality) - set(preferred_order)))
    return ordered


def _render_modality_availability_table(
    modality: str, summaries: list[dict[str, object]], regions: list[str]
) -> str:
    region_headers = "\n".join(_render_region_header(region) for region in regions)
    group_rows = "\n".join(_render_region_group_row(row, regions) for row in summaries)
    return f"""<section class="panel availability-section" aria-label="{html.escape(modality)} regional availability">
          <div class="panel-header">
            <h2>{html.escape(modality)}</h2>
            <div class="panel-subtitle">Groups by country, then Azure region</div>
          </div>
          <div class="matrix-scroll-top" aria-hidden="true"><div></div></div>
          <div class="table-wrap availability-matrix">
            <table>
              <thead>
                <tr>
                  <th>Group</th>
                  {region_headers}
                </tr>
              </thead>
              <tbody>{group_rows}</tbody>
            </table>
          </div>
        </section>"""


def _render_region_header(region: str) -> str:
    country_code = _region_country_code(region)
    country_name = _region_country_name(region)
    flag = _region_flag(country_code)
    label = _region_short_label(region)
    title = f"{country_name} - {region}"
    return f"""<th class="region-header" title="{html.escape(title)}">
                    <span class="region-heading">{flag}<span class="region-label">{html.escape(label)}</span></span>
            </th>"""


def _render_region_group_row(row: dict[str, object], regions: list[str]) -> str:
    region_cells = "\n".join(
        _render_availability_cell(row["regions"].get(region), region) for region in regions
    )
    return f"""<tr>
                <td><code>{html.escape(str(row["group"]))}</code></td>
                {region_cells}
              </tr>"""


def _render_large_extension_group_tables(rows: list[dict[str, object]], regions: list[str]) -> str:
    summaries = _large_extension_group_summaries(rows)
    if not summaries:
        return ""

    tables = "\n".join(_render_large_extension_group_table(summary, regions) for summary in summaries)
    return f"""<section class="availability-stack" aria-label="Large AKS extension group availability">
      <div class="section-heading">
        <h2>Large AKS Extension Groups</h2>
        <div class="panel-subtitle">Extension groups with more than {_LARGE_EXTENSION_GROUP_THRESHOLD} extensions</div>
      </div>
    </section>
    {tables}"""


def _large_extension_group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        feature = str(row["feature"])
        if str(row["category"]) != "AKS extensions" or not feature.startswith("extensionTypes."):
            continue

        group = str(row["group"])
        summary = summaries.setdefault(group, {"group": group, "features": {}})
        feature_summary = summary["features"].setdefault(
            feature,
            {
                "feature": feature,
                "label": _extension_feature_label(feature, group),
                "regions": {},
            },
        )
        feature_summary["regions"][str(row["region"])] = str(row["status"])

    large_summaries = [
        summary
        for summary in summaries.values()
        if len(summary["features"]) > _LARGE_EXTENSION_GROUP_THRESHOLD
    ]
    return sorted(
        large_summaries,
        key=lambda item: (
            not _is_primary_extension_group(str(item["group"])),
            str(item["group"]),
            len(item["features"]),
        ),
    )


def _render_large_extension_group_table(summary: dict[str, object], regions: list[str]) -> str:
    group = str(summary["group"])
    features = sorted(
        summary["features"].values(),
        key=lambda item: str(item["label"]),
    )
    table = _render_extension_feature_table(features, regions)
    heading = f"AKS extensions: {html.escape(group)}"
    subtitle = f"{len(features):,} extensions by country, then Azure region"
    if not _is_primary_extension_group(group):
        return f"""<details class="panel availability-section extension-group-section extension-group-collapsed" aria-label="AKS extension group {html.escape(group)} regional availability">
          <summary class="panel-header extension-group-summary">
            <h2>{heading}</h2>
            <div class="panel-subtitle">{subtitle}</div>
          </summary>
          <div class="lazy-matrix-placeholder">Open to load this extension matrix.</div>
          <template>{table}</template>
        </details>"""

    return f"""<section class="panel availability-section extension-group-section" aria-label="AKS extension group {html.escape(group)} regional availability">
          <div class="panel-header">
            <h2>{heading}</h2>
            <div class="panel-subtitle">{subtitle}</div>
          </div>
          {table}
        </section>"""


def _render_extension_feature_table(features: list[dict[str, object]], regions: list[str]) -> str:
    region_headers = "\n".join(_render_region_header(region) for region in regions)
    feature_rows = "\n".join(_render_extension_feature_row(feature, regions) for feature in features)
    return f"""<div class="matrix-scroll-top" aria-hidden="true"><div></div></div>
          <div class="table-wrap availability-matrix extension-feature-matrix">
            <table>
              <thead>
                <tr>
                  <th>Extension</th>
                  {region_headers}
                </tr>
              </thead>
              <tbody>{feature_rows}</tbody>
            </table>
          </div>"""


def _is_primary_extension_group(group: str) -> bool:
    return group in _PRIMARY_EXTENSION_GROUPS


def _render_extension_feature_row(feature: dict[str, object], regions: list[str]) -> str:
    region_cells = "\n".join(
        _render_status_cell(feature["regions"].get(region), region) for region in regions
    )
    return f"""<tr>
                <td><code>{html.escape(str(feature["label"]))}</code></td>
                {region_cells}
              </tr>"""


def _render_status_cell(status: str | None, region: str) -> str:
    label_by_status = {"available": "A", "unavailable": "U", "partial": "P", "unknown": "?"}
    if status is None:
        return '<td><span class="status-dot status-unknown" title="not reported">-</span></td>'

    css_status = status if status in label_by_status else "unknown"
    title = f"{region}: {status}"
    return (
        f'<td><span class="status-dot status-{html.escape(css_status)}" title="{html.escape(title)}">'
        f'{html.escape(label_by_status.get(status, "?"))}</span></td>'
    )


def _extension_feature_label(feature: str, group: str) -> str:
    label = feature.removeprefix("extensionTypes.")
    group_prefix = f"{group}."
    if label.startswith(group_prefix):
        return label.removeprefix(group_prefix)
    return label


def _region_flag(country_code: str) -> str:
    label = (
        "Unknown country" if country_code == "UN" else _COUNTRY_NAMES.get(country_code, country_code)
    )
    display = "?" if country_code == "UN" else country_code
    return (
        f'<span class="region-flag-fallback" title="{html.escape(label)}" '
        f'aria-label="{html.escape(label)}">{html.escape(display)}</span>'
    )


def _sort_regions(regions: dict[str, object]) -> list[str]:
  return sorted(
    regions,
    key=lambda region: (_region_country_name(region), _region_short_label(region), region),
  )


def _region_country_name(region: str) -> str:
    return _COUNTRY_NAMES.get(_region_country_code(region), "Unknown")


def _region_country_code(region: str) -> str:
    normalized = region.lower().replace(" ", "")
    us_regions = {
        "centralus",
        "centraluseuap",
        "eastus",
        "eastus2",
        "eastus2euap",
        "northcentralus",
        "southcentralus",
        "westcentralus",
        "westus",
        "westus2",
        "westus3",
    }
    if normalized in us_regions:
        return "US"
    if normalized.startswith("canada"):
        return "CA"
    if normalized.startswith("brazil"):
        return "BR"
    if normalized.startswith("mexico"):
        return "MX"
    if normalized.startswith("chile"):
        return "CL"
    if normalized.startswith("denmark"):
      return "DK"
    if normalized.startswith("finland"):
      return "FI"
    if normalized.startswith("greece"):
      return "GR"
    if normalized.startswith("portugal"):
      return "PT"
    if normalized.startswith("uk"):
        return "GB"
    if normalized.startswith("france"):
        return "FR"
    if normalized.startswith("germany"):
        return "DE"
    if normalized.startswith("italy"):
        return "IT"
    if normalized.startswith("spain"):
        return "ES"
    if normalized.startswith("poland"):
        return "PL"
    if normalized.startswith("sweden"):
        return "SE"
    if normalized.startswith("norway"):
        return "NO"
    if normalized.startswith("switzerland"):
        return "CH"
    if normalized.startswith("austria"):
        return "AT"
    if normalized.startswith("belgium"):
        return "BE"
    if normalized in {"northeurope", "westeurope"}:
        return "IE" if normalized == "northeurope" else "NL"
    if normalized.startswith("australia"):
        return "AU"
    if normalized.startswith("newzealand"):
        return "NZ"
    if normalized.startswith("japan"):
        return "JP"
    if normalized.startswith("korea"):
        return "KR"
    if normalized.startswith("india") or normalized in {"centralindia", "southindia", "westindia"}:
        return "IN"
    if normalized.startswith("china"):
        return "CN"
    if normalized.startswith("taiwan"):
        return "TW"
    if normalized.startswith("malaysia"):
        return "MY"
    if normalized.startswith("indonesia"):
        return "ID"
    if normalized.startswith("israel"):
        return "IL"
    if normalized.startswith("qatar"):
        return "QA"
    if normalized.startswith("uae"):
        return "AE"
    if normalized.startswith("southafrica"):
        return "ZA"
    if normalized == "eastasia":
        return "HK"
    if normalized == "southeastasia":
        return "SG"
    return "UN"


def _region_short_label(region: str) -> str:
    normalized = region.lower().replace(" ", "")
    replacements = {
      "eastus": "east",
      "eastus2": "east2",
      "centralus": "central",
      "northcentralus": "n central",
      "southcentralus": "s central",
      "westcentralus": "w central",
      "westus": "west",
      "westus2": "west2",
      "westus3": "west3",
      "canadacentral": "central",
      "canadaeast": "east",
      "brazilsouth": "south",
      "brazilsoutheast": "se",
      "mexicocentral": "central",
      "chilecentral": "central",
      "denmarkeast": "east",
      "finlandcentral": "central",
      "greececentral": "central",
      "portugalcentral": "central",
      "uksouth": "south",
      "ukwest": "west",
      "francecentral": "central",
      "francesouth": "south",
      "germanywestcentral": "w central",
      "germanynorth": "north",
      "italynorth": "north",
      "spaincentral": "central",
      "polandcentral": "central",
      "swedencentral": "central",
      "norwayeast": "east",
      "norwaywest": "west",
      "switzerlandnorth": "north",
      "switzerlandwest": "west",
      "austriaeast": "east",
      "belgiumcentral": "central",
      "northeurope": "north",
      "westeurope": "west",
      "australiaeast": "east",
      "australiasoutheast": "se",
      "australiacentral": "central",
      "australiacentral2": "central2",
      "newzealandnorth": "north",
      "japaneast": "east",
      "japanwest": "west",
      "koreacentral": "central",
      "koreasouth": "south",
      "centralindia": "central",
      "southindia": "south",
      "westindia": "west",
      "chinanorth3": "north3",
      "chinaeast3": "east3",
      "taiwannorth": "north",
      "taiwannorthwest": "nw",
      "malaysiawest": "west",
      "indonesiacentral": "central",
      "eastasia": "east",
      "southeastasia": "se",
      "israelcentral": "central",
      "qatarcentral": "central",
      "uaecentral": "central",
      "uaenorth": "north",
      "southafricanorth": "north",
      "southafricawest": "west",
    }
    return replacements.get(normalized, normalized)


def _index_script() -> str:
    return r"""
    function syncAvailabilityScrollbars() {
      document.querySelectorAll('.availability-section').forEach((section) => {
        const top = section.querySelector('.matrix-scroll-top');
        const body = section.querySelector('.availability-matrix');
        const spacer = top ? top.firstElementChild : null;
        if (!top || !body || !spacer) return;
        spacer.style.width = `${body.scrollWidth}px`;
        if (section.dataset.scrollSynced === 'true') return;
        section.dataset.scrollSynced = 'true';
        let syncing = false;
        const sync = (source, target) => {
          if (syncing) return;
          syncing = true;
          target.scrollLeft = source.scrollLeft;
          syncing = false;
        };
        top.addEventListener('scroll', () => sync(top, body));
        body.addEventListener('scroll', () => sync(body, top));
      });
    }
    function initializeLazyExtensionGroups() {
      document.querySelectorAll('.extension-group-collapsed').forEach((section) => {
        section.addEventListener('toggle', () => {
          if (!section.open || section.dataset.loaded === 'true') return;
          const template = section.querySelector('template');
          const placeholder = section.querySelector('.lazy-matrix-placeholder');
          if (!template || !placeholder) return;
          placeholder.replaceWith(template.content.cloneNode(true));
          section.dataset.loaded = 'true';
          template.remove();
          syncAvailabilityScrollbars();
        });
      });
    }
    window.addEventListener('load', syncAvailabilityScrollbars);
    window.addEventListener('load', initializeLazyExtensionGroups);
    window.addEventListener('resize', syncAvailabilityScrollbars);
"""


def _render_availability_cell(summary: dict[str, int] | None, region: str) -> str:
    if summary is None:
        badge = '<span class="availability-badge availability-empty">-</span>'
    else:
        available = summary["available"]
        total = summary["total"]
        missing = total - available
        health_class = _availability_health_class(available, total)
        title = f"{region}: {available:,} available, {missing:,} not available, {total:,} total"
        badge = (
            f'<span class="availability-badge {health_class}" title="{html.escape(title)}">'
            f'<span class="availability-count">{available:,}/{total:,}</span>'
            "</span>"
        )
    return f"<td>{badge}</td>"


def _availability_health_class(available: int, total: int) -> str:
    if total == 0:
        return "availability-empty"
    missing = total - available
    if missing == 0:
        return "availability-good"
    if missing == 1:
        return "availability-warn"
    if missing == 2:
        return "availability-caution"
    return "availability-poor"


def _feature_group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row["category"]), str(row["group"]))
        summary = summaries.setdefault(
            key,
            {"category": key[0], "group": key[1], "features": set(), "checks": 0, "available": 0},
        )
        summary["features"].add(str(row["feature"]))
        summary["checks"] = int(summary["checks"]) + 1
        if row["status"] == "available":
            summary["available"] = int(summary["available"]) + 1
    return sorted(
        summaries.values(),
        key=lambda item: (str(item["category"]), -int(item["checks"]), str(item["group"])),
    )


def _render_group_row(row: dict[str, object]) -> str:
    return f"""<tr>
                <td>{html.escape(str(row["category"]))}</td>
                <td><code>{html.escape(str(row["group"]))}</code></td>
                <td class="number">{len(row["features"]):,}</td>
                <td class="number">{int(row["available"]):,}</td>
                <td class="number">{int(row["checks"]):,}</td>
              </tr>"""


def _is_extension_feature(feature: str) -> bool:
    return feature.startswith("extensions.") or feature.startswith("extensionTypes.")


def _heatmap_script() -> str:
    return r"""
    const state = {
      rows: [],
      regions: [],
      filteredRows: [],
      heatmapRows: [],
      detailsPage: 1,
      heatmapPage: 1,
    };
    const statusLabels = { available: 'A', unavailable: 'U', partial: 'P', unknown: '?', '': '-' };
    const statusOrder = { unknown: 0, partial: 1, unavailable: 2, available: 3 };
    const elements = {
      loadStatus: document.getElementById('load-status'),
      search: document.getElementById('search'),
      modality: document.getElementById('modality'),
      group: document.getElementById('group'),
      status: document.getElementById('status'),
      pageSize: document.getElementById('page-size'),
      detailsRows: document.getElementById('details-rows'),
      detailsCount: document.getElementById('detail-count'),
      detailsPage: document.getElementById('details-page'),
      detailsPrev: document.getElementById('details-prev'),
      detailsNext: document.getElementById('details-next'),
      heatmapTable: document.getElementById('heatmap-table'),
      heatmapCount: document.getElementById('heatmap-count'),
      heatmapPage: document.getElementById('heatmap-page'),
      heatmapPrev: document.getElementById('heatmap-prev'),
      heatmapNext: document.getElementById('heatmap-next'),
    };

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
      }[char]));
    }
    function category(feature) {
      if (feature === 'extensionCatalog') return 'AKS extensions';
      if (feature.startsWith('extensions.') || feature.startsWith('extensionTypes.')) return 'AKS extensions';
      if (feature.startsWith('kubernetesVersions.')) return 'AKS Kubernetes versions';
      if (feature.startsWith('hostingPlans.') || feature.startsWith('runtimes.')) return 'Azure Functions';
      if (feature.startsWith('aiModels.')) return 'Azure AI models';
      if (feature.startsWith('containerApps.')) return 'Container Apps';
      if (feature.startsWith('vmSkus.')) return 'VM SKUs';
      return feature.split('.')[0];
    }
    function group(feature) {
      if (feature.startsWith('extensionTypes.')) return feature.replace('extensionTypes.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('extensions.')) return 'curated';
      if (feature.startsWith('kubernetesVersions.')) return feature.replace('kubernetesVersions.', '');
      if (feature.startsWith('hostingPlans.')) return 'hosting plans';
      if (feature.startsWith('runtimes.')) return feature.replace('runtimes.', '').split('.')[0] || 'runtime';
      if (feature.startsWith('aiModels.')) return feature.replace('aiModels.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('containerApps.')) {
        if (feature.endsWith('daprComponents')) return 'dapr';
        if (feature.endsWith('connectedEnvironments')) return 'connected environments';
        return 'core';
      }
      if (feature.startsWith('vmSkus.')) {
        const sku = feature.replace('vmSkus.', '').replace('standard.', '');
        const match = sku.match(/^([a-z]+)/i);
        return match ? match[1].toUpperCase() : 'Other';
      }
      return feature.split('.')[0];
    }
    function flatten(snapshot) {
      const rows = [];
      for (const [region, services] of Object.entries(snapshot.regions || {})) {
        for (const [service, features] of Object.entries(services || {})) {
          for (const [feature, result] of Object.entries(features || {})) {
            const row = {
              region, service, feature,
              category: category(feature),
              group: group(feature),
              status: result.status || 'unknown',
              message: result.message || result.error_code || '',
            };
            row.searchText = `${row.region} ${row.service} ${row.category} ${row.group} ${row.feature} ${row.status} ${row.message}`.toLowerCase();
            rows.push(row);
          }
        }
      }
      return rows.sort((a, b) => a.region.localeCompare(b.region) || a.category.localeCompare(b.category) || a.feature.localeCompare(b.feature));
    }
    function populateSelect(select, values) {
      const label = select.options[0].textContent;
      const current = select.value;
      select.innerHTML = `<option value="">${escapeHtml(label)}</option>`;
      values.forEach((value) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
      if (values.includes(current)) select.value = current;
    }
    function applyFilters() {
      const query = elements.search.value.trim().toLowerCase();
      const modality = elements.modality.value;
      const selectedGroup = elements.group.value;
      const status = elements.status.value;
      state.filteredRows = state.rows.filter((row) => (
        (!query || row.searchText.includes(query)) &&
        (!modality || row.category === modality) &&
        (!selectedGroup || row.group === selectedGroup) &&
        (!status || row.status === status)
      )).sort((a, b) => (statusOrder[a.status] ?? 4) - (statusOrder[b.status] ?? 4) || a.region.localeCompare(b.region) || a.feature.localeCompare(b.feature));
      state.heatmapRows = buildHeatmapRows(state.filteredRows);
      state.detailsPage = 1;
      state.heatmapPage = 1;
      renderDetails();
      renderHeatmap();
    }
    function buildHeatmapRows(rows) {
      const byFeature = new Map();
      rows.forEach((row) => {
        const key = `${row.category}|${row.group}|${row.feature}`;
        if (!byFeature.has(key)) byFeature.set(key, { category: row.category, group: row.group, feature: row.feature, regions: {} });
        byFeature.get(key).regions[row.region] = row.status;
      });
      return Array.from(byFeature.values()).sort((a, b) => a.category.localeCompare(b.category) || a.group.localeCompare(b.group) || a.feature.localeCompare(b.feature));
    }
    function pageBounds(total, page) {
      const size = Number(elements.pageSize.value);
      const pages = Math.max(1, Math.ceil(total / size));
      const safePage = Math.min(Math.max(1, page), pages);
      return { size, pages, page: safePage, start: (safePage - 1) * size, end: safePage * size };
    }
    function renderDetails() {
      const bounds = pageBounds(state.filteredRows.length, state.detailsPage);
      state.detailsPage = bounds.page;
      const visible = state.filteredRows.slice(bounds.start, bounds.end);
      elements.detailsRows.innerHTML = visible.map((row) => `
        <tr>
          <td><code>${escapeHtml(row.region)}</code></td>
          <td>${escapeHtml(row.category)}</td>
          <td><code>${escapeHtml(row.group)}</code></td>
          <td><code>${escapeHtml(row.feature)}</code></td>
          <td><span class="status status-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span></td>
          <td>${escapeHtml(row.message)}</td>
        </tr>`).join('') || '<tr><td colspan="6" class="empty">No checks match the current filters.</td></tr>';
      elements.detailsCount.textContent = `${state.filteredRows.length.toLocaleString()} checks`;
      elements.detailsPage.textContent = `Page ${bounds.page} of ${bounds.pages}`;
      elements.detailsPrev.disabled = bounds.page <= 1;
      elements.detailsNext.disabled = bounds.page >= bounds.pages;
    }
    function renderHeatmap() {
      const bounds = pageBounds(state.heatmapRows.length, state.heatmapPage);
      state.heatmapPage = bounds.page;
      const visible = state.heatmapRows.slice(bounds.start, bounds.end);
      const header = `<thead><tr><th>Group</th><th>Feature</th>${state.regions.map((region) => `<th>${escapeHtml(region)}</th>`).join('')}</tr></thead>`;
      const body = visible.map((row) => `<tr>
        <td><code>${escapeHtml(row.group)}</code></td>
        <td><code>${escapeHtml(row.feature)}</code></td>
        ${state.regions.map((region) => {
          const value = row.regions[region] || '';
          const css = value || 'unknown';
          return `<td><span class="status-dot status-${escapeHtml(css)}" title="${escapeHtml(value || 'not reported')}">${escapeHtml(statusLabels[value] || '?')}</span></td>`;
        }).join('')}
      </tr>`).join('') || `<tr><td colspan="${state.regions.length + 2}" class="empty">No features match the current filters.</td></tr>`;
      elements.heatmapTable.innerHTML = header + `<tbody>${body}</tbody>`;
      elements.heatmapCount.textContent = `${state.heatmapRows.length.toLocaleString()} feature rows`;
      elements.heatmapPage.textContent = `Page ${bounds.page} of ${bounds.pages}`;
      elements.heatmapPrev.disabled = bounds.page <= 1;
      elements.heatmapNext.disabled = bounds.page >= bounds.pages;
    }
    async function loadSnapshot() {
      const response = await fetch('api/latest.json', { cache: 'no-store' });
      const snapshot = await response.json();
      state.regions = Object.keys(snapshot.regions || {}).sort();
      state.rows = flatten(snapshot);
      populateSelect(elements.modality, [...new Set(state.rows.map((row) => row.category))].sort());
      populateSelect(elements.group, [...new Set(state.rows.map((row) => row.group))].sort());
      elements.loadStatus.textContent = `${state.rows.length.toLocaleString()} checks loaded from latest.json`;
      applyFilters();
    }
    elements.search.addEventListener('input', applyFilters);
    elements.modality.addEventListener('change', () => {
      const groups = [...new Set(state.rows.filter((row) => !elements.modality.value || row.category === elements.modality.value).map((row) => row.group))].sort();
      populateSelect(elements.group, groups);
      applyFilters();
    });
    elements.group.addEventListener('change', applyFilters);
    elements.status.addEventListener('change', applyFilters);
    elements.pageSize.addEventListener('change', applyFilters);
    elements.detailsPrev.addEventListener('click', () => { state.detailsPage -= 1; renderDetails(); });
    elements.detailsNext.addEventListener('click', () => { state.detailsPage += 1; renderDetails(); });
    elements.heatmapPrev.addEventListener('click', () => { state.heatmapPage -= 1; renderHeatmap(); });
    elements.heatmapNext.addEventListener('click', () => { state.heatmapPage += 1; renderHeatmap(); });
    loadSnapshot().catch((error) => { elements.loadStatus.textContent = `Could not load latest.json: ${error}`; });
"""


def write_static_summary(output_dir: Path) -> str:
    latest_path = output_dir / "api" / "latest.json"
    snapshot = load_snapshot(latest_path)
    rows = _flatten_snapshot(snapshot)
    return json.dumps(
        {
            "timestamp": snapshot.timestamp.isoformat(),
            "features": len(rows),
            "statuses": _status_counts(rows),
        },
        sort_keys=True,
    )
