import json

import pytest

from azure_region_monitor.briefing import (
    BRIEFING_KINDS, build_briefing, compact_briefing, enrich_briefing_features,
)
from azure_region_monitor.display import plain_feature_name
from azure_region_monitor.models import Snapshot
from azure_region_monitor.summary import ChangeContext


def snapshot(date, regions):
    return Snapshot.model_validate({"timestamp": f"{date}T00:00:00Z", "regions": regions})


def vm_snapshot(date, status, *, extra=None):
    features = {
        "vmSkus.standard.base": {"status": "available"},
        "vmSkus.standard.target": {"status": status},
        **(extra or {}),
    }
    return snapshot(date, {"eastus": {"compute": features}})


@pytest.mark.parametrize("prefix", ["modelLatency.", "aiLatency."])
def test_measurement_coverage_changes_are_not_catalog_rollouts_or_delistings(prefix):
    before = snapshot("2026-09-05", {"eastus": {"ai": {
        prefix + "base": {"status": "available"},
        prefix + "old": {"status": "available"},
    }}})
    after = snapshot("2026-09-06", {"eastus": {"ai": {
        prefix + "base": {"status": "available"},
        prefix + "new": {"status": "available"},
    }}})
    briefing = build_briefing(after, before)
    assert briefing["counts"]["other_changes"] == 2
    assert briefing["counts"]["new_listings"] == briefing["counts"]["delistings"] == 0
    tomorrow = snapshot("2026-09-07", after.model_dump()["regions"])
    continued = build_briefing(tomorrow, after, prior_day={"briefing": briefing})
    assert continued["counts"]["continuing_absences"] == 0


def test_all_54_sizes_and_266_size_region_additions_are_retained():
    regions = ["eastus", "westus3", "westeurope", "japaneast", "australiaeast"]
    before = {
        region: {
            "compute": {"vmSkus.standard.base": {"status": "available"}},
            "aks": {"extensionCatalog": {"status": "available"}},
        }
        for region in regions
    }
    after = json.loads(json.dumps(before))
    for size in range(54):
        for region in regions[:5 if size < 50 else 4]:
            after[region]["compute"][f"vmSkus.standard.d{size}.v5"] = {"status": "available"}
    after["eastus"]["aks"]["extensionTypes.microsoft.flux"] = {"status": "available"}

    briefing = build_briefing(snapshot("2026-05-10", after), snapshot("2026-05-09", before))

    assert len(briefing["records"]) == 267
    assert briefing["counts"]["new_listings"] == 267
    assert briefing["counts"]["scope_changes"] == 0
    assert briefing["scope"]["added_checks"] == 267
    sizes = next(group for group in briefing["groups"] if group["modality"] == "VM SKUs")
    assert sizes["feature_count"] == 54
    assert sizes["listing_count"] == 266
    assert sizes["region_counts"]["australiaeast"] == 50
    assert sizes["region_counts"]["eastus"] == 54
    assert sizes["region_feature_counts"] == sizes["region_counts"]
    assert sum(sizes["region_counts"].values()) == sizes["listing_count"]
    assert set(sizes) == {
        "kind", "modality", "feature_count", "listing_count", "regions", "region_counts",
        "region_feature_counts", "examples",
    }
    assert len(sizes["examples"]) == 1
    example = sizes["examples"][0]
    assert example["label"] == plain_feature_name(example["feature"])
    assert example["coverage_before"]["available"] == 0
    assert example["coverage_after"]["available"] == 5
    assert example["coverage_after"]["total_regions"] == 5
    assert {key: value for key, value in example.items() if key != "feature_context"} in briefing["records"]
    assert example["feature_context"] == briefing["feature_contexts"][example["feature"]]
    assert example["evidence_after"]["status"] == "available"
    assert len({
        (record["region"], record["service"], record["feature"])
        for record in briefing["records"]
    }) == 267
    assert "records" not in compact_briefing(briefing)
    assert "feature_contexts" not in compact_briefing(briefing)
    assert len(briefing["records"]) == 267
    json.dumps(briefing)


