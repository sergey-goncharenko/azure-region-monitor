from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from azure_region_monitor.config import AiModelFeature
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


@dataclass(frozen=True)
class AiModelRecord:
    feature: str
    model_name: str
    version: str
    publisher: str
    kind: str
    lifecycle_status: str
    sku_names: tuple[str, ...]


class AiModelCatalogCliProbe:
    name = "ai-model-catalog-cli"
    normalize_missing_features = True

    def __init__(
        self,
        model_features: list[AiModelFeature] | None = None,
        cli_runner: CliRunner | None = None,
    ) -> None:
        self._model_features = model_features or []
        self._cli_runner = cli_runner or run_az

    def run(self, region: str):
        started = time.perf_counter()
        listed_models, error = self._list_models(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        if not self._model_features:
            yield from self._run_all_listed_models(region, listed_models, error, latency_ms)
            return

        listed_tokens = _model_tokens(listed_models)
        for model_feature in self._model_features:
            if error:
                yield ProbeResult(
                    service="ai",
                    feature=model_feature.feature,
                    result=FeatureResult(
                        status="unknown",
                        latency_ms=latency_ms,
                        error_code=error.error_code,
                        message=error.message,
                    ),
                )
                continue

            is_available = _normalize_model_token(model_feature.model) in listed_tokens
            yield ProbeResult(
                service="ai",
                feature=model_feature.feature,
                result=FeatureResult(
                    status="available" if is_available else "unavailable",
                    latency_ms=latency_ms,
                    message=_selected_model_message(region, model_feature.model, is_available),
                ),
            )

    def _run_all_listed_models(
        self,
        region: str,
        listed_models: list[AiModelRecord],
        error: AzureCliError | None,
        latency_ms: int,
    ):
        if error:
            yield ProbeResult(
                service="ai",
                feature="aiModelCatalog",
                result=FeatureResult(
                    status="unknown",
                    latency_ms=latency_ms,
                    error_code=error.error_code,
                    message=error.message,
                ),
            )
            return

        for model in sorted(listed_models, key=lambda item: item.feature):
            yield ProbeResult(
                service="ai",
                feature=model.feature,
                result=FeatureResult(
                    status="available",
                    latency_ms=latency_ms,
                    message=_listed_model_message(region, model),
                ),
            )

    def _list_models(self, region: str) -> tuple[list[AiModelRecord], AzureCliError | None]:
        command = [
            az_executable(),
            "cognitiveservices",
            "model",
            "list",
            "--location",
            region,
            "--output",
            "json",
        ]

        try:
            completed = self._cli_runner(command)
        except FileNotFoundError:
            return [], AzureCliError("AzureCliNotFound", "Azure CLI executable 'az' was not found.")

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Azure CLI command failed.").strip()
            if _is_unsupported_model_catalog_location(message):
                return [], None
            return [], AzureCliError("AzureCliCommandFailed", message)

        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as error:
            return [], AzureCliError("AzureCliInvalidJson", str(error))

        return _extract_model_records(payload), None


def _extract_model_records(payload: object) -> list[AiModelRecord]:
    if not isinstance(payload, list):
        return []

    records: dict[str, AiModelRecord] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        model = item.get("model")
        if not isinstance(model, dict):
            continue

        model_name = _string_value(model.get("name")) or _model_name_from_resource_name(
            _string_value(item.get("name"))
        )
        if not model_name:
            continue
        version = _string_value(model.get("version")) or "unversioned"
        publisher = _string_value(model.get("publisher")) or _string_value(model.get("format")) or "unknown"
        kind = _string_value(item.get("kind")) or "unknown"
        lifecycle_status = _string_value(model.get("lifecycleStatus")) or "unknown"
        sku_names = _extract_sku_names(model.get("skus"))
        feature = f"aiModels.{_feature_slug(publisher)}.{_feature_slug(model_name)}.{_feature_slug(version)}"
        records[feature] = AiModelRecord(
            feature=feature,
            model_name=model_name,
            version=version,
            publisher=publisher,
            kind=kind,
            lifecycle_status=lifecycle_status,
            sku_names=sku_names,
        )

    return list(records.values())


def _extract_sku_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _string_value(item.get("name"))
        if name:
            names.append(name)
    return tuple(sorted(set(names)))


def _model_tokens(models: list[AiModelRecord]) -> set[str]:
    tokens: set[str] = set()
    for model in models:
        tokens.add(_normalize_model_token(f"{model.model_name}@{model.version}"))
        tokens.add(_normalize_model_token(f"{model.publisher}/{model.model_name}@{model.version}"))
    return tokens


def _normalize_model_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _is_unsupported_model_catalog_location(message: str) -> bool:
    normalized = message.lower()
    return "noregisteredproviderfound" in normalized and "locations/models" in normalized


def _feature_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unknown"


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _model_name_from_resource_name(value: str) -> str:
    parts = value.split(".")
    return parts[1] if len(parts) >= 3 else value


def _listed_model_message(region: str, model: AiModelRecord) -> str:
    sku_text = f" SKUs: {', '.join(model.sku_names)}." if model.sku_names else ""
    return (
        f"Azure AI model '{model.model_name}' version '{model.version}' "
        f"from '{model.publisher}' is listed by az cognitiveservices model list in {region}. "
        f"Kind: {model.kind}. Lifecycle: {model.lifecycle_status}." + sku_text
    )


def _selected_model_message(region: str, model: str, is_available: bool) -> str:
    if is_available:
        return f"Azure AI model '{model}' is listed by az cognitiveservices model list in {region}."
    return f"Azure AI model '{model}' was not listed by az cognitiveservices model list in {region}."