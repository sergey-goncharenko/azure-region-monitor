from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

LEARN_MCP_ENDPOINT = "https://learn.microsoft.com/api/mcp"
LEARN_REFERENCE_CACHE = "feature-references.json"
POSITIVE_CACHE_TTL = timedelta(days=30)
NEGATIVE_CACHE_TTL = timedelta(days=7)
DEFAULT_MAX_LOOKUPS = 40
DEFAULT_TOTAL_BUDGET_SECONDS = 90.0
DEFAULT_TIMEOUT_SECONDS = 10.0
_CACHE_VERSION = 1
_GATE_VERSION = 3
_GENERIC_DISTINCTIVE_TOKENS = {
    "aks",
    "azure",
    "cluster",
    "extension",
    "extensions",
    "kubernetes",
    "microsoft",
    "model",
    "models",
    "openai",
    "policy",
    "preview",
    "series",
    "service",
    "services",
    "size",
    "sizes",
    "version",
    "versions",
}
_ALLOWED_DISTINCTIVE_TOKEN_SUFFIXES = _GENERIC_DISTINCTIVE_TOKENS | {
    "availability",
    "docs",
    "documentation",
    "ga",
    "general",
    "guide",
    "guidance",
    "reasoning",
    "release",
    "releases",
    "supported",
    "support",
}
_MODEL_VARIANT_SUFFIXES = {
    "large",
    "micro",
    "mini",
    "nano",
    "small",
    "turbo",
}
_TOKEN_SEPARATOR_PATTERN = r"[\s\-_/.#]*"


@dataclass(frozen=True)
class LearnHttpResponse:
    status: int
    headers: Mapping[str, str]
    content_type: str
    body: bytes


Transport = Callable[[str, Mapping[str, Any], Mapping[str, str], float], LearnHttpResponse]


@dataclass(frozen=True)
class LookupQuery:
    query: str
    tokens: tuple[str, ...]


