from __future__ import annotations

import html
import json
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


def _render_index(snapshot: Snapshot) -> str:
    rows = _flatten_snapshot(snapshot)
    status_counts = _status_counts(rows)
    status_total = sum(status_counts.values())
    available_percent = round((status_counts.get("available", 0) / status_total) * 100, 1) if status_total else 0
    regions = sorted(snapshot.regions)
    unique_features = sorted({str(row["feature"]) for row in rows})
    categories = sorted({str(row["category"]) for row in rows})
    table_rows = "\n".join(_render_raw_row(row) for row in rows)
    category_options = "\n".join(
        f'<option value="{html.escape(category, quote=True)}">{html.escape(category)}</option>'
        for category in categories
    )
    modality_rows = "\n".join(_render_modality_row(row) for row in _modality_summaries(rows))
    region_rows = "\n".join(_render_region_row(row) for row in _region_summaries(rows))
    difference_rows = "\n".join(_render_difference_row(row, regions) for row in _difference_summaries(rows))
    difference_body = difference_rows or (
        f'<tr><td colspan="{len(regions) + 2}" class="empty">No regional status differences in this snapshot.</td></tr>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Azure Regional Feature Availability Monitor</title>
  <style>
    :root {{
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
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px 18px 42px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: flex-end;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1.2;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .timestamp {{ color: var(--muted); font-size: 14px; }}
    a {{ color: #2759a5; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .metric-value {{ font-size: 24px; font-weight: 650; }}
    .metric-label {{ color: var(--muted); font-size: 13px; margin-top: 2px; }}
    .status-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 18px;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(360px, 0.9fr);
      gap: 14px;
      align-items: start;
      margin-bottom: 14px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .panel-header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      padding: 14px 14px 0;
    }}
    h2 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.3;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .panel-subtitle {{ color: var(--muted); font-size: 13px; }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .panel .table-wrap {{ border: 0; border-radius: 0; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; font-weight: 650; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: 0; }}
    .number {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .matrix table {{ min-width: 980px; }}
    .matrix th, .matrix td {{ text-align: center; }}
    .matrix th:first-child, .matrix td:first-child,
    .matrix th:nth-child(2), .matrix td:nth-child(2) {{ text-align: left; }}
    .matrix .table-wrap {{ max-height: 560px; }}
    .matrix th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: var(--panel);
    }}
    .matrix th:first-child,
    .matrix td:first-child {{
      position: sticky;
      left: 0;
      z-index: 1;
      background: var(--panel);
      min-width: 76px;
    }}
    .matrix th:nth-child(2),
    .matrix td:nth-child(2) {{
      position: sticky;
      left: 76px;
      z-index: 1;
      background: var(--panel);
      min-width: 280px;
      max-width: 360px;
    }}
    .matrix th:first-child,
    .matrix th:nth-child(2) {{ z-index: 3; }}
    .empty {{ color: var(--muted); text-align: center; padding: 24px; }}
    .status {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 650;
    }}
    .status-available {{ background: var(--available-bg); color: var(--available-text); }}
    .status-unavailable {{ background: var(--unavailable-bg); color: var(--unavailable-text); }}
    .status-partial {{ background: var(--partial-bg); color: var(--partial-text); }}
    .status-unknown {{ background: var(--unknown-bg); color: var(--unknown-text); }}
    .status-dot {{
      display: inline-flex;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 700;
      line-height: 1;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding: 10px 14px 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .legend-item {{ display: inline-flex; align-items: center; gap: 5px; }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(160px, 220px) minmax(200px, 260px);
      gap: 10px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }}
    input, select {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      padding: 6px 10px;
      font: inherit;
      color: var(--text);
      background: #fff;
    }}
    details {{ margin-top: 14px; }}
    summary {{
      cursor: pointer;
      padding: 14px;
      font-weight: 650;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    details[open] summary {{ border-radius: 8px 8px 0 0; border-bottom: 0; }}
    details .panel {{ border-radius: 0 0 8px 8px; }}
    code {{ color: var(--text); }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 12px 32px; }}
      header {{ display: block; }}
      h1 {{ font-size: 22px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .layout {{ grid-template-columns: 1fr; }}
      .toolbar {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Azure Regional Feature Availability Monitor</h1>
        <div class="timestamp">Latest snapshot: {html.escape(snapshot.timestamp.isoformat())}</div>
      </div>
      <a href="api/latest.json">api/latest.json</a>
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
          <div class="panel-subtitle">Grouped by feature family</div>
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
          <h2>Regions</h2>
          <div class="panel-subtitle">Availability by location</div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Region</th>
                <th class="number">Checks</th>
                <th class="number">Available</th>
                <th class="number">Unavailable</th>
                <th class="number">Unknown</th>
              </tr>
            </thead>
            <tbody>{region_rows}</tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="panel matrix" aria-label="Regional differences">
      <div class="panel-header">
        <h2>Regional Differences</h2>
        <div class="panel-subtitle">Features with mixed status across tested regions</div>
      </div>
      <div class="legend" aria-label="Status legend">
        <span class="legend-item"><span class="status-dot status-available">A</span> Available</span>
        <span class="legend-item"><span class="status-dot status-unavailable">U</span> Unavailable</span>
        <span class="legend-item"><span class="status-dot status-partial">P</span> Partial</span>
        <span class="legend-item"><span class="status-dot status-unknown">?</span> Unknown</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Service</th>
              <th>Feature</th>
              {_render_region_headers(regions)}
            </tr>
          </thead>
          <tbody>{difference_body}</tbody>
        </table>
      </div>
    </section>
    <details>
      <summary>Raw Checks ({len(rows)})</summary>
      <section class="panel" aria-label="Raw regional availability checks">
        <div class="toolbar">
          <input id="raw-search" type="search" placeholder="Search region, feature, or message" aria-label="Search raw checks">
          <select id="raw-status" aria-label="Filter by status">
            <option value="">All statuses</option>
            <option value="available">Available</option>
            <option value="unavailable">Unavailable</option>
            <option value="partial">Partial</option>
            <option value="unknown">Unknown</option>
          </select>
          <select id="raw-category" aria-label="Filter by modality">
            <option value="">All modalities</option>
            {category_options}
          </select>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Region</th>
                <th>Service</th>
                <th>Modality</th>
                <th>Feature</th>
                <th>Status</th>
                <th>Latency</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody id="raw-rows">{table_rows}</tbody>
          </table>
        </div>
      </section>
    </details>
  </main>
  <script>
    const rawRows = Array.from(document.querySelectorAll('#raw-rows tr'));
    const searchInput = document.getElementById('raw-search');
    const statusSelect = document.getElementById('raw-status');
    const categorySelect = document.getElementById('raw-category');
    function applyRawFilters() {{
      const query = searchInput.value.trim().toLowerCase();
      const status = statusSelect.value;
      const category = categorySelect.value;
      rawRows.forEach((row) => {{
        const rowText = row.searchText || (row.searchText = row.textContent.toLowerCase());
        const matchesQuery = !query || rowText.includes(query);
        const matchesStatus = !status || row.dataset.status === status;
        const matchesCategory = !category || row.dataset.category === category;
        row.hidden = !(matchesQuery && matchesStatus && matchesCategory);
      }});
    }}
    searchInput.addEventListener('input', applyRawFilters);
    statusSelect.addEventListener('change', applyRawFilters);
    categorySelect.addEventListener('change', applyRawFilters);
  </script>
</body>
</html>
"""


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


def _render_raw_row(row: dict[str, object]) -> str:
    status = str(row["status"])
    latency = "" if row["latency_ms"] is None else f"{row['latency_ms']} ms"
    return f"""<tr data-status="{html.escape(status, quote=True)}" data-category="{html.escape(str(row["category"]), quote=True)}">
            <td><code>{html.escape(str(row["region"]))}</code></td>
            <td>{html.escape(str(row["service"]))}</td>
            <td>{html.escape(str(row["category"]))}</td>
            <td><code>{html.escape(str(row["feature"]))}</code></td>
            <td><span class="status status-{html.escape(status)}">{html.escape(status)}</span></td>
            <td>{html.escape(latency)}</td>
            <td>{html.escape(str(row["message"]))}</td>
          </tr>"""


def _feature_category(feature: str) -> str:
    if feature.startswith("extensionTypes."):
        return "AKS extension catalog"
    if feature.startswith("extensions."):
        return "Curated AKS extensions"
    if feature.startswith("kubernetesVersions."):
        return "AKS Kubernetes versions"
    return feature.split(".", 1)[0]


def _modality_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        category = str(row["category"])
        summary = summaries.setdefault(
            category,
            {
                "category": category,
                "features": set(),
                "checks": 0,
                "statuses": {},
            },
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


def _region_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        region = str(row["region"])
        summary = summaries.setdefault(region, {"region": region, "checks": 0, "statuses": {}})
        summary["checks"] = int(summary["checks"]) + 1
        statuses = summary["statuses"]
        status = str(row["status"])
        statuses[status] = statuses.get(status, 0) + 1
    return sorted(summaries.values(), key=lambda item: str(item["region"]))


def _render_region_row(row: dict[str, object]) -> str:
    statuses = row["statuses"]
    return f"""<tr>
                <td><code>{html.escape(str(row["region"]))}</code></td>
                <td class="number">{row["checks"]}</td>
                <td class="number">{statuses.get("available", 0)}</td>
                <td class="number">{statuses.get("unavailable", 0)}</td>
                <td class="number">{statuses.get("unknown", 0)}</td>
              </tr>"""


def _difference_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    features: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row["service"]), str(row["feature"]))
        summary = features.setdefault(
            key,
            {"service": key[0], "feature": key[1], "regions": {}},
        )
        summary["regions"][str(row["region"])] = str(row["status"])

    differences = []
    for summary in features.values():
        statuses = set(summary["regions"].values())
        if len(statuses) > 1:
            differences.append(summary)
    return sorted(differences, key=lambda item: (str(item["service"]), str(item["feature"])))


def _render_region_headers(regions: list[str]) -> str:
    return "\n".join(f"<th>{html.escape(region)}</th>" for region in regions)


def _render_difference_row(row: dict[str, object], regions: list[str]) -> str:
    cells = "\n".join(_render_status_dot(row["regions"].get(region, "")) for region in regions)
    return f"""<tr>
              <td>{html.escape(str(row["service"]))}</td>
              <td><code>{html.escape(str(row["feature"]))}</code></td>
              {cells}
            </tr>"""


def _render_status_dot(status: str) -> str:
    labels = {"available": "A", "unavailable": "U", "partial": "P", "unknown": "?", "": "-"}
    css_status = status or "unknown"
    title = status or "not reported"
    return f'<td><span class="status-dot status-{html.escape(css_status)}" title="{html.escape(title, quote=True)}">{html.escape(labels.get(status, "?"))}</span></td>'


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