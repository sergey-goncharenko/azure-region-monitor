from __future__ import annotations

from dataclasses import dataclass

DEFAULT_REGIONS = [
    "eastus",
    "eastus2",
    "westus3",
    "westeurope",
    "northeurope",
    "swedencentral",
    "uksouth",
    "germanywestcentral",
    "southeastasia",
    "australiaeast",
]
DEFAULT_AKS_KUBERNETES_VERSION_PREFIXES = ["1.32", "1.33", "1.34", "1.35"]
DEFAULT_VM_SKUS = ["Standard_B2s", "Standard_D2s_v5", "Standard_D2as_v5", "Standard_E2s_v5"]


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


def parse_vm_skus(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_VM_SKUS

    skus = [item.strip() for item in raw.split(",") if item.strip()]
    if not skus:
        raise ValueError("VM SKUs cannot be empty")
    return skus