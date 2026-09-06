"""Offline, source-backed capability context, not probe results or launch dates.

Only the documented SKU size sets and model versions below qualify as exact.
``verified_on`` dates the checked documentation, not a regional observation.
Category/family descriptions do not verify the capability of an unknown variant.
No documentation is fetched while importing or calling this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from azure_region_monitor.display import display_model_name, plain_feature_name

_VERIFIED_ON = "2026-09-06"
_LEARN = "https://learn.microsoft.com/en-us/"
_VM_BASE = _LEARN + "azure/virtual-machines/"
_FUNCTIONS_BASE = _LEARN + "azure/azure-functions/"
_FLEX = _FUNCTIONS_BASE + "flex-consumption-plan"
_EXTENSIONS = _LEARN + "azure/aks/cluster-extensions"
_POLICY = _LEARN + "azure/governance/policy/concepts/policy-for-kubernetes"
_MODELS = _LEARN + "azure/foundry/foundry-models/concepts/models-sold-directly-by-azure"
_PARTNER_MODELS = _LEARN + "azure/foundry/foundry-models/concepts/models-from-partners"
_CLAUDE = "https://platform.claude.com/docs/en/models/overview"
_GITHUB_MODELS = "https://docs.github.com/en/github-models"
_VM_LIMIT = (
    "A regional SKU listing does not establish quota, capacity, price, successful deployment, "
    "or measured performance. Temporary disks are not durable application storage."
)
_EXTENSION_LIMIT = (
    "Extension-type catalog evidence is not installation, configuration, cluster compatibility, "
    "or successful execution evidence."
)
_FUNCTION_LIMIT = (
    "Runtime rows combine a Linux runtime listing with the Flex Consumption location signal. "
    "A catalog entry is not a deployment test or proof of current language support; "
    "an absent Flex location is not evidence of quota exhaustion."
)
_CONTAINER_LIMIT = (
    "Only the Microsoft.App resource type's advertised locations are checked. This is not "
    "quota, capacity, deployment, or Dapr runtime execution evidence."
)
_MODEL_LIMIT = (
    "Regional model-catalog evidence does not establish quota, account approval, deployment "
    "type, inference access, content filtering, performance, or data residency."
)


def _source(label: str, url: str) -> dict[str, str]:
    return {"label": label, "url": url}


def _search(feature: str) -> dict[str, str]:
    return _source(
        "Search Microsoft Learn for this exact identifier (not verified)",
        _LEARN + "search/?" + urlencode({"terms": feature}),
    )


def _description(
    title: str,
    summary: str,
    differentiators: tuple[str, ...],
    use_cases: str,
    sources: tuple[dict[str, str], ...],
    limitations: str,
    specificity: str = "exact",
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "differentiators": list(differentiators),
        "use_cases": use_cases,
        "sources": [dict(source) for source in sources],
        "specificity": specificity,
        "verified_on": "" if specificity == "unverified" else _VERIFIED_ON,
        "limitations": limitations,
    }


@dataclass(frozen=True)
class _VmSeries:
    name: str
    ram_per_cpu: int
    sizes: tuple[int, ...]
    local_disk: bool
    processor: str
    purpose: str
    page: str
    ram_overrides: tuple[tuple[int, int], ...] = ()


# All six v6 Basics tables list precisely these sizes, including 2 and 128.
_V6_SIZES = (2, 4, 8, 16, 32, 48, 64, 96, 128)
_V5_SIZES = (2, 4, 8, 16, 32, 48, 64, 96)
_VM_SERIES = {
    ("d", "ns", "6"): _VmSeries(
        "Dnsv6", 4, _V6_SIZES, False, "Intel Xeon Platinum 8573C",
        "general-purpose", "memory-optimized/dnsv6-series",
    ),
    ("d", "nds", "6"): _VmSeries(
        "Dndsv6", 4, _V6_SIZES, True, "Intel Xeon Platinum 8573C",
        "general-purpose", "memory-optimized/dndsv6-series",
    ),
    ("d", "nls", "6"): _VmSeries(
        "Dnlsv6", 2, _V6_SIZES, False, "Intel Xeon Platinum 8573C",
        "low-memory general-purpose", "memory-optimized/dnlsv6-series",
    ),
    ("d", "nlds", "6"): _VmSeries(
        "Dnldsv6", 2, _V6_SIZES, True, "Intel Xeon Platinum 8573C",
        "low-memory general-purpose", "memory-optimized/dnldsv6-series",
    ),
    ("e", "ns", "6"): _VmSeries(
        "Ensv6", 8, _V6_SIZES, False, "Intel Xeon Platinum 8573C",
        "memory-optimized", "memory-optimized/ensv6-series",
    ),
    ("e", "nds", "6"): _VmSeries(
        "Endsv6", 8, _V6_SIZES, True, "Intel Xeon Platinum 8573C",
        "memory-optimized", "memory-optimized/endsv6-series",
    ),
    ("d", "s", "5"): _VmSeries(
        "Dsv5", 4, _V5_SIZES, False, "Intel Xeon Platinum",
        "general-purpose", "general-purpose/dsv5-series",
    ),
    ("d", "as", "5"): _VmSeries(
        "Dasv5", 4, _V5_SIZES, False, "AMD EPYC",
        "general-purpose", "general-purpose/dasv5-series",
    ),
    ("e", "s", "5"): _VmSeries(
        "Esv5", 8, (2, 4, 8, 16, 20, 32, 48, 64, 96), False, "Intel Xeon Platinum",
        "memory-optimized", "memory-optimized/esv5-series", ((96, 672),),
    ),
}


def _vm_context(feature: str) -> dict[str, Any]:
    slug = feature.removeprefix("vmSkus.").lower().replace("_", ".")
    if slug == "standard.b2s":
        return _description(
            "Standard_B2s - burstable VM",
            "A previous-generation B-series VM for workloads with intermittent CPU demand.",
            (
                "2 vCPUs and 4 GiB RAM, as listed in the Bv1 size table.",
                "CPU credits accumulate below baseline and enable bursts above baseline.",
                "Includes 8 GiB of local temporary storage.",
            ),
            "Consider for development or lightly loaded services with occasional CPU bursts; "
            "evaluate sustained CPU demand before choosing a credit-based size.",
            (_source("Bv1 series specifications", _VM_BASE + "sizes/general-purpose/bv1-series"),),
            _VM_LIMIT,
        )
    match = re.fullmatch(r"standard\.([de])([1-9][0-9]{0,2})([a-z]+)\.v([1-9][0-9]*)", slug)
    series = None
    if match:
        family, cpu_text, suffix, generation = match.groups()
        series = _VM_SERIES.get((family, suffix, generation))
        if series and int(cpu_text) in series.sizes:
            cpu = int(cpu_text)
            ram = dict(series.ram_overrides).get(cpu, cpu * series.ram_per_cpu)
            ratio = ram / cpu
            sku = f"Standard_{family.upper()}{cpu}{suffix}_v{generation}"
            network = "network-optimized " if "n" in suffix else ""
            memory = (
                "Low-memory (l): 2 GiB per vCPU rather than the 4 GiB in Dnsv6/Dndsv6."
                if "l" in suffix else
                f"{series.purpose.capitalize()} configuration with {ratio:g} GiB per vCPU."
            )
            disk = (
                "Local temporary disks (d) provide scratch space; keep durable data elsewhere."
                if series.local_disk else
                "No local temporary disk; use remote managed disks for persistent storage."
            )
            networking = (
                "Network-optimized (n): accelerated connection setup and higher bandwidth per "
                "vCPU; Premium SSD-compatible (s)."
                if "n" in suffix else "Premium SSD-compatible (s); managed disks are billed separately."
            )
            workload = (
                "memory-intensive databases and caches" if family == "e" else
                "network-facing services with modest memory needs" if "l" in suffix else
                "application servers and network-facing services"
            )
            return _description(
                f"{sku} - {network}{series.purpose} VM",
                f"{series.name} is a {network}{series.purpose} VM series using "
                f"{series.processor} processors.",
                (f"{cpu} vCPUs and {ram} GiB RAM, from the documented size table.",
                 memory, disk, networking),
                f"Evaluate for {workload}; benchmark your workload and confirm storage, "
                "network, and regional provisioning requirements.",
                (
                    _source(f"{series.name} series specifications", _VM_BASE + "sizes/" + series.page),
                    _source("VM size suffix meanings", _VM_BASE + "vm-naming-conventions"),
                ),
                _VM_LIMIT,
            )
    sources = [_search(feature), _source("Azure VM sizes", _VM_BASE + "sizes/overview")]
    facts = (
        "This signal represents a name in the regional VM size catalog, not a running VM.",
        "Exact CPU, memory, disk, and network specifications are not verified for this identifier.",
    )
    if series:
        sources.insert(0, _source(f"{series.name} family", _VM_BASE + "sizes/" + series.page))
        facts = (
            f"The name resembles {series.name}, but this size is not in its checked size table.",
            "No CPU or RAM specification is inferred for an undocumented size.",
        )
    return _description(
        plain_feature_name(feature), "VM catalog entry with unverified exact specifications.",
        facts, "Use the identifier to look up an exact size before sizing or deploying a workload.",
        tuple(sources), "Exact SKU specifications have not been verified. " + _VM_LIMIT,
        "unverified",
    )


# Exact extension identities are documented in the linked pages. Azure Policy's
# documented extension type is microsoft.policyinsights, not microsoft.azurepolicy.
_EXTENSION_PROFILES = {
    "microsoft.flux": (
        "Flux GitOps",
        "Reconciles Kubernetes configuration and application deployments from declared sources.",
        ("Uses Git as a source of truth and reconciles the cluster toward the desired state.",
         "Supports Helm sources and Kustomize-based configurations."),
        "Consider for declarative Kubernetes deployment and drift reconciliation.",
        "azure/azure-arc/kubernetes/tutorial-use-gitops-flux2",
    ),
    "microsoft.azuremonitor.containers": (
        "Azure Monitor Container insights",
        "Connects Kubernetes container monitoring to Azure Monitor.",
        ("Collects container logs and Kubernetes monitoring data.",
         "Uses a Log Analytics workspace; installing the extension is separate from listing it."),
        "Consider for investigating container behavior and cluster operations with collected telemetry.",
        "azure/azure-arc/kubernetes/extensions",
    ),
    "microsoft.policyinsights": (
        "Azure Policy for Kubernetes",
        "Applies centrally managed policy to Kubernetes resources using Gatekeeper.",
        ("Audits or enforces policy on resources such as pods, containers, and namespaces.",
         "Reports audit and compliance information to Azure Policy."),
        "Consider for Kubernetes configuration governance after testing the policy assignments.",
        "azure/governance/policy/concepts/policy-for-kubernetes",
    ),
    "microsoft.vmware": (
        "Azure Arc-enabled VMware vSphere",
        "Connects VMware vSphere inventory and VM lifecycle management to the Azure control plane.",
        ("Uses an Azure Arc resource bridge to communicate with VMware vCenter.",
         "Discovers vSphere resources and enables Azure-managed VM lifecycle operations.",
         "Guest operating-system management requires the connected machine agent separately."),
        "Consider for managing existing VMware infrastructure through Azure; this is not GitOps "
        "or evidence that VMware workloads can be installed on AKS.",
        "azure/azure-arc/vmware-vsphere/overview",
    ),
}
_EXTENSION_ALIASES = {
    "extensions.gitops": "microsoft.flux",
    "extensions.monitor": "microsoft.azuremonitor.containers",
}


def _extension_context(feature: str) -> dict[str, Any]:
    identity = _EXTENSION_ALIASES.get(feature, feature.removeprefix("extensionTypes.").lower())
    profile = _EXTENSION_PROFILES.get(identity)
    if profile:
        title, summary, facts, use_cases, page = profile
        sources = [_source(title, _LEARN + page)]
        if identity == "microsoft.vmware":
            sources.append(_source(
                "Microsoft's exact VMware extension-type mapping",
                _LEARN + "azure/azure-arc/resource-graph-samples",
            ))
        return _description(title, summary, facts, use_cases, tuple(sources), _EXTENSION_LIMIT)
    facts = (
        "The probe observes a regional extension-type catalog, not installed cluster software.",
        "The exact extension's purpose and cluster requirements have not been verified.",
    )
    sources = [_search(feature), _source("AKS cluster extension platform", _EXTENSIONS)]
    if identity == "microsoft.azurepolicy":
        facts = (
            "Azure Policy for Kubernetes provides Gatekeeper-based audit and enforcement.",
            "Microsoft documents microsoft.policyinsights as the extension type; the "
            "microsoft.azurepolicy identifier has not been verified as an alias.",
        )
        sources.append(_source("Documented Azure Policy extension identity", _POLICY))
    return _description(
        f"{identity} - unverified extension identity",
        "A regional extension catalog identifier without a verified exact product mapping.",
        facts, "Check the exact extension's documentation and cluster prerequisites before use.",
        tuple(sources), "Exact extension identity is unverified. " + _EXTENSION_LIMIT, "unverified",
    )


_RUNTIME_PROFILES = {
    "python": (
        "Python", "functions-reference-python",
        "Python functions use triggers and bindings for event-driven code.",
        "The Python v2 programming model declares triggers and bindings with decorators.",
        "Python event handlers and data-processing integrations",
    ),
    "node": (
        "Node.js", "functions-reference-node",
        "Runs JavaScript or TypeScript functions with the @azure/functions programming model.",
        "The Node.js language version is distinct from the Functions programming-model version.",
        "JavaScript/TypeScript HTTP APIs and event handlers",
    ),
    "dotnet-isolated": (
        ".NET isolated worker", "dotnet-isolated-process-guide",
        "Runs .NET code in a worker process separate from the Functions host.",
        "Supports application-controlled startup, dependency injection, and middleware.",
        ".NET event handlers that need worker-process and dependency isolation",
    ),
    "dotnet": (
        ".NET in-process", "functions-dotnet-class-library",
        "Runs .NET class library code in the same process as the Functions host.",
        "Flex Consumption does not support the .NET in-process execution model.",
        "reviewing existing in-process apps and planning isolated-worker migration",
    ),
    "java": (
        "Java", "functions-reference-java",
        "Exposes annotated Java methods as function entry points.",
        "Uses Java annotations for functions and trigger/binding integration, with Maven tooling.",
        "Java event handlers and integrations using existing Java libraries",
    ),
    "powershell": (
        "PowerShell", "functions-reference-powershell",
        "Runs PowerShell scripts in response to configured triggers.",
        "Input/output bindings are declared in function.json and passed to script parameters.",
        "event-triggered operational automation written in PowerShell",
    ),
}
# This is documentation evidence, not a replacement for monitored runtime config.
_FLEX_RUNTIME_VERSIONS = {
    "python": ("3.10", "3.11", "3.12", "3.13", "3.14"),
    "node": ("22", "24"),
    "dotnet-isolated": ("8", "9", "10"),
    "java": ("8", "11", "17", "21", "25"),
    "powershell": ("7.4",),
}


def _runtime_context(feature: str) -> dict[str, Any]:
    language, _, version = feature.removeprefix("runtimes.").partition(".")
    profile = _RUNTIME_PROFILES.get(language)
    if not profile or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        return _description(
            plain_feature_name(feature), "Unverified Functions runtime catalog entry.",
            ("A runtime identifier describes a language stack, not a hosting plan.",
             "Runtime rows are tied to Flex Consumption regional listing evidence."),
            "Verify the language, version, and hosting-plan compatibility before selecting it.",
            (_search(feature), _source("Functions language support", _FUNCTIONS_BASE + "supported-languages")),
            "This exact runtime has not been verified. " + _FUNCTION_LIMIT, "unverified",
        )
    title, page, summary, distinction, use_cases = profile
    supported = version in _FLEX_RUNTIME_VERSIONS.get(language, ())
    version_fact = (
        f"{title} {version} is named in the checked Flex Consumption supported-stack table."
        if supported else
        f"Version {version} is not in the checked Flex Consumption supported-stack table; "
        "its current support is not verified."
    )
    return _description(
        f"{title} {version} for Azure Functions", summary,
        (distinction, version_fact),
        f"Consider for {use_cases}; validate application dependencies and current support.",
        (_source(f"{title} developer guide", _FUNCTIONS_BASE + page),
         _source("Flex Consumption supported language stacks", _FLEX + "#supported-language-stack-versions")),
        _FUNCTION_LIMIT + (
            " The in-process .NET model is explicitly unsupported on Flex Consumption."
            if language == "dotnet" else ""
        ),
        "exact" if supported else "family",
    )


_CONTAINER_PROFILES = {
    "managedEnvironments": (
        "Container Apps managed environment", "environment",
        "An Azure-managed boundary for related container apps and jobs.",
        ("Groups apps and jobs with shared networking and logging configuration.",
         "Workload-profile environments can host Consumption and Dedicated profiles."),
        "grouping related services while planning their network and logging boundaries",
    ),
    "apps": (
        "Container Apps application", "overview",
        "A containerized service rather than a run-to-completion job.",
        ("Supports HTTPS or TCP ingress and multiple application revisions.",
         "Scaling can respond to HTTP traffic or configured event-driven rules."),
        "HTTP APIs, microservices, and continuously operating event consumers",
    ),
    "jobs": (
        "Container Apps job", "jobs",
        "A containerized task that runs to completion and stops.",
        ("Executions can start manually, on a schedule, or in response to events.",
         "Jobs share environment networking and logging with container apps."),
        "batch processing and bounded, scheduled or event-triggered tasks",
    ),
    "connectedEnvironments": (
        "Container Apps connected environment on Azure Arc", "azure-arc-overview",
        "An environment for Container Apps on an Azure Arc-enabled Kubernetes cluster.",
        ("Uses a connected cluster, Container Apps extension, and custom location.",
         "Underlying Kubernetes infrastructure is distinct from an Azure-managed environment."),
        "running Container Apps on supported Arc-connected infrastructure you operate",
    ),
    "daprComponents": (
        "Container Apps Dapr component configuration", "dapr-components",
        "Environment-level configuration connecting Dapr applications to backing services.",
        ("Provides pluggable connections to supporting external services.",
         "Components can be shared or scoped to specific Dapr application IDs.",
         "This resource is a component configuration, not a new Dapr runtime release."),
        "configuring shared or app-scoped service integrations for Dapr-enabled applications",
    ),
}


def _container_context(feature: str) -> dict[str, Any]:
    profile = _CONTAINER_PROFILES.get(feature.removeprefix("containerApps."))
    if not profile:
        return _description(
            plain_feature_name(feature), "Unverified Microsoft.App resource-type observation.",
            ("The regional signal comes from provider metadata's resource-type locations.",
             "The exact resource's application capabilities have not been verified."),
            "Look up the exact Microsoft.App resource type before designing around it.",
            (_search(feature), _source("Container Apps overview", _LEARN + "azure/container-apps/overview")),
            _CONTAINER_LIMIT, "unverified",
        )
    title, page, summary, facts, use_cases = profile
    return _description(
        title, summary, facts, f"Consider for {use_cases}; confirm the deployment prerequisites.",
        (_source(title, _LEARN + "azure/container-apps/" + page),), _CONTAINER_LIMIT,
    )


@dataclass(frozen=True)
class _Model:
    title: str
    summary: str
    facts: tuple[str, ...]
    use_cases: str
    url: str
    versions: tuple[str, ...] = ()


_MODEL_PROFILES = {
    ("openai", "gpt-4o"): _Model(
        "GPT-4o", "An OpenAI model that processes text and image inputs.",
        ("Combines text and image processing.", "Supports JSON mode and parallel function calling."),
        "text and visual-input assistants with tested tool integrations",
        _MODELS + "#gpt-4o-and-gpt-4-turbo", ("2024-05-13", "2024-08-06", "2024-11-20"),
    ),
    ("openai", "gpt-4o-mini"): _Model(
        "GPT-4o mini", "The smaller GPT-4o option for text and image processing.",
        ("Supports text/image processing, JSON mode, and parallel function calling.",
         "Microsoft positions it as a lower-cost replacement candidate for GPT-3.5 Turbo."),
        "bounded text/vision tasks when evaluation confirms sufficient quality",
        _MODELS + "#gpt-4o-and-gpt-4-turbo", ("2024-07-18",),
    ),
    ("openai", "gpt-4-1"): _Model(
        "GPT-4.1", "A text-and-image input model with text output.",
        ("Supports Chat Completions and Responses APIs.",
         "Supports function calling and structured outputs; context limits vary by deployment type."),
        "document and image-assisted workflows with validated API and context requirements",
        _MODELS + "#gpt-41-series", ("2025-04-14",),
    ),
    ("openai", "o3"): _Model(
        "OpenAI o3", "A reasoning model for multistep problem-solving tasks.",
        ("Supports text and image processing with reasoning.",
         "Supports structured outputs and function/tool calling."),
        "reasoning-intensive workflows where quality and latency are evaluated together",
        _MODELS + "#o-series-models", ("2025-04-16",),
    ),
    ("openai", "gpt-6-astra"): _Model(
        "GPT-6 Astra", "A reasoning model accepting text/image input and producing text output.",
        ("Supports structured outputs and configurable reasoning effort.",
         "Tool calling requires the Responses API; Chat Completions does not support its tools.",
         "The documented model does not support the none reasoning-effort level."),
        "reasoning and tool-based workflows after checking API compatibility and access requirements",
        _MODELS + "#gpt-6", ("2026-09-03",),
    ),
    ("anthropic", "claude-fable-5-1"): _Model(
        "Claude Fable 5.1", "Anthropic's model for demanding reasoning and long-running agent work.",
        ("Supports text/image input and text output.",
         "Uses always-on adaptive thinking; forced tool use is not supported."),
        "multistep research and agent workflows when task evaluations justify this model",
        "https://platform.claude.com/docs/en/models/fable-5-1/overview",
    ),
    ("openai", "text-embedding-3-small"): _Model(
        "text-embedding-3-small", "Converts text into numerical vectors for similarity operations.",
        ("Uses the Embeddings API, not a chat-completion API.",
         "Default output is 1,536 dimensions; the dimensions parameter can reduce vector size."),
        "semantic retrieval or similarity ranking after evaluating embedding quality",
        _MODELS + "#embeddings",
    ),
    ("openai", "text-embedding-3-large"): _Model(
        "text-embedding-3-large", "Converts text into numerical vectors for similarity operations.",
        ("Uses the Embeddings API, not a chat-completion API.",
         "Default output is 3,072 dimensions; the dimensions parameter can reduce vector size."),
        "semantic retrieval where evaluation justifies the larger vector storage footprint",
        _MODELS + "#embeddings",
    ),
}

for _variant in ("mini", "nano"):
    _MODEL_PROFILES[("openai", f"gpt-4-1-{_variant}")] = _Model(
        f"GPT-4.1 {_variant}", "A GPT-4.1 variant with text/image input and text output.",
        ("Supports Chat Completions and Responses APIs with function calling.",
         "Supports structured outputs; documented context limits depend on deployment type."),
        "text/vision workflows after comparing this variant's quality and cost on your own tasks",
        _MODELS + "#gpt-41-series", ("2025-04-14",),
    )

for _variant in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
    _MODEL_PROFILES[("openai", _variant)] = _Model(
        display_model_name(_variant), "A GPT-5 reasoning model with text and image processing.",
        ("Supports reasoning, structured outputs, and function/tool calling.",
         "Supports Chat Completions and Responses APIs; this is not the non-reasoning chat variant."),
        "reasoning workflows after evaluating the selected variant's quality, cost, and latency",
        _MODELS + "#gpt-5", ("2025-08-07",),
    )

_MODEL_PROFILES[("openai", "gpt-5-chat")] = _Model(
    "GPT-5 chat", "A preview GPT-5 conversational variant rather than the GPT-5 reasoning model.",
    ("Accepts text and image input and produces text output.",
     "Uses Chat Completions or Responses APIs; preview versions have a distinct lifecycle."),
    "conversational prototypes where preview lifecycle constraints are acceptable",
    _MODELS + "#gpt-5", ("2025-08-07", "2025-10-03"),
)

_MODEL_ALIASES = {
    "gpt-4.1": "gpt-4-1",
    "gpt-4.1-mini": "gpt-4-1-mini",
    "gpt-4.1-nano": "gpt-4-1-nano",
}


def _model_context(feature: str) -> dict[str, Any]:
    modality, _, remainder = feature.partition(".")
    publisher, _, model_and_version = remainder.partition(".")
    publisher = publisher.lower()
    # Auto-discovered model names/versions are slugged separately; do not split
    # an unknown model's dots into an invented version or infer model capabilities.
    if modality == "aiModels":
        model, separator, version = model_and_version.rpartition(".")
        if not separator:
            model, version = model_and_version, ""
    else:
        model, version = model_and_version, ""
    model_key = _MODEL_ALIASES.get(model.lower(), model.lower())
    profile = _MODEL_PROFILES.get((publisher, model_key))
    sources: list[dict[str, str]] = []
    if profile:
        title = profile.title + (f" (catalog version {version})" if version else "")
        exact = version in profile.versions
        context = _description(
            title, profile.summary, profile.facts,
            f"Consider for {profile.use_cases}; validate the exact deployment and version.",
            (_source(f"{profile.title} documentation", profile.url),),
            _MODEL_LIMIT + (
                " The exact catalog version is documented; this is not a launch-date claim."
                if exact else
                " Only model-family capabilities are verified; this exact catalog version or "
                "endpoint mapping has not been verified."
            ),
            "exact" if exact else "family",
        )
    else:
        provider_label = {"openai": "OpenAI", "anthropic": "Anthropic"}.get(publisher, publisher)
        provider_url = _CLAUDE if publisher == "anthropic" else (
            _MODELS if publisher == "openai" else _PARTNER_MODELS
        )
        evidence = {
            "aiModels": "Catalog presence identifies a provider/model/version candidate, not its tested abilities.",
            "modelLatency": "This records an inference request to the configured GitHub Models endpoint.",
            "aiLatency": "This records an inference request to a configured Azure OpenAI deployment.",
        }[modality]
        context = _description(
            f"{display_model_name(model_and_version)} - {provider_label or 'unknown publisher'}",
            "A model identifier observed by this modality; exact capabilities are not verified.",
            (evidence,
             "Context limits, input/output modalities, licensing, and tool support need exact-model review."),
            "Use the linked provider/catalog documentation to evaluate this exact model before adoption.",
            (_source(f"{provider_label or 'Foundry'} model catalog (category only)", provider_url),
             _search(feature)),
            "No exact model capability or version is verified. The source provides category "
            "context only. " + _MODEL_LIMIT,
            "category",
        )
    if modality == "modelLatency":
        context["summary"] = (
            "A GitHub Models endpoint inference-latency observation, not an Azure regional "
            "model-catalog result. " + context["summary"]
        )
        context["limitations"] = (
            "Timing describes the configured request and runner-to-endpoint path, not universal "
            "model speed or an Azure region. GitHub documents GitHub Models as retired on "
            "July 30, 2026; retained observations do not prove the service is currently available. "
            + context["limitations"]
        )
        sources.append(_source("GitHub Models service status", _GITHUB_MODELS))
    elif modality == "aiLatency":
        context["summary"] = (
            "An inference-latency observation against a configured Azure OpenAI deployment. "
            + context["summary"]
        )
        context["limitations"] = (
            "Timing covers the configured endpoint, request, and runner network path only. "
            "It does not prove deployment-local data processing or performance for other prompts. "
            + context["limitations"]
        )
    context["sources"].extend(sources)
    return context


def describe_feature(feature: str) -> dict[str, Any]:
    """Return independent JSON-serializable context without I/O or status changes."""
    if feature.startswith("vmSkus."):
        return _vm_context(feature)
    if feature.startswith(("extensionTypes.", "extensions.")):
        return _extension_context(feature)
    if feature.startswith("runtimes."):
        return _runtime_context(feature)
    if feature.startswith("containerApps."):
        return _container_context(feature)
    if feature.startswith(("aiModels.", "modelLatency.", "aiLatency.")):
        return _model_context(feature)
    if feature == "hostingPlans.flexConsumption":
        return _description(
            "Azure Functions Flex Consumption",
            "A Linux-based serverless hosting plan for event-driven functions.",
            ("Supports virtual network integration and selectable instance memory sizes.",
             "Scales on demand, with optional billed always-ready instances.",
             "Scaling operates per function, with documented trigger groups that scale together."),
            "Consider for event-driven applications needing serverless scaling and private "
            "network access; validate the language stack, startup behavior, and regional quota.",
            (_source("Flex Consumption hosting plan", _FLEX),),
            "The probe checks the Flex Consumption location list, not deployment or quota. "
            "Absence means the region is not listed, not that quota is exhausted.",
        )
    if feature.startswith("hostingPlans."):
        return _description(
            f"{feature.removeprefix('hostingPlans.')} - unverified Functions hosting plan",
            "A hosting-plan identifier without a verified exact product mapping.",
            ("Hosting-plan evidence describes where a function app can be hosted, not its language.",
             "The monitored Flex Consumption probe checks locations, not deployment or quota."),
            "Verify the exact plan and its regional evidence before choosing a Functions host.",
            (_search(feature), _source("Monitored Flex Consumption plan", _FLEX)),
            "This exact hosting-plan capability is unverified; Flex Consumption facts must not "
            "be assumed to apply to another plan.",
            "unverified",
        )
    if feature.startswith("kubernetesVersions."):
        version = feature.removeprefix("kubernetesVersions.")
        return _description(
            f"AKS Kubernetes {version}",
            "A Kubernetes version track in the regional AKS version listing.",
            ("Minor versions can introduce features and API changes; patches contain fixes.",
             "Regional version listing is separate from upgrade eligibility for an existing cluster."),
            "Use for upgrade-target planning after reviewing release notes, deprecated APIs, "
            "node images, and the current AKS support calendar.",
            (_source("AKS version support and release calendar",
                     _LEARN + "azure/aks/supported-kubernetes-versions"), _search(feature)),
            "Version-specific capabilities, GA status, support dates, and cluster upgrade paths "
            "are not inferred from this identifier. A newly observed listing is not a launch.",
            "category",
        )
    catalogs = {
        "vmSkuCatalog": ("VM size catalog", _VM_BASE + "sizes/overview"),
        "extensionCatalog": ("Kubernetes extension catalog", _EXTENSIONS),
        "aiModelCatalog": ("Azure AI model catalog", _MODELS),
    }
    if feature in catalogs:
        title, url = catalogs[feature]
        return _description(
            title, "A catalog-level probe result rather than an individual product capability.",
            ("Catalog retrieval can fail independently of individual feature availability.",
             "An unknown catalog result provides no reliable evidence of product absence."),
            "Inspect the recorded probe evidence before treating a missing entry as a capability change.",
            (_source(title, url),), "No individual feature specifications are verified by this marker.",
            "category",
        )
    return _description(
        feature or "Unrecognized feature",
        "An identifier without a verified offline capability description.",
        ("No exact product capability has been verified for this identifier.",
         "The recorded probe evidence, not the identifier alone, determines what was observed."),
        "Research the exact identifier and its evidence before making a placement or adoption decision.",
        (_search(feature),), "Unverified identifier; no specification, launch, or availability claim.",
        "unverified",
    )
