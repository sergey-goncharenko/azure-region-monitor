import json
from pathlib import Path

from azure_region_monitor.static_site import (
    _region_badge,
    _region_country_name,
    _region_short_label,
    _render_narrative_banner,
    _render_region_header,
    _sort_regions,
    build_static_site,
    _render_regional_latency_section,
)


def test_narrative_banner_renders_ai_blog_post_with_headline_and_paragraphs():
    day = {
        "narrative": "Germany North lights up\n\nA wave of VM SKUs rolled out.\n\nNo regressions.",
        "narrative_source": "ai",
    }
    html = _render_narrative_banner(day)
    assert 'class="narrative-headline"' in html
    assert "Germany North lights up" in html
    # Two body paragraphs after the headline.
    assert html.count("<p>") == 2
    assert "AI summary" in html


def test_narrative_banner_single_block_ai_splits_first_line_as_headline():
    day = {"narrative": "Big rollout day\nVM SKUs surged in Germany North.", "narrative_source": "ai"}
    html = _render_narrative_banner(day)
    assert 'class="narrative-headline"' in html
    assert "Big rollout day" in html
    assert "VM SKUs surged" in html


def test_narrative_banner_rule_source_stays_single_paragraph():
    day = {"narrative": "Latest scan: 3 new availability signals.", "narrative_source": "rule"}
    html = _render_narrative_banner(day)
    assert "narrative-headline" not in html
    assert "Auto summary" in html


def test_geography_regions_named_as_asia_and_europe():
    # East Asia / Southeast Asia / North Europe / West Europe are multi-country Azure
    # geographies. They must read as Asia/Europe, not as Hong Kong/Singapore/etc.
    assert _region_country_name("eastasia") == "East Asia"
    assert _region_country_name("southeastasia") == "Southeast Asia"
    assert _region_country_name("northeurope") == "North Europe"
    assert _region_country_name("westeurope") == "West Europe"
    # Geography badge, not a single-country code.
    assert _region_badge("eastasia") == "AS"
    assert _region_badge("westeurope") == "EU"
    # Short label carries the geography word so it is visible on screen.
    assert _region_short_label("southeastasia") == "SE Asia"
    assert _region_short_label("northeurope") == "N Europe"


def test_region_header_shows_geography_name():
    header = _render_region_header("eastasia")
    assert "East Asia" in header
    assert "AS" in header
    assert "Hong Kong" not in header

    europe = _render_region_header("westeurope")
    assert "West Europe" in europe
    assert "Netherlands" not in europe


def test_ordinary_regions_still_named_by_country():
    assert _region_country_name("eastus") == "United States"
    assert _region_country_name("japaneast") == "Japan"
    assert _region_badge("japaneast") == "JP"


def test_geography_regions_sort_by_their_geography_name():
    order = _sort_regions(
        {"westus": 1, "eastasia": 1, "northeurope": 1, "southeastasia": 1, "westeurope": 1}
    )
    # Sorted by display name: East Asia, North Europe, Southeast Asia, United States, West Europe.
    assert order == ["eastasia", "northeurope", "southeastasia", "westus", "westeurope"]


def _ai_latency_snapshot():
    from azure_region_monitor.models import FeatureResult, Snapshot

    def result(region, p50):
        return FeatureResult(
            status="available",
            latency_ms=p50,
            message=f"m from {region}: p50 {p50}ms, p95 {p50 + 40}ms, TTFT p50 {p50 - 50}ms, 50.0 tok/s over 3/3 samples.",
        )

    return Snapshot(
        regions={
            "eastus": {
                "ai-latency": {
                    "aiLatency.openai.gpt-4o": result("eastus", 1090),
                    "aiLatency.openai.gpt-5.1": result("eastus", 1293),
                }
            },
            "westus3": {
                "ai-latency": {
                    "aiLatency.openai.gpt-4o": result("westus3", 658),
                    "aiLatency.openai.gpt-5.1": result("westus3", 886),
                }
            },
            "uksouth": {
                "ai-latency": {"aiLatency.openai.gpt-4o": result("uksouth", 950)}
            },
        }
    )


def test_regional_latency_section_groups_by_model():
    html = _render_regional_latency_section(_ai_latency_snapshot())

    # One sub-table heading per model, not a single hardcoded "(gpt-4o)" title.
    assert "<h3>gpt-4o &middot; 3 regions</h3>" in html
    assert "<h3>gpt-5.1 &middot; 2 regions</h3>" in html
    assert "Azure Per-Region Latency</h2>" in html
    # gpt-5.1 is visible (the bug was that it was rendered but unlabeled).
    assert html.count("gpt-5.1") >= 1
    # Two separate tables.
    assert html.count("<table>") == 2


def test_regional_latency_section_shows_rank_deltas():
    prev = {"gpt-4o": {"eastus": 1, "westus3": 3}}
    html = _render_regional_latency_section(_ai_latency_snapshot(), prev)

    # Rank column header present.
    assert "<th>Rank</th>" in html
    # westus3 is fastest now (#1) and was #3 -> moved up 2.
    assert "rank-up" in html
    # eastus was #1, now slower -> moved down.
    assert "rank-down" in html
    # gpt-5.1 has no previous ranks -> rows marked new.
    assert "rank-new" in html


