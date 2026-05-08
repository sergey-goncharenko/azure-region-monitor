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
    table_rows = "\n".join(_render_row(row) for row in rows)

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
      max-width: 1180px;
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
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(110px, 1fr));
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
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; font-weight: 650; text-transform: uppercase; }}
    tr:last-child td {{ border-bottom: 0; }}
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
    code {{ color: var(--text); }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 12px 32px; }}
      header {{ display: block; }}
      h1 {{ font-size: 22px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
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
      {_render_metric("Available", status_counts.get("available", 0))}
      {_render_metric("Unavailable", status_counts.get("unavailable", 0))}
      {_render_metric("Partial", status_counts.get("partial", 0))}
      {_render_metric("Unknown", status_counts.get("unknown", 0))}
    </section>
    <section class="table-wrap" aria-label="Regional availability matrix">
      <table>
        <thead>
          <tr>
            <th>Region</th>
            <th>Service</th>
            <th>Feature</th>
            <th>Status</th>
            <th>Latency</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </section>
  </main>
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


def _render_metric(label: str, value: int) -> str:
    return f"""<div class="metric">
        <div class="metric-value">{value}</div>
        <div class="metric-label">{html.escape(label)}</div>
      </div>"""


def _render_row(row: dict[str, object]) -> str:
    status = str(row["status"])
    latency = "" if row["latency_ms"] is None else f"{row['latency_ms']} ms"
    return f"""<tr>
            <td><code>{html.escape(str(row["region"]))}</code></td>
            <td>{html.escape(str(row["service"]))}</td>
            <td><code>{html.escape(str(row["feature"]))}</code></td>
            <td><span class="status status-{html.escape(status)}">{html.escape(status)}</span></td>
            <td>{html.escape(latency)}</td>
            <td>{html.escape(str(row["message"]))}</td>
          </tr>"""


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