class LearnLookupClient:
    def __init__(
        self,
        *,
        endpoint: str = LEARN_MCP_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._transport = transport or _urllib_transport
        self._session_id: str | None = None
        self._next_id = 1

    def search(self, query: str) -> list[dict[str, Any]]:
        self._initialize()
        response = self._request(
            "tools/call",
            {"name": "microsoft_docs_search", "arguments": {"query": query}},
        )
        return _extract_search_results(response)

    def _initialize(self) -> None:
        if self._session_id is not None:
            return
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "azure-region-monitor",
                    "version": "0.1.0",
                },
            },
        )

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": dict(params),
        }
        self._next_id += 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._transport(self._endpoint, payload, headers, self._timeout)
        session_id = _header(response.headers, "Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        message = parse_json_rpc_response(response.content_type, response.body)
        if "error" in message:
            raise RuntimeError(f"Microsoft Learn MCP returned an error: {message['error']}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise ValueError("Microsoft Learn MCP response did not include an object result")
        return result


def learn_lookup_enabled_from_env() -> bool:
    return os.environ.get("LEARN_LOOKUP_ENABLED", "1") != "0"


def parse_json_rpc_response(content_type: str, body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8")
    if content_type.lower().split(";", 1)[0].strip() == "text/event-stream":
        messages: list[dict[str, Any]] = []
        for block in re.split(r"\r?\n\r?\n", text.strip()):
            data_lines = []
            for line in block.splitlines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if not data_lines:
                continue
            parsed = json.loads("\n".join(data_lines))
            if isinstance(parsed, dict):
                messages.append(parsed)
        if not messages:
            raise ValueError("Microsoft Learn MCP SSE response did not contain JSON data")
        return messages[-1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Microsoft Learn MCP JSON response was not an object")
    return parsed


def lookup_learn_references(
    briefing: dict[str, Any],
    cache_path: Path,
    *,
    enabled: bool | None = None,
    client: LearnLookupClient | None = None,
    now: datetime | None = None,
    max_lookups: int = DEFAULT_MAX_LOOKUPS,
    total_budget_seconds: float = DEFAULT_TOTAL_BUDGET_SECONDS,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    metadata: dict[str, Any] = {
        "status": "ok",
        "looked_up": 0,
        "cached": 0,
        "matched": 0,
        "error": None,
    }
    if enabled is None:
        enabled = learn_lookup_enabled_from_env()
    if not enabled:
        metadata["status"] = "disabled"
        return metadata

    entries = list(_digest_feature_entries(briefing))
    if not entries:
        return metadata

    cache = read_reference_cache(cache_path)
    references: dict[str, dict[str, str]] = {}
    stale_entries: list[dict[str, Any]] = []
    for entry in entries:
        feature = entry["feature"]
        cached = _fresh_cache_entry(cache, feature, now)
        if cached is None:
            stale_entries.append(entry)
            continue
        metadata["cached"] += 1
        reference = cached.get("reference")
        if isinstance(reference, dict):
            references[feature] = _reference_payload(reference)

    if stale_entries:
        lookup_client = client or LearnLookupClient()
        deadline = time.monotonic() + total_budget_seconds
        for entry in sorted(stale_entries, key=lambda item: item["feature"]):
            if metadata["looked_up"] >= max_lookups or time.monotonic() >= deadline:
                metadata["status"] = "partial"
                metadata["error"] = "lookup budget exhausted"
                break
            feature = entry["feature"]
            query = build_lookup_query(entry)
            if query is None:
                _put_cache_entry(cache, feature, now, None, "")
                continue
            try:
                results = lookup_client.search(query.query)
                metadata["looked_up"] += 1
            except Exception as error:
                metadata["status"] = "partial" if references else "failed"
                metadata["error"] = str(error)
                break
            reference = select_learn_reference(entry, results)
            _put_cache_entry(cache, feature, now, reference, query.query)
            if reference is not None:
                references[feature] = reference

    if references:
        attach_learn_references(briefing, references)
    metadata["matched"] = len(references)
    write_reference_cache(cache_path, cache, now=now)
    return metadata


def attach_cached_learn_references(
    briefing: dict[str, Any],
    cache_path: Path,
    *,
    now: datetime | None = None,
) -> None:
    references = fresh_cached_references(cache_path, now=now)
    if references:
        attach_learn_references(briefing, references)


def attach_learn_references(
    briefing: dict[str, Any],
    references: Mapping[str, Mapping[str, str]],
) -> None:
    digest = briefing.get("digest")
    if isinstance(digest, dict):
        for modality in digest.get("modalities", []):
            if not isinstance(modality, dict):
                continue
            for feature_entry in modality.get("features", []):
                if not isinstance(feature_entry, dict):
                    continue
                feature = feature_entry.get("feature")
                if isinstance(feature, str) and feature in references:
                    feature_entry["learn_reference"] = dict(references[feature])
    contexts = briefing.get("feature_contexts")
    if isinstance(contexts, dict):
        for feature, reference in references.items():
            context = contexts.get(feature)
            if isinstance(context, dict):
                context["learn_reference"] = dict(reference)


def fresh_cached_references(
    cache_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, str]]:
    now = now or datetime.now(timezone.utc)
    cache = read_reference_cache(cache_path)
    references: dict[str, dict[str, str]] = {}
    features = cache.get("features")
    if not isinstance(features, dict):
        return references
    for feature in sorted(features):
        if not isinstance(feature, str):
            continue
        cached = _fresh_cache_entry(cache, feature, now)
        if cached is None:
            continue
        reference = cached.get("reference")
        if isinstance(reference, dict):
            references[feature] = _reference_payload(reference)
    return references


def read_reference_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": _CACHE_VERSION, "features": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": _CACHE_VERSION, "features": {}}
    if not isinstance(value, dict) or not isinstance(value.get("features"), dict):
        return {"version": _CACHE_VERSION, "features": {}}
    return {
        **value,
        "features": {
            feature: entry
            for feature, entry in value["features"].items()
            if isinstance(feature, str) and isinstance(entry, dict)
        },
    }


def write_reference_cache(path: Path, cache: dict[str, Any], *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    features = cache.get("features") if isinstance(cache.get("features"), dict) else {}
    normalized = {
        "version": _CACHE_VERSION,
        "generated_at": _format_time(now),
        "features": {
            str(feature): _normalized_cache_entry(entry)
            for feature, entry in sorted(features.items())
            if isinstance(entry, dict)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_lookup_query(entry: Mapping[str, Any]) -> LookupQuery | None:
    feature = str(entry.get("feature") or "")
    label = str(entry.get("label") or feature)
    modality = str(entry.get("modality") or "")
    if _is_measurement_modality(modality):
        return None
    if feature.startswith("vmSkus."):
        series = _vm_series_name(feature)
        target = series or label
        return LookupQuery(f"{target} series Azure virtual machine size", _tokens(target, feature))
    if feature.startswith("extensionTypes."):
        name = _extension_name(feature)
        return LookupQuery(f"{name} AKS cluster extension", _tokens(name, feature))
    if feature.startswith("aiModels."):
        model = _model_name(feature)
        return LookupQuery(f"{model} Azure OpenAI / Foundry model", _tokens(model, feature))
    if feature.startswith("runtimes."):
        runtime = feature.removeprefix("runtimes.").replace(".", " ")
        return LookupQuery(f"Azure Functions Flex Consumption {runtime} runtime", _tokens(runtime, feature))
    if feature == "hostingPlans.flexConsumption":
        return LookupQuery(
            "Azure Functions Flex Consumption hosting plan",
            ("flexconsumption", "flex consumption"),
        )
    if feature.startswith("containerApps."):
        resource_type = feature.removeprefix("containerApps.")
        return LookupQuery(
            f"Azure Container Apps {resource_type} resource type",
            _tokens(resource_type, feature),
        )
    if feature.startswith("kubernetesVersions."):
        version = feature.removeprefix("kubernetesVersions.")
        return LookupQuery(f"AKS Kubernetes {version} release", (version,))
    if modality:
        return LookupQuery(f"{label} {modality} Microsoft Learn", _tokens(label, feature))
    return None


def select_learn_reference(
    entry: Mapping[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, str] | None:
    best_score = -1
    best_reference: dict[str, str] | None = None
    for result in results:
        candidate = _candidate_learn_reference(entry, result)
        if candidate is None:
            continue
        score, reference = candidate
        if score > best_score:
            best_score = score
            best_reference = reference
    return best_reference


def _urllib_transport(
    endpoint: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: float,
) -> LearnHttpResponse:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return LearnHttpResponse(
            status=response.status,
            headers=dict(response.headers.items()),
            content_type=response.headers.get("Content-Type", "application/json"),
            body=body,
        )


def _extract_search_results(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and isinstance(structured.get("results"), list):
        return [item for item in structured["results"] if isinstance(item, dict)]
    content = result.get("content")
    if not isinstance(content, list):
        return []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        parsed = json.loads(text)
        results = parsed.get("results") if isinstance(parsed, dict) else None
        if isinstance(results, list):
            return [result for result in results if isinstance(result, dict)]
    return []


def _digest_feature_entries(briefing: Mapping[str, Any]) -> list[dict[str, Any]]:
    digest = briefing.get("digest")
    if not isinstance(digest, dict):
        return []
    entries: dict[str, dict[str, Any]] = {}
    for modality in digest.get("modalities", []):
        if not isinstance(modality, dict):
            continue
        modality_name = str(modality.get("modality") or "")
        if _is_measurement_modality(modality_name):
            continue
        for feature_entry in modality.get("features", []):
            if not isinstance(feature_entry, dict):
                continue
            feature = feature_entry.get("feature")
            if isinstance(feature, str) and feature:
                entry = dict(feature_entry)
                entry.setdefault("modality", modality_name)
                entries[feature] = entry
    return [entries[feature] for feature in sorted(entries)]


def _fresh_cache_entry(cache: Mapping[str, Any], feature: str, now: datetime) -> dict[str, Any] | None:
    features = cache.get("features")
    if not isinstance(features, dict):
        return None
    entry = features.get(feature)
    if not isinstance(entry, dict):
        return None
    if entry.get("gate_version") != _GATE_VERSION:
        return None
    checked_at = _parse_time(entry.get("checked_at"))
    if checked_at is None:
        return None
    ttl = POSITIVE_CACHE_TTL if isinstance(entry.get("reference"), dict) else NEGATIVE_CACHE_TTL
    if now - checked_at > ttl:
        return None
    return entry


def _put_cache_entry(
    cache: dict[str, Any],
    feature: str,
    now: datetime,
    reference: Mapping[str, str] | None,
    query: str,
) -> None:
    features = cache.setdefault("features", {})
    if not isinstance(features, dict):
        cache["features"] = features = {}
    features[feature] = {
        "checked_at": _format_time(now),
        "gate_version": _GATE_VERSION,
        "query": query,
        "reference": dict(reference) if reference is not None else None,
    }


def _normalized_cache_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    reference = entry.get("reference")
    return {
        "checked_at": str(entry.get("checked_at") or ""),
        "gate_version": entry.get("gate_version") if isinstance(entry.get("gate_version"), int) else None,
        "query": str(entry.get("query") or ""),
        "reference": _reference_payload(reference) if isinstance(reference, dict) else None,
    }


def _candidate_learn_reference(
    entry: Mapping[str, Any],
    result: Mapping[str, Any],
) -> tuple[int, dict[str, str]] | None:
    url = str(result.get("contentUrl") or result.get("url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "learn.microsoft.com":
        return None
    title = str(result.get("title") or "").strip()
    content = str(result.get("content") or result.get("excerpt") or "")
    path = _normalized_learn_path(parsed.path)
    score = _reference_score(entry, title, path, content)
    if score is None:
        return None
    return score, {
        "title": _collapse_text(title)[:200],
        "url": url,
        "excerpt": _plain_excerpt(content),
    }


def _reference_score(
    entry: Mapping[str, Any],
    title: str,
    path: str,
    content: str,
) -> int | None:
    feature = str(entry.get("feature") or "")
    if feature.startswith("vmSkus."):
        return _vm_reference_score(feature, title, path)
    if feature.startswith("extensionTypes."):
        return _extension_reference_score(feature, title, path)
    if feature.startswith("aiModels."):
        return _ai_model_reference_score(feature, title, path, content)
    if feature.startswith("runtimes.") or feature == "hostingPlans.flexConsumption":
        return _functions_reference_score(feature, title, path, content)
    if feature.startswith("kubernetesVersions."):
        return _kubernetes_version_reference_score(feature, title, path, content)
    if feature.startswith("containerApps."):
        return _container_apps_reference_score(feature, title, path, content)
    query = build_lookup_query(entry)
    tokens = query.tokens if query else _tokens(str(entry.get("label") or ""), feature)
    distinctive = _distinctive_tokens(*tokens)
    if not _contains_distinctive_token(f"{title}\n{path}\n{content}", distinctive):
        return None
    return 10


def _vm_reference_score(feature: str, title: str, path: str) -> int | None:
    series = _vm_series_name(feature)
    if series is None or not _contains_distinctive_token(f"{title}\n{path}", (series,)):
        return None
    score = 50
    if _path_starts(path, "azure/virtual-machines/sizes"):
        score += 100
    elif _path_starts(path, "azure/virtual-machines"):
        score += 75
    return score


def _extension_reference_score(feature: str, title: str, path: str) -> int | None:
    tokens = _extension_distinctive_tokens(feature)
    if not tokens or not _contains_distinctive_token(f"{title}\n{path}", tokens):
        return None
    if not _is_extension_product_path(feature, path):
        return None
    score = 50
    if _path_starts(path, "azure/aks") or _path_starts(path, "azure/azure-arc/kubernetes"):
        score += 100
    else:
        score += 25
    return score


def _ai_model_reference_score(feature: str, title: str, path: str, content: str) -> int | None:
    model = _model_base_name(feature)
    if not model:
        return None
    if not (_path_starts(path, "azure/ai-foundry") or _path_starts(path, "azure/ai-services/openai")):
        return None
    headings = "\n".join(_content_headings(content))
    if not _contains_distinctive_token(f"{title}\n{path}\n{headings}", (model,)):
        return None
    score = 50
    if _path_starts(path, "azure/ai-services/openai"):
        score += 100
    elif _path_starts(path, "azure/ai-foundry"):
        score += 90
    return score


def _functions_reference_score(feature: str, title: str, path: str, content: str) -> int | None:
    if not _path_starts(path, "azure/azure-functions"):
        return None
    if feature == "hostingPlans.flexConsumption":
        tokens = ("flexconsumption", "flex consumption")
    else:
        runtime = feature.removeprefix("runtimes.")
        tokens = _distinctive_tokens(runtime, runtime.split(".", 1)[0])
    if not _contains_distinctive_token(f"{title}\n{path}\n{content}", tokens):
        return None
    return 120


def _kubernetes_version_reference_score(feature: str, title: str, path: str, content: str) -> int | None:
    version = feature.removeprefix("kubernetesVersions.")
    if not _path_starts(path, "azure/aks"):
        return None
    if _path_starts(path, "azure/aks/security-bulletins"):
        return None
    if not _contains_distinctive_token(f"{title}\n{path}\n{content}", (version,)):
        return None
    score = 120
    if "supported-kubernetes-versions" in path:
        score += 100
    if _contains_distinctive_token(title, ("supported kubernetes versions",)):
        score += 25
    return score


def _container_apps_reference_score(feature: str, title: str, path: str, content: str) -> int | None:
    if not _path_starts(path, "azure/container-apps"):
        return None
    tokens = _distinctive_tokens(feature.removeprefix("containerApps."))
    if not _contains_distinctive_token(f"{title}\n{path}\n{content}", tokens):
        return None
    return 120


def _reference_payload(reference: Mapping[str, Any]) -> dict[str, str]:
    return {
        "title": str(reference.get("title") or ""),
        "url": str(reference.get("url") or ""),
        "excerpt": str(reference.get("excerpt") or "")[:200],
    }


def _vm_series_name(feature: str) -> str | None:
    slug = feature.removeprefix("vmSkus.").lower().replace("_", ".")
    match = re.fullmatch(r"standard\.([a-z]+?)([1-9][0-9]{0,3})([a-z]*)\.v([1-9][0-9]*)", slug)
    if not match:
        return None
    family, _size, suffix, generation = match.groups()
    return f"{family.upper()}{suffix}v{generation}"


def _model_name(feature: str) -> str:
    parts = feature.split(".", 2)
    if len(parts) < 3:
        return feature.removeprefix("aiModels.")
    model = parts[2]
    date_match = re.fullmatch(r"(.+)\.(\d{4}-\d{2}-\d{2})", model)
    if date_match:
        return f"{date_match.group(1)} {date_match.group(2)}"
    version_match = re.fullmatch(r"(.+)\.(\d+(?:-\d+)*)", model)
    if version_match:
        return f"{version_match.group(1)} {version_match.group(2)}"
    return model


def _model_base_name(feature: str) -> str:
    name = _model_name(feature)
    date_match = re.fullmatch(r"(.+)\s+\d{4}-\d{2}-\d{2}", name)
    if date_match:
        return date_match.group(1)
    version_match = re.fullmatch(r"(.+)\s+\d+(?:-\d+)+", name)
    if version_match:
        return version_match.group(1)
    return name


def _extension_name(feature: str) -> str:
    name = feature.removeprefix("extensionTypes.")
    if name.startswith("microsoft."):
        name = name.removeprefix("microsoft.")
    special = {
        "azurepolicy": "Azure Policy",
        "policyinsights": "Azure Policy",
        "azuremonitor.containers": "Azure Monitor containers",
    }
    if name in special:
        return special[name]
    return name.replace(".", " ")


def _extension_distinctive_tokens(feature: str) -> tuple[str, ...]:
    name = feature.removeprefix("extensionTypes.")
    if name.startswith("microsoft."):
        name = name.removeprefix("microsoft.")
    tokens = [name, _extension_name(feature)]
    if name == "azurepolicy":
        tokens.append("azure policy")
    if name == "azuremonitor.containers":
        tokens.append("container insights")
    return _distinctive_tokens(*tokens)


def _is_extension_product_path(feature: str, path: str) -> bool:
    if _path_starts(path, "azure/backup") and "backup" not in _extension_distinctive_tokens(feature):
        return False
    if _path_starts(path, "azure/aks") or _path_starts(path, "azure/azure-arc/kubernetes"):
        return True
    tokens = set(_extension_distinctive_tokens(feature))
    if "backup" in tokens:
        return _path_starts(path, "azure/backup")
    if "azurepolicy" in tokens:
        return _path_starts(path, "azure/governance/policy")
    if "dapr" in tokens:
        return _path_starts(path, "azure/dapr")
    return False


def _tokens(primary: str, feature: str) -> tuple[str, ...]:
    tokens = []
    for value in (primary, feature.rsplit(".", 1)[-1], feature):
        normalized = _collapse_text(str(value)).lower()
        if normalized and normalized not in tokens:
            tokens.append(normalized)
    compact = _compact_token(primary)
    if compact and compact not in tokens:
        tokens.append(compact)
    return tuple(tokens)


def _distinctive_tokens(*values: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        normalized = _collapse_text(str(value)).lower()
        if normalized and normalized not in _GENERIC_DISTINCTIVE_TOKENS and normalized not in tokens:
            tokens.append(normalized)
        for part in re.split(r"[^a-zA-Z0-9.]+", str(value).lower()):
            clean = part.strip(".")
            if (
                clean
                and clean not in _GENERIC_DISTINCTIVE_TOKENS
                and clean not in tokens
                and (len(clean) > 1 or clean.isdigit())
            ):
                tokens.append(clean)
        compact = _compact_token(value)
        if compact and compact not in _GENERIC_DISTINCTIVE_TOKENS and compact not in tokens:
            tokens.append(compact)
    return tuple(tokens)


def _contains_distinctive_token(text: str, tokens: tuple[str, ...]) -> bool:
    haystack = text.lower()
    for token in tokens:
        parts = re.findall(r"[a-z0-9]+", token.lower())
        if not parts:
            continue
        token_pattern = _TOKEN_SEPARATOR_PATTERN.join(map(re.escape, parts))
        pattern = re.compile(
            rf"(?<![a-z0-9]){token_pattern}(?![a-z0-9])"
        )
        if any(
            not _has_disallowed_distinctive_suffix(haystack, match.end(), token)
            for match in pattern.finditer(haystack)
        ):
            return True
    return False


def _has_disallowed_distinctive_suffix(text: str, match_end: int, token: str) -> bool:
    if not any(character.isdigit() for character in token):
        return False
    suffix_match = re.match(r"([\s\-_/.#]+)([a-z0-9]+)", text[match_end:])
    if suffix_match is None:
        return False
    separators, suffix = suffix_match.groups()
    if suffix in _ALLOWED_DISTINCTIVE_TOKEN_SUFFIXES:
        return False
    if any(not separator.isspace() for separator in separators):
        return True
    return len(_compact_token(token)) <= 3 and suffix in _MODEL_VARIANT_SUFFIXES


def _content_headings(content: str) -> list[str]:
    headings = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return headings


def _normalized_learn_path(path: str) -> str:
    normalized = urllib.parse.unquote(path).lower().strip("/")
    parts = normalized.split("/")
    if parts and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0]):
        parts = parts[1:]
    return "/".join(part for part in parts if part)


def _path_starts(path: str, prefix: str) -> bool:
    normalized_prefix = prefix.lower().strip("/")
    return path == normalized_prefix or path.startswith(f"{normalized_prefix}/")


def _plain_excerpt(content: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", content)
    text = re.sub(r"[#*_`>|]", " ", text)
    return _collapse_text(text)[:200]


def _collapse_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _is_measurement_modality(modality: str) -> bool:
    return "latency" in modality.lower()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None
