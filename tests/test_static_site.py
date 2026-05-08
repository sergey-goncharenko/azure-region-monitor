from pathlib import Path

from azure_region_monitor.static_site import build_static_site


def test_build_static_site_writes_dashboard_and_latest_json(tmp_path):
    output_dir = tmp_path / "public"

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    latest_json = (output_dir / "api" / "latest.json").read_text(encoding="utf-8")

    assert "Azure Regional Feature Availability Monitor" in index_html
    assert "swedencentral" in index_html
    assert "extensions.gitops" in latest_json
    assert not (output_dir / "api" / "diff.json").exists()