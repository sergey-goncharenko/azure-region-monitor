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
class FunctionRuntimeFeature:
    feature: str
    runtime: str


DEFAULT_FUNCTION_RUNTIME_FEATURES = [
    FunctionRuntimeFeature(feature="runtimes.dotnet-isolated.10", runtime="DOTNET-ISOLATED|10"),
    FunctionRuntimeFeature(feature="runtimes.dotnet-isolated.9", runtime="DOTNET-ISOLATED|9"),
    FunctionRuntimeFeature(feature="runtimes.dotnet-isolated.8", runtime="DOTNET-ISOLATED|8"),
    FunctionRuntimeFeature(feature="runtimes.dotnet-isolated.7", runtime="DOTNET-ISOLATED|7"),
    FunctionRuntimeFeature(feature="runtimes.dotnet-isolated.6", runtime="DOTNET-ISOLATED|6"),
    FunctionRuntimeFeature(feature="runtimes.dotnet.8", runtime="DOTNET|8"),
    FunctionRuntimeFeature(feature="runtimes.dotnet.6", runtime="DOTNET|6"),
    FunctionRuntimeFeature(feature="runtimes.node.24", runtime="NODE|24"),
    FunctionRuntimeFeature(feature="runtimes.node.22", runtime="NODE|22"),
    FunctionRuntimeFeature(feature="runtimes.node.20", runtime="NODE|20"),
    FunctionRuntimeFeature(feature="runtimes.node.18", runtime="NODE|18"),
    FunctionRuntimeFeature(feature="runtimes.python.3.14", runtime="PYTHON|3.14"),
    FunctionRuntimeFeature(feature="runtimes.python.3.13", runtime="PYTHON|3.13"),
    FunctionRuntimeFeature(feature="runtimes.python.3.12", runtime="PYTHON|3.12"),
    FunctionRuntimeFeature(feature="runtimes.python.3.11", runtime="PYTHON|3.11"),
    FunctionRuntimeFeature(feature="runtimes.python.3.10", runtime="PYTHON|3.10"),
    FunctionRuntimeFeature(feature="runtimes.python.3.9", runtime="PYTHON|3.9"),
    FunctionRuntimeFeature(feature="runtimes.python.3.8", runtime="PYTHON|3.8"),
    FunctionRuntimeFeature(feature="runtimes.python.3.7", runtime="PYTHON|3.7"),
    FunctionRuntimeFeature(feature="runtimes.java.25", runtime="JAVA|25"),
    FunctionRuntimeFeature(feature="runtimes.java.21", runtime="JAVA|21"),
    FunctionRuntimeFeature(feature="runtimes.java.17", runtime="JAVA|17"),
    FunctionRuntimeFeature(feature="runtimes.java.11", runtime="JAVA|11"),
    FunctionRuntimeFeature(feature="runtimes.java.8", runtime="JAVA|8"),
    FunctionRuntimeFeature(feature="runtimes.powershell.7.4", runtime="POWERSHELL|7.4"),
    FunctionRuntimeFeature(feature="runtimes.powershell.7.2", runtime="POWERSHELL|7.2"),
]


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

    if raw.strip().lower() in {"*", "all"}:
        return []

    skus = [item.strip() for item in raw.split(",") if item.strip()]
    if not skus:
        raise ValueError("VM SKUs cannot be empty")
    return skus


def parse_function_runtime_features(raw: str | None) -> list[FunctionRuntimeFeature]:
    if not raw:
        return DEFAULT_FUNCTION_RUNTIME_FEATURES

    features: list[FunctionRuntimeFeature] = []
    for item in raw.split(","):
        feature, separator, runtime = item.strip().partition("=")
        if not separator or not feature or not runtime:
            raise ValueError(
                "Function runtime features must use 'feature=runtime' pairs separated by commas"
            )
        features.append(FunctionRuntimeFeature(feature=feature, runtime=runtime))

    return features