import json
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
    assert (output_dir / "heatmap.html").exists()
    assert "swedencentral" in index_html
    assert "extensions.gitops" in latest_json
    assert not (output_dir / "api" / "diff.json").exists()


def test_build_static_site_shows_uniform_extension_availability(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "public"
    snapshot = {
        "timestamp": "2026-05-08T00:00:00Z",
        "regions": {
            "eastus": {
                "aks": {
                    "extensionCatalog": {
                        "status": "unknown",
                        "message": "Catalog failed.",
                    },
                    "extensions.gitops": {
                        "status": "available",
                        "message": "Checked AKS extension type 'microsoft.flux' in eastus.",
                    }
                }
            },
            "westeurope": {
                "aks": {
                    "extensions.gitops": {
                        "status": "available",
                        "message": "Checked AKS extension type 'microsoft.flux' in westeurope.",
                    }
                }
            },
        },
    }
    snapshot_path.write_text(
        json.dumps(snapshot),
        encoding="utf-8",
    )

    build_static_site(
        output_dir, snapshot_path=snapshot_path, diff_path=tmp_path / "missing-diff.json"
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    heatmap_html = (output_dir / "heatmap.html").read_text(encoding="utf-8")

    assert "AKS extensions" in index_html
    assert "curated" in index_html
    assert "Detailed heatmap" in index_html
    assert "Check Details" in heatmap_html
    assert "Curated AKS extensions" not in index_html
    assert "AKS extension catalog" not in index_html


def test_build_static_site_groups_modalities_by_feature_family(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "public"
    snapshot = {
        "timestamp": "2026-05-08T00:00:00Z",
        "regions": {
            "eastus": {
                "aks": {
                    "extensionTypes.microsoft.flux": {"status": "available"},
                    "kubernetesVersions.1.34": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
            }
        },
    }
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    build_static_site(
        output_dir, snapshot_path=snapshot_path, diff_path=tmp_path / "missing-diff.json"
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert "AKS extensions" in index_html
    assert "AKS Kubernetes versions" in index_html
    assert "VM SKUs" in index_html
    assert "<td>None</td>" not in index_html


def test_build_static_site_uses_paged_detail_page_for_heavy_tables(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "public"
    eastus_features = {}
    westus_features = {}
    for index in range(400):
        feature = f"vmSkus.standard.test{index}"
        eastus_features[feature] = {"status": "available"}
        westus_features[feature] = {"status": "unavailable"}
    snapshot = {
        "timestamp": "2026-05-08T00:00:00Z",
        "regions": {
            "eastus": {"compute": eastus_features},
            "westus": {"compute": westus_features},
        },
    }
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    build_static_site(
        output_dir, snapshot_path=snapshot_path, diff_path=tmp_path / "missing-diff.json"
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    heatmap_html = (output_dir / "heatmap.html").read_text(encoding="utf-8")

    assert "Showing 300 of" not in index_html
    assert "Raw Checks" not in index_html
    assert "Check Details" in heatmap_html
    assert "heatmap-prev" in heatmap_html
    assert "details-next" in heatmap_html
    assert "fetch('api/latest.json'" in heatmap_html
    assert index_html.count("vmSkus.standard.test") == 0