def test_regional_latency_section_empty_without_data():
    from azure_region_monitor.models import FeatureResult, Snapshot

    snap = Snapshot(regions={"eastus": {"ai": {"aiModels.x.y.1": FeatureResult(status="available")}}})
    assert _render_regional_latency_section(snap) == ""


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
    assert (output_dir / "insights" / "index.html").exists()
    assert (output_dir / "insights" / "azure-openai-regional-availability.html").exists()
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
    assert "unknown</span> means the monitor parked that check" in index_html
    assert "GitHub repository" in index_html
    assert "https://github.com/sergey-goncharenko/azure-region-monitor" in index_html
    assert "swedencentral" in latest_json
    assert (output_dir / "index.html").stat().st_size < 1_000_000
    assert "extensions.gitops" in latest_json
    assert not (output_dir / "api" / "diff.json").exists()


def test_build_static_site_writes_modality_shards_and_summary(tmp_path):
    output_dir = tmp_path / "public"

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )

    api_dir = output_dir / "api"
    # Monolithic snapshot is preserved for downloads/tooling.
    assert (api_dir / "latest.json").exists()
    # Tiny summary headline.
    summary = json.loads((api_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["checks"] > 0
    assert "status_counts" in summary and "modality_counts" in summary

    # Manifest plus a shard file per modality.
    manifest = json.loads((api_dir / "modalities" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["modalities"]
    total_rows = 0
    for modality in manifest["modalities"]:
        shard_path = api_dir / "modalities" / f"{modality['slug']}.json"
        assert shard_path.exists()
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        assert len(shard["rows"]) == modality["rows"]
        total_rows += len(shard["rows"])
    # Full fidelity: shard rows sum to the summary check count.
    assert total_rows == summary["checks"]


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
    assert "<loc>https://azwatch.operator.lat/insights/</loc>" in sitemap_xml
    assert "<loc>https://azwatch.operator.lat/insights/azure-openai-regional-availability.html</loc>" in sitemap_xml
    assert "<loc>https://azwatch.operator.lat/api/latest.json</loc>" in sitemap_xml
    assert "# Azure Regional Feature Availability Monitor" in llms_txt
    assert "api/latest.json" in llms_txt
    assert "insights/" in llms_txt
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
    assert "History and signal changes" in methodology_html
    assert "parked as probe-quality changes" in methodology_html
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

    assert "Recent Availability Signals" in index_html
    assert "unknown transitions are parked" in index_html
    assert "Parked unknown" in index_html
    assert 'href="api/history/changes/2026-05-10.json"' in index_html
    assert "eastus flux unavailable -> available" in index_html
    assert "History baseline starts today" in index_html
    assert (output_dir / "api" / "history" / "recent-changes.json").exists()
    assert (output_dir / "api" / "history" / "changes" / "2026-05-10.json").exists()


def test_build_static_site_writes_blog_from_history_index(tmp_path):
    output_dir = tmp_path / "public"
    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-04T00:00:00Z",
                "regions": {"eastus": {"aks": {"extensions.gitops": {"status": "available"}}}},
            }
        ),
        encoding="utf-8",
    )
    (history_dir / "index.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-04T00:00:00Z",
                "days": [
                    {
                        "date": "2026-07-04",
                        "narrative": "Germany North floods with DCv5\n\nA broad wave of VM SKUs.\n\nNo regressions.",
                        "narrative_source": "ai",
                        "change_type_counts": {"new_availability": 12, "regression": 0},
                        "parked_unknown_changes": 3,
                        "highlights": [
                            {
                                "region": "germanynorth",
                                "feature": "vmSkus.standard.dc16ads.v5",
                                "previous": "unavailable",
                                "current": "available",
                                "change_type": "new_availability",
                            }
                        ],
                    },
                    {
                        "date": "2026-07-03",
                        "narrative": "A quieter day\n\nSmall changes only.",
                        "narrative_source": "ai",
                        "change_type_counts": {"new_availability": 1, "regression": 1},
                        "parked_unknown_changes": 0,
                        "highlights": [],
                    },
                    {"date": "2026-07-02", "narrative": ""},  # no narrative -> not a post
                ],
            }
        ),
        encoding="utf-8",
    )

    build_static_site(
        output_dir,
        snapshot_path=snapshot_path,
        diff_path=tmp_path / "missing-diff.json",
        history_path=history_dir,
    )

    blog_index = (output_dir / "blog" / "index.html").read_text(encoding="utf-8")
    post = (output_dir / "blog" / "2026-07-04.html").read_text(encoding="utf-8")
    feed = (output_dir / "blog" / "feed.xml").read_text(encoding="utf-8")
    sitemap = (output_dir / "sitemap.xml").read_text(encoding="utf-8")
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    # Both narrated days become posts; the empty-narrative day does not.
    assert (output_dir / "blog" / "2026-07-03.html").exists()
    assert not (output_dir / "blog" / "2026-07-02.html").exists()
    assert "Germany North floods with DCv5" in blog_index
    assert "Germany North floods with DCv5" in post
    assert "Engineering context" in post
    assert "germanynorth" in post
    # Sitemap lists the blog index and dated posts.
    assert "<loc>https://azwatch.operator.lat/blog/</loc>" in sitemap
    assert "<loc>https://azwatch.operator.lat/blog/2026-07-04.html</loc>" in sitemap
    # RSS feed has an item per post and the nav/head link the blog.
    assert feed.count("<item>") == 2
    assert 'type="application/rss+xml"' in index_html
    assert 'href="blog/"' in index_html


