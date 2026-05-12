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
    assert (output_dir / "methodology.html").exists()
    assert (output_dir / "favicon.svg").exists()
    assert (output_dir / "robots.txt").exists()
    assert (output_dir / "sitemap.xml").exists()
    assert (output_dir / "llms.txt").exists()
    assert (output_dir / "llms-full.txt").exists()
    assert (output_dir / "staticwebapp.config.json").exists()
    assert "Status meanings" in index_html
    assert "Public Alpha" in index_html
    assert "Current scans cover" in index_html
    assert "configured Azure public cloud regions" in index_html
    assert "unknown</span> usually means a probe failed, timed out" in index_html
    assert "GitHub repository" in index_html
    assert "https://github.com/sergey-goncharenko/azure-region-monitor" in index_html
    assert "swedencentral" in latest_json
    assert (output_dir / "index.html").stat().st_size < 1_000_000
    assert "extensions.gitops" in latest_json
    assert not (output_dir / "api" / "diff.json").exists()


def test_build_static_site_writes_crawl_and_llm_resources(tmp_path):
    output_dir = tmp_path / "public"

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )

    robots_txt = (output_dir / "robots.txt").read_text(encoding="utf-8")
    sitemap_xml = (output_dir / "sitemap.xml").read_text(encoding="utf-8")
    llms_txt = (output_dir / "llms.txt").read_text(encoding="utf-8")
    llms_full_txt = (output_dir / "llms-full.txt").read_text(encoding="utf-8")
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    config = json.loads((output_dir / "staticwebapp.config.json").read_text(encoding="utf-8"))

    assert "Sitemap: https://azwatch.operator.lat/sitemap.xml" in robots_txt
    assert "<loc>https://azwatch.operator.lat/</loc>" in sitemap_xml
    assert "<loc>https://azwatch.operator.lat/api/latest.json</loc>" in sitemap_xml
    assert "# Azure Regional Feature Availability Monitor" in llms_txt
    assert "api/latest.json" in llms_txt
    assert "Snapshot Shape" in llms_full_txt
    assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in index_html
    assert '<link rel="alternate" href="/llms.txt" type="text/plain" title="LLM guide">' in index_html
    assert config["mimeTypes"][".svg"] == "image/svg+xml"
    assert config["mimeTypes"][".xml"] == "application/xml"
    assert 'download="azure-region-monitor-latest.json"' in index_html


def test_build_static_site_writes_security_config(tmp_path):
    output_dir = tmp_path / "public"

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )

    config = json.loads((output_dir / "staticwebapp.config.json").read_text(encoding="utf-8"))
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert "Content-Security-Policy" in config["globalHeaders"]
    assert "frame-ancestors 'none'" in config["globalHeaders"]["Content-Security-Policy"]
    assert config["globalHeaders"]["X-Content-Type-Options"] == "nosniff"
    assert config["globalHeaders"]["X-Frame-Options"] == "DENY"
    assert config["globalHeaders"]["Permissions-Policy"]
    assert config["routes"][0]["route"] == "/api/latest.json"
    assert config["routes"][0]["headers"]["Access-Control-Allow-Origin"] == "*"
    assert (
        config["routes"][0]["headers"]["Content-Disposition"]
        == 'attachment; filename="azure-region-monitor-latest.json"'
    )
    assert config["routes"][1]["route"] == "/api/*"
    assert config["routes"][1]["headers"]["Access-Control-Allow-Origin"] == "*"
    assert "hatscripts.github.io" not in index_html


def test_build_static_site_writes_status_methodology_page(tmp_path):
    output_dir = tmp_path / "public"

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )

    methodology_html = (output_dir / "methodology.html").read_text(encoding="utf-8")
    heatmap_html = (output_dir / "heatmap.html").read_text(encoding="utf-8")

    assert "Plain-language guide" in methodology_html
    assert "Public Alpha" in methodology_html
    assert "Region scope" in methodology_html
    assert "configured public Azure region list" in methodology_html
    assert "sovereign cloud" in methodology_html
    assert "not a quota result" in methodology_html
    assert "az functionapp list-flexconsumption-locations --output json" in methodology_html
    assert "Quota is separate" in methodology_html
    assert "AKS extensions" in methodology_html
    assert "Azure AI models" in methodology_html
    assert "locations/models" in methodology_html
    assert "Container Apps" in methodology_html
    assert "VM SKUs" in methodology_html
    assert "methodology.html" in heatmap_html
    assert "Public Alpha" in heatmap_html