def test_enrichment_refreshes_documentation_without_changing_records_classification():
    before = vm_snapshot("2026-09-05", "unavailable")
    after = vm_snapshot("2026-09-06", "available")
    briefing = build_briefing(after, before)
    original_records = json.loads(json.dumps(briefing["records"]))
    briefing["feature_contexts"]["vmSkus.standard.target"]["summary"] = "Obsolete context."
    refreshed = enrich_briefing_features(briefing)
    assert refreshed["records"] == original_records
    assert refreshed["counts"] == briefing["counts"]
    assert refreshed["feature_contexts"]["vmSkus.standard.target"]["summary"] != "Obsolete context."
    assert briefing["feature_contexts"]["vmSkus.standard.target"]["summary"] == "Obsolete context."


def test_first_observation_states_its_history_bound_and_always_has_a_read_more_link():
    before = vm_snapshot("2026-09-05", "unavailable")
    after = vm_snapshot("2026-09-06", "available")
    limited = build_briefing(after, before)
    assert "First observed in this comparison" in limited["records"][0]["novelty"]
    key = ("eastus", "compute", "vmSkus.standard.target")
    contextual = build_briefing(after, before, contexts={
        key: ChangeContext(classification="net_new_availability", expansion_kind="new_feature"),
    })
    assert "First observed in retained monitoring history" in contextual["records"][0]["novelty"]
    assert "not a confirmed product launch" in contextual["records"][0]["novelty"]
    context = contextual["feature_contexts"]["vmSkus.standard.target"]
    assert context["specificity"] == "unverified"
    assert context["sources"][0]["url"].startswith("https://learn.microsoft.com/")


def test_missing_baseline_does_not_invent_additions_but_reports_gaps():
    current = vm_snapshot("2026-05-10", "unknown")
    briefing = build_briefing(current, None)

    assert briefing["baseline_available"] is False
    assert briefing["previous_timestamp"] is None
    assert briefing["comparison_days"] is None
    assert briefing["scope"]["added_regions"] == []
    assert briefing["scope"]["added_checks"] == 0
    assert briefing["scope"]["previous_regions"] is None
    assert briefing["scope"]["previous_checks"] is None
    assert briefing["counts"] == {
        **dict.fromkeys(BRIEFING_KINDS, 0),
        "observation_gaps": 1,
    }
    assert briefing["records"][0]["coverage_before"] is None
    assert briefing["records"][0]["evidence_before"] is None
    assert briefing["tracking"]["complete"] is False


def test_comparison_uses_actual_utc_calendar_dates_not_assumed_yesterday():
    before = vm_snapshot("2026-05-06", "unavailable")
    current = vm_snapshot("2026-05-10", "available")
    current.timestamp = current.timestamp.replace(hour=23)
    briefing = build_briefing(current, before)
    assert briefing["comparison_days"] == 4
    assert briefing["previous_timestamp"] == "2026-05-06T00:00:00+00:00"
    assert briefing["current_timestamp"] == "2026-05-10T23:00:00+00:00"


def test_unknown_only_day_includes_unchanged_gaps_and_preserves_probe_detail():
    previous = vm_snapshot("2026-05-09", "unknown")
    current = vm_snapshot("2026-05-10", "unknown")
    current.regions["eastus"]["compute"]["vmSkus.standard.target"].message = "Catalog timed out"
    current.regions["eastus"]["compute"]["vmSkus.standard.target"].error_code = "TIMEOUT"

    briefing = build_briefing(current, previous)
    assert briefing["counts"]["observation_gaps"] == 1
    assert sum(briefing["counts"].values()) == 1
    record = briefing["records"][0]
    assert record["previous"] == record["current"] == "unknown"
    assert record["evidence_after"] == {
        "source": "snapshot",
        "timestamp": "2026-05-10T00:00:00+00:00",
        "status": "unknown",
        "detail": "Catalog timed out",
        "error_code": "TIMEOUT",
        "latency_ms": None,
    }
    assert record["coverage_after"]["unknown"] == 1
    assert record["coverage_after"]["available"] == 0