def test_build_static_site_writes_insight_pages_with_seo_metadata(tmp_path):
    output_dir = tmp_path / "public"

    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )

    insights_index = (output_dir / "insights" / "index.html").read_text(encoding="utf-8")
    openai_page = (output_dir / "insights" / "azure-openai-regional-availability.html").read_text(
        encoding="utf-8"
    )

    assert "Azure Regional Availability Insights" in insights_index
    assert "Azure OpenAI Regional Availability Tracker" in openai_page
    assert '<meta property="og:title" content="Azure OpenAI Regional Availability Tracker">' in openai_page
    assert '<script type="application/ld+json">' in openai_page
    assert "Azure OpenAI regional availability" in openai_page
    assert "does not prove quota" in openai_page


def test_build_static_site_writes_empty_blog_without_history(tmp_path):
    output_dir = tmp_path / "public"
    build_static_site(
        output_dir,
        snapshot_path=Path("data/snapshots/2026-05-08.json"),
        diff_path=tmp_path / "missing-diff.json",
    )
    # Blog index and feed are always written, even with no narrated days.
    blog_index = (output_dir / "blog" / "index.html").read_text(encoding="utf-8")
    assert "No change summaries have been published yet" in blog_index
    assert (output_dir / "blog" / "feed.xml").exists()


def test_build_static_site_renders_metric_trends_from_history(tmp_path):
    output_dir = tmp_path / "public"
    history_dir = tmp_path / "history"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-10T00:00:00Z",
                "regions": {
                    "eastus": {
                        "aks": {
                            "extensions.gitops": {"status": "available"},
                            "extensions.monitor": {"status": "unavailable"},
                        }
                    },
                    "westeurope": {
                        "aks": {
                            "extensions.gitops": {"status": "available"},
                            "extensions.monitor": {"status": "available"},
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (history_dir / "changes").mkdir(parents=True)
    (history_dir / "recent-changes.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-10T00:00:00Z",
                "days": [
                    {
                        "date": "2026-05-10",
                        "change_path": "changes/2026-05-10.json",
                        "total_changes": 2,
                        "change_type_counts": {
                            "new_availability": 2,
                            "regression": 0,
                            "status_change": 0,
                        },
                        "status_counts": {
                            "available": 3,
                            "unavailable": 1,
                            "partial": 0,
                            "unknown": 0,
                        },
                        "summary_counts": {"regions": 2, "features": 2, "checks": 4},
                        "highlights": [],
                    },
                    {
                        "date": "2026-05-09",
                        "change_path": "changes/2026-05-09.json",
                        "total_changes": 1,
                        "change_type_counts": {
                            "new_availability": 1,
                            "regression": 0,
                            "status_change": 0,
                        },
                        "status_counts": {
                            "available": 1,
                            "unavailable": 1,
                            "partial": 0,
                            "unknown": 0,
                        },
                        "summary_counts": {"regions": 2, "features": 1, "checks": 2},
                        "highlights": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (history_dir / "changes" / "2026-05-10.json").write_text("{}", encoding="utf-8")
    (history_dir / "changes" / "2026-05-09.json").write_text("{}", encoding="utf-8")

    build_static_site(
        output_dir,
        snapshot_path=snapshot_path,
        diff_path=tmp_path / "missing-diff.json",
        history_path=history_dir,
    )

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")

    assert "No change for 1 day" in index_html
    assert "Up 1 since previous snapshot" in index_html
    assert "Up 2 since previous snapshot" in index_html
    assert "Up 25.0 pp since previous snapshot" in index_html
    assert "sparkline" in index_html


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
    assert '<details class="panel unknown-diagnostics" aria-label="Unknown diagnostics">' in index_html
    assert "Unknowns To Investigate" in index_html
    assert "1 unknown checks" in index_html
    assert "Unknown checks are parked as" in index_html
    assert "Catalog failed." in index_html
    assert "extensionCatalog" in index_html
    assert index_html.index("Large AKS Extension Groups") < index_html.index("Unknowns To Investigate")
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

    assert "Loading group / region matrices from the per-modality API" in index_html
    assert "regional-availability-root" in index_html
    assert "renderRegionalAvailability" in index_html
    assert "renderAvailabilityCell" in index_html
    assert "regionCountryCode" in index_html
    assert "region-flag-fallback" in index_html
    assert "regionShortLabel" in index_html
    assert "availability-single" in index_html
    assert "Groups by Azure region, rendered from the per-modality API" in index_html
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
    assert "fetch('api/modalities/manifest.json'" in heatmap_html
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
    assert "Loading extension groups from the per-modality API" in index_html
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