def test_build_static_site_copies_history_and_renders_recent_changes(tmp_path):
    output_dir = tmp_path / "public"
    history_dir = tmp_path / "history"
    (history_dir / "changes").mkdir(parents=True)
    (history_dir / "snapshots").mkdir(parents=True)
    recent_changes = {
        "generated_at": "2026-05-10T00:00:00Z",
        "days": [
            {
                "date": "2026-05-10",
                "snapshot_path": "snapshots/2026-05-10.json",
                "change_path": "changes/2026-05-10.json",
                "total_changes": 2,
                "change_type_counts": {
                    "new_availability": 1,
                    "regression": 1,
                    "status_change": 0,
                },
                "highlights": [
                    {
                        "region": "eastus",
                        "group": "microsoft",
                        "feature": "extensionTypes.microsoft.flux",
                        "previous": "unavailable",
                        "current": "available",
                    }
                ],
            }
        ],
    }
    (history_dir / "recent-changes.json").write_text(json.dumps(recent_changes), encoding="utf-8")
    (history_dir / "changes" / "2026-05-10.json").write_text(
        json.dumps(recent_changes["days"][0]), encoding="utf-8"
    )
    (history_dir / "snapshots" / "2026-05-10.json").write_text("{}", encoding="utf-8")

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
        history_path=history_dir,
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert "Recent Changes" in index_html
    assert "Today plus previous change days" in index_html
    assert 'href="api/history/changes/2026-05-10.json"' in index_html
    assert "eastus flux unavailable -> available" in index_html
    assert (output_dir / "api" / "history" / "recent-changes.json").exists()
    assert (output_dir / "api" / "history" / "changes" / "2026-05-10.json").exists()