@pytest.mark.parametrize("service,prefix,catalog,modality", [
    ("compute", "vmSkus.", "vmSkuCatalog", "VM SKUs"),
    ("aks", "extensionTypes.", "extensionCatalog", "AKS extensions"),
    ("ai", "aiModels.", "aiModelCatalog", "Azure AI models"),
])
def test_dynamic_catalog_failures_cannot_create_delistings_or_new_rollouts(
    service, prefix, catalog, modality
):
    healthy = snapshot("2026-05-07", {
        "eastus": {service: {
            f"{prefix}a": {"status": "available"},
            f"{prefix}b": {"status": "available"},
        }},
    })
    failed = snapshot("2026-05-08", {
        "eastus": {service: {
            catalog: {"status": "unknown", "error_code": "TIMEOUT", "message": "Catalog failed"},
        }},
    })
    still_failed = snapshot("2026-05-09", failed.model_dump()["regions"])
    recovered = snapshot("2026-05-10", healthy.model_dump()["regions"])
    gap = build_briefing(failed, healthy)
    continuing_gap = build_briefing(still_failed, failed, prior_day=gap)
    recovery = build_briefing(recovered, still_failed, prior_day=continuing_gap)

    assert gap["counts"]["delistings"] == gap["counts"]["scope_changes"] == 0
    assert gap["counts"]["observation_gaps"] == 3
    assert continuing_gap["counts"]["observation_gaps"] == 3
    record = next(record for record in gap["records"] if record["feature"] == f"{prefix}a")
    assert record["current"] is None
    assert record["evidence_after"]["status"] == "unknown"
    assert record["evidence_after"]["feature"] == catalog
    assert record["evidence_after"]["error_code"] == "TIMEOUT"
    assert record["modality"] == modality
    assert record["absence_since"] is None
    assert recovery["counts"]["new_listings"] == recovery["counts"]["restorations"] == 0
    assert recovery["counts"]["scope_changes"] == 0
    assert recovery["counts"]["observation_recoveries"] == 3


@pytest.mark.parametrize("status", ["available", "unavailable", "partial"])
def test_unknown_to_known_is_observation_recovery_not_a_rollout(status):
    previous = vm_snapshot("2026-05-09", "unknown")
    current = vm_snapshot("2026-05-10", status)
    context = ChangeContext(
        classification="restored_availability", available_days=1, last_available_date="2026-05-08"
    )
    briefing = build_briefing(
        current, previous, contexts={("eastus", "compute", "vmSkus.standard.target"): context}
    )
    assert briefing["counts"]["observation_recoveries"] == 1
    assert briefing["counts"]["new_listings"] == briefing["counts"]["restorations"] == 0
    assert briefing["records"][0]["previous"] == "unknown"
    assert briefing["records"][0]["current"] == status


def test_scope_changes_do_not_become_rollouts_or_delistings():
    previous = snapshot("2026-05-09", {
        "eastus": {
            "compute": {
                "vmSkus.standard.base": {"status": "available"},
                "vmSkus.standard.old": {"status": "available"},
            },
            "ai": {"aiModels.openai.old": {"status": "available"}},
        },
        "westus": {"compute": {"vmSkus.standard.base": {"status": "available"}}},
    })
    current = snapshot("2026-05-10", {
        "eastus": {
            "compute": {
                "vmSkus.standard.base": {"status": "available"},
                "vmSkus.standard.new": {"status": "available"},
            },
            "aks": {"kubernetesVersions.1.33": {"status": "available"}},
        },
        "northcentralus": {"compute": {"vmSkus.standard.base": {"status": "available"}}},
    })
    briefing = build_briefing(current, previous)
    assert briefing["scope"]["added_regions"] == ["northcentralus"]
    assert briefing["scope"]["removed_regions"] == ["westus"]
    assert briefing["scope"]["added_checks"] == 3
    assert briefing["scope"]["removed_checks"] == 3
    assert briefing["counts"]["scope_changes"] == 4
    assert briefing["counts"]["new_listings"] == 1
    assert briefing["counts"]["delistings"] == 1
    removed = next(
        record for record in briefing["records"] if record["feature"] == "vmSkus.standard.old"
    )
    assert removed["current"] is None
    assert removed["kind"] == "delistings"
    assert removed["coverage_after"]["observed"] == 0
    assert all(record["kind"] != "deprecation" for record in briefing["records"])
    assert "retirement" not in str(removed.get("novelty"))


