from __future__ import annotations

from dataclasses import dataclass

DEFAULT_REGIONS = ["westeurope", "swedencentral", "eastus"]
DEFAULT_AKS_KUBERNETES_VERSION_PREFIXES = ["1.32", "1.33", "1.34", "1.35"]


@dataclass(frozen=True)
class AksExtensionFeature:
    feature: str
    extension_type: str


DEFAULT_AKS_EXTENSION_FEATURES = [
    AksExtensionFeature(feature="extensions.gitops", extension_type="microsoft.flux"),
    AksExtensionFeature(
        feature="extensions.monitor",
        extension_type="microsoft.azuremonitor.containers",
    ),
]


def parse_aks_extension_features(raw: str | None) -> list[AksExtensionFeature]:
    if not raw:
        return DEFAULT_AKS_EXTENSION_FEATURES

    features: list[AksExtensionFeature] = []
    for item in raw.split(","):
        feature, separator, extension_type = item.strip().partition("=")
        if not separator or not feature or not extension_type:
            raise ValueError(
                "AKS extension features must use 'feature=extensionType' pairs separated by commas"
            )
        features.append(AksExtensionFeature(feature=feature, extension_type=extension_type))

    return features


def parse_aks_kubernetes_version_prefixes(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_AKS_KUBERNETES_VERSION_PREFIXES

    prefixes = [item.strip() for item in raw.split(",") if item.strip()]
    if not prefixes:
        raise ValueError("AKS Kubernetes version prefixes cannot be empty")
    return prefixes