def test_build_static_site_shows_uniform_extension_availability(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "public"
    snapshot = {
        "timestamp": "2026-05-08T00:00:00Z",
        "regions": {
            "australiaeast": {
                "aks": {
                    "extensionTypes.azure.policy": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
            },
            "francecentral": {
                "aks": {
                    "extensionTypes.azure.policy": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
            },
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
    assert "Unknowns To Investigate" in index_html
    assert "1 unknown checks" in index_html
    assert "Use this as a probe quality backlog" in index_html
    assert "Catalog failed." in index_html
    assert "extensionCatalog" in index_html
    assert "availability-tooltip-trigger" in index_html
    assert "renderRegionalAvailability" in index_html
    assert "renderAvailabilityCell" in index_html
    assert "initializeAvailabilityTooltips" in index_html
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
            "australiaeast": {
                "aks": {
                    "extensionTypes.azure.policy": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
            },
            "eastus": {
                "aks": {
                    "extensionTypes.microsoft.flux": {"status": "available"},
                    "kubernetesVersions.1.34": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
                "functions": {
                    "hostingPlans.flexConsumption": {"status": "available"},
                    "runtimes.python.3.12": {"status": "available"},
                },
                "ai": {
                    "aiModels.openai.gpt-4o.2024-08-06": {"status": "available"},
                    "aiModels.mistral-ai.mistral-large.2407": {"status": "unavailable"},
                },
                "containerApps": {
                    "containerApps.managedEnvironments": {"status": "available"},
                    "containerApps.daprComponents": {"status": "unavailable"},
                    "containerApps.connectedEnvironments": {"status": "unavailable"},
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
    assert "Azure Functions" in index_html
    assert "Azure AI models" in index_html
    assert "Container Apps" in index_html
    assert "VM SKUs" in index_html
    assert "<td>None</td>" not in index_html


def test_build_static_site_color_codes_regional_modality_groups(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "public"
    snapshot = {
        "timestamp": "2026-05-08T00:00:00Z",
        "regions": {
            "australiaeast": {
                "aks": {
                    "extensionTypes.azure.policy": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
            },
            "francecentral": {
                "aks": {
                    "extensionTypes.azure.policy": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                },
            },
            "eastus": {
                "aks": {
                    "extensionTypes.microsoft.flux": {"status": "available"},
                    "extensionTypes.microsoft.dapr": {"status": "unavailable"},
                    "extensionTypes.azure.policy": {"status": "available"},
                    "kubernetesVersions.1.34": {"status": "available"},
                },
                "compute": {
                    "vmSkus.standard.b2s": {"status": "available"},
                    "vmSkus.standard.b2ms": {"status": "unavailable"},
                    "vmSkus.standard.d2s.v5": {"status": "available"},
                    "vmSkus.standard.d4s.v5": {"status": "unavailable"},
                    "vmSkus.standard.d8s.v5": {"status": "unavailable"},
                    "vmSkus.standard.e2s.v5": {"status": "unavailable"},
                    "vmSkus.standard.e4s.v5": {"status": "unavailable"},
                    "vmSkus.standard.e8s.v5": {"status": "unavailable"},
                },
                "functions": {
                    "hostingPlans.flexConsumption": {"status": "available"},
                    "runtimes.python.3.12": {"status": "available"},
                    "runtimes.node.22": {"status": "unavailable"},
                },
                "ai": {
                    "aiModels.openai.gpt-4o.2024-08-06": {"status": "available"},
                    "aiModels.mistral-ai.mistral-large.2407": {"status": "unavailable"},
                },
                "containerApps": {
                    "containerApps.managedEnvironments": {"status": "available"},
                    "containerApps.apps": {"status": "available"},
                    "containerApps.jobs": {"status": "available"},
                    "containerApps.daprComponents": {"status": "unavailable"},
                    "containerApps.connectedEnvironments": {"status": "unavailable"},
                },
            }
        },
    }
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    build_static_site(
        output_dir, snapshot_path=snapshot_path, diff_path=tmp_path / "missing-diff.json"
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert "Loading group / region matrices from api/latest.json" in index_html
    assert "regional-availability-root" in index_html
    assert "renderRegionalAvailability" in index_html
    assert "renderAvailabilityCell" in index_html
    assert "regionCountryCode" in index_html
    assert "region-flag-fallback" in index_html
    assert "regionShortLabel" in index_html
    assert "availability-single" in index_html
    assert "Groups by Azure region, rendered from api/latest.json" in index_html
    assert "circle-flags" not in index_html
    assert "\U0001f1fa\U0001f1f8" not in index_html
    assert "availability-good" in index_html
    assert "availability-warn" in index_html
    assert "availability-caution" in index_html
    assert "availability-poor" in index_html
    assert "<td><code>azure</code></td>" in index_html
    assert "<td><code>microsoft</code></td>" in index_html
    assert "<td><code>hosting plans</code></td>" in index_html
    assert "<td><code>python</code></td>" in index_html
    assert "<td><code>node</code></td>" in index_html
    assert "<td><code>openai</code></td>" in index_html
    assert "<td><code>mistral-ai</code></td>" in index_html
    assert "<td><code>core</code></td>" in index_html
    assert "<td><code>dapr</code></td>" in index_html
    assert "<td><code>connected environments</code></td>" in index_html
    assert "<td><code>D</code></td>" in index_html
    assert "<td><code>E</code></td>" in index_html
    assert "${escapeHtml(statusInitial(status))}" in index_html
    assert "availability-count" in index_html


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


def test_build_static_site_splits_large_extension_groups_into_detail_tables(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    output_dir = tmp_path / "public"
    eastus_features = {}
    westus_features = {}
    for index in range(11):
        feature = f"extensionTypes.microsoft.extension{index}"
        eastus_features[feature] = {"status": "available"}
        westus_features[feature] = {"status": "unavailable"}
    for index in range(11):
        feature = f"extensionTypes.contoso.extension{index}"
        eastus_features[feature] = {"status": "available"}
        westus_features[feature] = {"status": "unavailable"}
    for index in range(10):
        feature = f"extensionTypes.boutique.extension{index}"
        eastus_features[feature] = {"status": "available"}
        westus_features[feature] = {"status": "available"}
    snapshot = {
        "timestamp": "2026-05-08T00:00:00Z",
        "regions": {
            "eastus": {"aks": eastus_features},
            "westus": {"aks": westus_features},
        },
    }
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    build_static_site(
        output_dir, snapshot_path=snapshot_path, diff_path=tmp_path / "missing-diff.json"
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert "Large AKS Extension Groups" in index_html
    assert "Loading extension groups from api/latest.json" in index_html
    assert "renderLargeExtensionGroups" in index_html
    assert "largeExtensionGroups" in index_html
    assert "extension-group-collapsed" in index_html
    assert "Open to load this extension matrix." in index_html
    assert "<th>Extension</th>" in index_html
    assert "extension0" not in index_html
    assert "extensionTypes.microsoft.extension0" not in index_html
    assert index_html.index("Regional Availability By Modality") < index_html.index(
        "Large AKS Extension Groups"
    )