def test_new_unknown_region_is_one_gap_with_scope_context():
    previous = snapshot("2026-05-09", {})
    current = vm_snapshot("2026-05-10", "unknown")
    briefing = build_briefing(current, previous)
    gap = next(record for record in briefing["records"] if record["current"] == "unknown")
    assert gap["kind"] == "observation_gaps"
    assert gap["scope_reason"] == "region_added"
    assert briefing["counts"]["observation_gaps"] == 1
    assert briefing["counts"]["scope_changes"] == 1
    assert len(briefing["records"]) == 2


def test_removed_scope_is_not_repeated_as_a_phantom_addition_next_day():
    day1 = vm_snapshot("2026-05-08", "available")
    day2 = snapshot("2026-05-09", {})
    day3 = snapshot("2026-05-10", {})
    prior = build_briefing(day2, day1)
    assert prior["counts"]["scope_changes"] == 2
    assert build_briefing(day3, day2, prior_day=prior)["records"] == []


def test_region_filter_scope_includes_unchanged_regions():
    current = vm_snapshot("2026-05-10", "available")
    previous = vm_snapshot("2026-05-09", "available")
    briefing = build_briefing(current, previous)
    assert briefing["records"] == []
    assert briefing["regions"] == ["eastus"]
    assert briefing["modalities"] == ["VM SKUs"]


def test_changing_service_scope_does_not_invent_a_rollout():
    previous = vm_snapshot("2026-05-09", "available")
    current = snapshot("2026-05-10", {"eastus": {
        "another-probe": {"vmSkus.standard.base": {"status": "available"}},
    }})
    briefing = build_briefing(current, previous)
    assert briefing["counts"]["scope_changes"] == 3
    assert briefing["counts"]["new_listings"] == briefing["counts"]["delistings"] == 0


def test_before_after_coverage_uses_each_snapshots_denominator():
    previous = vm_snapshot("2026-05-09", "available")
    current = vm_snapshot("2026-05-10", "unavailable")
    current.regions["westus3"] = {
        "compute": {"vmSkus.standard.base": current.regions["eastus"]["compute"]["vmSkus.standard.base"]}
    }
    briefing = build_briefing(current, previous)
    record = next(record for record in briefing["records"] if record["kind"] == "delistings")
    assert record["coverage_before"] == {
        "available": 1, "unavailable": 0, "partial": 0, "unknown": 0,
        "observed": 1, "total_regions": 1,
    }
    assert record["coverage_after"] == {
        "available": 0, "unavailable": 1, "partial": 0, "unknown": 0,
        "observed": 1, "total_regions": 2,
    }


def test_tracked_delisting_continues_and_restores_without_counting_old_absences():
    extra = {"vmSkus.standard.longstanding": {"status": "unavailable"}}
    day1 = vm_snapshot("2026-05-07", "available", extra=extra)
    day2 = vm_snapshot("2026-05-08", "unavailable", extra=extra)
    day3 = vm_snapshot("2026-05-09", "unavailable", extra=extra)
    day4 = vm_snapshot("2026-05-10", "available", extra=extra)

    disappearance = build_briefing(day2, day1)
    continuing = build_briefing(day3, day2, prior_day={"briefing": disappearance})
    restoration = build_briefing(day4, day3, prior_day=continuing)

    assert disappearance["counts"]["delistings"] == 1
    assert continuing["counts"]["continuing_absences"] == 1
    assert continuing["counts"]["delistings"] == 0
    assert continuing["tracking"]["since"] == "2026-05-07"
    assert continuing["tracking"]["complete"] is False
    assert continuing["records"][0]["absence_since"] == "2026-05-08"
    assert continuing["records"][0]["last_available_date"] == "2026-05-07"
    assert continuing["records"][0]["previous"] == continuing["records"][0]["current"] == "unavailable"
    assert restoration["counts"]["restorations"] == 1
    assert restoration["counts"]["new_listings"] == 0
    assert restoration["records"][0]["absence_since"] is None
    assert len(continuing["records"]) == len(restoration["records"]) == 1


