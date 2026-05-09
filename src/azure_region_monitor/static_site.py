from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from azure_region_monitor.models import Snapshot
from azure_region_monitor.storage import load_snapshot


def build_static_site(
    output_dir: Path,
    snapshot_path: Path = Path("data/snapshots/latest.json"),
    diff_path: Path = Path("data/diffs/latest.json"),
) -> None:
    snapshot = load_snapshot(snapshot_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    api_dir = output_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(snapshot_path, api_dir / "latest.json")
    if diff_path.exists():
        shutil.copyfile(diff_path, api_dir / "diff.json")

    (output_dir / "index.html").write_text(_render_index(snapshot), encoding="utf-8")
    (output_dir / "heatmap.html").write_text(_render_heatmap_page(snapshot), encoding="utf-8")


def _render_index(snapshot: Snapshot) -> str:
    rows = _flatten_snapshot(snapshot)
    status_counts = _status_counts(rows)
    status_total = sum(status_counts.values())
    available_percent = (
        round((status_counts.get("available", 0) / status_total) * 100, 1) if status_total else 0
    )
    regions = sorted(snapshot.regions)
    unique_features = sorted({str(row["feature"]) for row in rows})
    modality_rows = "\n".join(_render_modality_row(row) for row in _modality_summaries(rows))
    region_modality_rows = "\n".join(
        _render_region_modality_row(row) for row in _region_modality_summaries(rows)
    )
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
        <a href="heatmap.html">Detailed heatmap</a>
        <a href="api/latest.json">api/latest.json</a>
      </nav>
    </header>
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
    <section class="panel" aria-label="Region modality availability">
      <div class="panel-header">
        <h2>Regional Availability By Modality</h2>
        <div class="panel-subtitle">Grouped availability shown as available / total</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th class="number">AKS extensions</th>
              <th class="number">AKS Kubernetes versions</th>
              <th class="number">VM SKUs</th>
              <th class="number">Unknown</th>
            </tr>
          </thead>
          <tbody>{region_modality_rows}</tbody>
        </table>
      </div>
    </section>
  </main>
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
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 10px; margin: 18px 0; }
    .metric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
    .metric-value { font-size: 24px; font-weight: 650; }
    .metric-label { color: var(--muted); font-size: 13px; margin-top: 2px; }
    .status-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; }
    .layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 1fr); gap: 14px; align-items: start; margin-bottom: 14px; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; margin-bottom: 14px; }
    .panel-header { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; padding: 14px 14px 0; }
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
    .status-dot { display: inline-flex; width: 22px; height: 22px; border-radius: 50%; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; line-height: 1; }
    .availability-groups { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 5px; min-width: 220px; }
    .availability-badge { display: inline-flex; gap: 5px; align-items: center; min-height: 24px; padding: 3px 7px; border-radius: 999px; border: 1px solid transparent; font-size: 12px; font-weight: 650; white-space: nowrap; }
    .availability-label { max-width: 96px; overflow: hidden; text-overflow: ellipsis; }
    .availability-count { font-variant-numeric: tabular-nums; opacity: 0.82; }
    .availability-good { background: #e5f6ee; border-color: #b6e4ca; color: #116339; }
    .availability-warn { background: #fff7ce; border-color: #ecd56b; color: #6e5500; }
    .availability-caution { background: #ffefd8; border-color: #f2bd72; color: #8a4a05; }
    .availability-poor { background: #fdecec; border-color: #efb8ba; color: #9d1c20; }
    .availability-empty { background: #edf1f6; border-color: #d0d8e3; color: #4f5f73; }
    .empty { color: var(--muted); text-align: center; padding: 24px; }
    @media (max-width: 720px) {
      main { padding: 20px 12px 32px; }
      header { display: block; }
      h1 { font-size: 22px; }
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


def _feature_category(feature: str) -> str:
    if feature == "extensionCatalog":
        return "AKS extensions"
    if _is_extension_feature(feature):
        return "AKS extensions"
    if feature.startswith("kubernetesVersions."):
        return "AKS Kubernetes versions"
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


def _region_modality_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    categories = ["AKS extensions", "AKS Kubernetes versions", "VM SKUs"]
    for row in rows:
        region = str(row["region"])
        category = str(row["category"])
        group = str(row["group"])
        summary = summaries.setdefault(region, {"region": region, "unknown": 0, "categories": {}})
        if row["status"] == "unknown":
            summary["unknown"] = int(summary["unknown"]) + 1
        category_summary = summary["categories"].setdefault(category, {})
        group_summary = category_summary.setdefault(group, {"available": 0, "total": 0})
        group_summary["total"] += 1
        if row["status"] == "available":
            group_summary["available"] += 1

    for summary in summaries.values():
        for category in categories:
            summary["categories"].setdefault(category, {})
    return sorted(summaries.values(), key=lambda item: str(item["region"]))


def _render_region_modality_row(row: dict[str, object]) -> str:
    categories = row["categories"]
    return f"""<tr>
                <td><code>{html.escape(str(row["region"]))}</code></td>
    <td>{_render_availability_groups(categories["AKS extensions"])}</td>
    <td>{_render_availability_groups(categories["AKS Kubernetes versions"])}</td>
    <td>{_render_availability_groups(categories["VM SKUs"])}</td>
                <td class="number">{row["unknown"]}</td>
              </tr>"""


def _render_availability_groups(groups: dict[str, dict[str, int]]) -> str:
    if not groups:
        return '<span class="availability-badge availability-empty">No checks</span>'

    badges = []
    for group, summary in sorted(groups.items()):
        available = summary["available"]
        total = summary["total"]
        missing = total - available
        health_class = _availability_health_class(available, total)
        title = f"{group}: {available:,} available, {missing:,} not available, {total:,} total"
        badges.append(
            f'<span class="availability-badge {health_class}" title="{html.escape(title)}">'
            f'<span class="availability-label">{html.escape(group)}</span>'
            f'<span class="availability-count">{available:,}/{total:,}</span>'
            "</span>"
        )
    return f'<div class="availability-groups">{"".join(badges)}</div>'


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
      if (feature.startsWith('vmSkus.')) return 'VM SKUs';
      return feature.split('.')[0];
    }
    function group(feature) {
      if (feature.startsWith('extensionTypes.')) return feature.replace('extensionTypes.', '').split('.')[0] || 'unknown';
      if (feature.startsWith('extensions.')) return 'curated';
      if (feature.startsWith('kubernetesVersions.')) return feature.replace('kubernetesVersions.', '');
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
