from __future__ import annotations

from azure_region_monitor.models import Snapshot
from azure_region_monitor.retired_modalities import RETIRED_MODALITIES


def merge_snapshot_overlay(base: Snapshot, overlay: Snapshot) -> Snapshot:
    merged = base.model_copy(deep=True)

    for region, overlay_services in overlay.regions.items():
        merged_services = merged.regions.setdefault(region, {})
        for service, overlay_features in overlay_services.items():
            overlay_categories = {_feature_category(feature) for feature in overlay_features}
            merged_features = merged_services.setdefault(service, {})

            for feature in list(merged_features):
                if _feature_category(feature) in overlay_categories:
                    del merged_features[feature]

            merged_features.update(overlay_features)

    merged.timestamp = overlay.timestamp
    prune_retired_modalities(merged)
    return merged


def prune_retired_modalities(snapshot: Snapshot) -> Snapshot:
    for region in list(snapshot.regions):
        services = snapshot.regions[region]
        for service in list(services):
            features = services[service]
            for feature in list(features):
                if _feature_category(feature) in RETIRED_MODALITIES:
                    del features[feature]
            if not features:
                del services[service]
        if not services:
            del snapshot.regions[region]
    return snapshot


def _feature_category(feature: str) -> str:
    if feature == "extensionCatalog":
        return "aksExtensions"
    if feature.startswith("extensions.") or feature.startswith("extensionTypes."):
        return "aksExtensions"
    if feature.startswith("kubernetesVersions."):
        return "aksKubernetesVersions"
    if feature.startswith("hostingPlans.") or feature.startswith("runtimes."):
        return "functions"
    if feature.startswith("aiModels."):
        return "aiModels"
    if feature.startswith("modelLatency."):
        return "modelLatency"
    if feature.startswith("aiLatency."):
        return "aiLatency"
    if feature.startswith("containerApps."):
        return "containerApps"
    if feature == "vmSkuCatalog" or feature.startswith("vmSkus."):
        return "vmSkus"
    return feature.split(".", 1)[0]