def test_globally_absent_key_remains_tracked_without_inventing_deprecation():
    before = vm_snapshot("2026-05-07", "available")
    disappeared = snapshot("2026-05-08", {
        "eastus": {"compute": {"vmSkus.standard.base": {"status": "available"}}}
    })
    next_day = snapshot("2026-05-09", disappeared.model_dump()["regions"])
    prior = build_briefing(disappeared, before)
    briefing = build_briefing(next_day, disappeared, prior_day=prior)
    assert briefing["counts"]["continuing_absences"] == 1
    record = briefing["records"][0]
    assert record["previous"] is record["current"] is None
    assert record["coverage_after"]["available"] == 0
    assert "deprecat" not in json.dumps(briefing).lower()


def test_untracked_and_stale_unavailable_cells_are_not_continuing_absences():
    day1 = vm_snapshot("2026-05-07", "available")
    day2 = vm_snapshot("2026-05-08", "unavailable")
    day3 = vm_snapshot("2026-05-09", "unavailable")
    day4 = vm_snapshot("2026-05-10", "unavailable")
    stale = build_briefing(day2, day1)
    assert build_briefing(day4, day3)["records"] == []
    assert build_briefing(day4, day3, prior_day=stale)["records"] == []


@pytest.mark.parametrize("available_days,expected", [(0, "new_listings"), (1, "restorations")])
def test_restoration_requires_observed_history_not_only_a_classification(available_days, expected):
    previous = vm_snapshot("2026-05-09", "unavailable")
    current = vm_snapshot("2026-05-10", "available")
    context = ChangeContext(classification="restored_availability", available_days=available_days)
    briefing = build_briefing(
        current, previous, contexts={("eastus", "compute", "vmSkus.standard.target"): context}
    )
    assert briefing["records"][0]["kind"] == expected
    assert "First observed in retained monitoring history" not in str(briefing["records"][0].get("novelty"))
    if expected == "restorations":
        assert briefing["records"][0].get("novelty") is None


def test_gap_between_absence_observations_preserves_tracking_not_rollout_claims():
    day1 = vm_snapshot("2026-05-06", "available")
    day2 = vm_snapshot("2026-05-07", "unavailable")
    day3 = vm_snapshot("2026-05-08", "unknown")
    day4 = vm_snapshot("2026-05-09", "unavailable")
    day5 = vm_snapshot("2026-05-10", "unavailable")
    prior = build_briefing(day2, day1)
    gap = build_briefing(day3, day2, prior_day=prior)
    recovery = build_briefing(day4, day3, prior_day=gap)
    continuing = build_briefing(day5, day4, prior_day=recovery)
    assert gap["counts"]["observation_gaps"] == 1
    assert recovery["counts"]["observation_recoveries"] == 1
    assert continuing["counts"]["continuing_absences"] == 1
    assert continuing["records"][0]["absence_since"] == "2026-05-07"


def test_partial_change_is_other_change():
    briefing = build_briefing(
        vm_snapshot("2026-05-10", "partial"), vm_snapshot("2026-05-09", "available")
    )
    assert briefing["counts"]["other_changes"] == 1


@pytest.mark.parametrize("feature,modality", [
    ("extensionTypes.microsoft.flux", "AKS extensions"),
    ("kubernetesVersions.1.33", "AKS Kubernetes versions"),
    ("hostingPlans.flexConsumption", "Azure Functions"),
    ("runtimes.python.3.13", "Azure Functions"),
    ("aiModels.openai.gpt", "Azure AI models"),
    ("containerApps.jobs", "Container Apps"),
    ("vmSkus.standard.d2.v5", "VM SKUs"),
])
def test_categories_and_details_reuse_existing_helpers(feature, modality):
    previous = snapshot("2026-05-09", {"eastus": {"service": {feature: {"status": "unavailable"}}}})
    current = snapshot("2026-05-10", {"eastus": {"service": {feature: {"status": "available"}}}})
    record = build_briefing(current, previous)["records"][0]
    assert record["label"] == plain_feature_name(feature)
    assert record["modality"] == modality
    assert record["details_url"].startswith("https://learn.microsoft.com/")
    assert record["feature_note"]
