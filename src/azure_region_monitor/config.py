from __future__ import annotations

from dataclasses import dataclass

DEFAULT_REGIONS = [
    "eastus",
    "westus2",
    "australiaeast",
    "southeastasia",
    "northeurope",
    "swedencentral",
    "westeurope",
    "uksouth",
    "centralus",
    "southafricanorth",
    "centralindia",
    "eastasia",
    "indonesiacentral",
    "japaneast",
    "japanwest",
    "koreacentral",
    "malaysiawest",
    "newzealandnorth",
    "canadacentral",
    "austriaeast",
    "belgiumcentral",
    "denmarkeast",
    "francecentral",
    "germanywestcentral",
    "italynorth",
    "norwayeast",
    "polandcentral",
    "spaincentral",
    "switzerlandnorth",
    "mexicocentral",
    "uaenorth",
    "brazilsouth",
    "chilecentral",
    "eastus2euap",
    "israelcentral",
    "qatarcentral",
    "eastus2",
    "eastusstg",
    "southcentralus",
    "westus3",
    "northcentralus",
    "westus",
    "jioindiawest",
    "centraluseuap",
    "southcentralusstg",
    "westcentralus",
    "southafricawest",
    "australiacentral",
    "australiacentral2",
    "australiasoutheast",
    "jioindiacentral",
    "koreasouth",
    "southindia",
    "westindia",
    "canadaeast",
    "francesouth",
    "germanynorth",
    "norwaywest",
    "switzerlandwest",
    "uaecentral",
    "brazilsoutheast",
    "ukwest",
]
DEFAULT_AKS_KUBERNETES_VERSION_PREFIXES = ["1.32", "1.33", "1.34", "1.35"]
DEFAULT_VM_SKUS = ["Standard_B2s", "Standard_D2s_v5", "Standard_D2as_v5", "Standard_E2s_v5"]


@dataclass(frozen=True)
class FunctionRuntimeFeature:
    feature: str
    runtime: str


@dataclass(frozen=True)
class ContainerAppsResourceFeature:
    feature: str
    resource_type: str


@dataclass(frozen=True)
class AiModelFeature:
    feature: str
    model: str


@dataclass(frozen=True)
class LatencyModel:
    feature: str
    model: str


@dataclass(frozen=True)
class AiLatencyTarget:
    region: str
    endpoint: str
    deployment: str
    model: str


DEFAULT_LATENCY_MODELS = [
    LatencyModel(feature="modelLatency.openai.gpt-4o-mini", model="openai/gpt-4o-mini"),
    LatencyModel(feature="modelLatency.openai.gpt-4o", model="openai/gpt-4o"),
    LatencyModel(feature="modelLatency.openai.gpt-4.1-mini", model="openai/gpt-4.1-mini"),
    LatencyModel(feature="modelLatency.openai.gpt-4.1", model="openai/gpt-4.1"),
    LatencyModel(feature="modelLatency.openai.o4-mini", model="openai/o4-mini"),
    LatencyModel(feature="modelLatency.openai.gpt-5-mini", model="openai/gpt-5-mini"),
    LatencyModel(feature="modelLatency.openai.gpt-5-nano", model="openai/gpt-5-nano"),
    LatencyModel(feature="modelLatency.microsoft.phi-4", model="microsoft/Phi-4"),
    LatencyModel(
        feature="modelLatency.deepseek.deepseek-v3-0324", model="deepseek/DeepSeek-V3-0324"
    ),
    LatencyModel(
        feature="modelLatency.meta.llama-3.3-70b-instruct", model="meta/Llama-3.3-70B-Instruct"
    ),
]


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

DEFAULT_CONTAINER_APPS_RESOURCE_FEATURES = [
    ContainerAppsResourceFeature(
        feature="containerApps.managedEnvironments",
        resource_type="managedEnvironments",
    ),
    ContainerAppsResourceFeature(
        feature="containerApps.apps",
        resource_type="containerApps",
    ),
    ContainerAppsResourceFeature(
        feature="containerApps.jobs",
        resource_type="jobs",
    ),
    ContainerAppsResourceFeature(
        feature="containerApps.daprComponents",
        resource_type="managedEnvironments/daprComponents",
    ),
    ContainerAppsResourceFeature(
        feature="containerApps.connectedEnvironments",
        resource_type="connectedEnvironments",
    ),
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


def parse_container_apps_resource_features(raw: str | None) -> list[ContainerAppsResourceFeature]:
    if not raw:
        return DEFAULT_CONTAINER_APPS_RESOURCE_FEATURES

    features: list[ContainerAppsResourceFeature] = []
    for item in raw.split(","):
        feature, separator, resource_type = item.strip().partition("=")
        if not separator or not feature or not resource_type:
            raise ValueError(
                "Container Apps resource features must use "
                "'feature=resourceType' pairs separated by commas"
            )
        features.append(ContainerAppsResourceFeature(feature=feature, resource_type=resource_type))

    return features


def parse_ai_model_features(raw: str | None) -> list[AiModelFeature]:
    if not raw or raw.strip().lower() in {"*", "all"}:
        return []

    features: list[AiModelFeature] = []
    for item in raw.split(","):
        feature, separator, model = item.strip().partition("=")
        if not separator or not feature or not model:
            raise ValueError(
                "AI model features must use 'feature=model[@version]' pairs separated by commas"
            )
        features.append(AiModelFeature(feature=feature, model=model))

    return features


def parse_latency_models(raw: str | None) -> list[LatencyModel]:
    if not raw:
        return DEFAULT_LATENCY_MODELS

    models: list[LatencyModel] = []
    for item in raw.split(","):
        feature, separator, model = item.strip().partition("=")
        if not separator or not feature or not model:
            raise ValueError(
                "Latency models must use 'feature=model' pairs separated by commas"
            )
        models.append(LatencyModel(feature=feature, model=model))

    return models


def parse_ai_latency_targets(raw: str | None) -> list[AiLatencyTarget]:
    """Parse Azure regional latency targets from the infra JSON output.

    Expects a JSON array of objects with region, endpoint, deployment, and model,
    matching the `targets` output of the regional-latency Bicep template.
    """

    if not raw or not raw.strip():
        return []

    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"AI latency targets must be valid JSON: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("AI latency targets JSON must be an array of target objects")

    targets: list[AiLatencyTarget] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each AI latency target must be a JSON object")
        region = str(item.get("region", "")).strip()
        endpoint = str(item.get("endpoint", "")).strip()
        deployment = str(item.get("deployment", "")).strip()
        model = str(item.get("model", "")).strip() or deployment
        if not region or not endpoint or not deployment:
            raise ValueError("AI latency targets require region, endpoint, and deployment")
        targets.append(
            AiLatencyTarget(
                region=region, endpoint=endpoint, deployment=deployment, model=model
            )
        )
    return targets