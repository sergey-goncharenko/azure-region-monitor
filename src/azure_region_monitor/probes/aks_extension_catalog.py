from __future__ import annotations

import json
import re
import time

from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


class AksExtensionCatalogCliProbe:
    name = "aks-extension-catalog-cli"
    normalize_missing_features = True

    def __init__(self, cli_runner: CliRunner | None = None) -> None:
        self._cli_runner = cli_runner or run_az

    def run(self, region: str):
        started = time.perf_counter()
        extension_types, error = self._list_extension_types(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        if error:
            yield ProbeResult(
                service="aks",
                feature="extensionCatalog",
                result=FeatureResult(
                    status="unknown",
                    latency_ms=latency_ms,
                    error_code=error.error_code,
                    message=error.message,
                ),
            )
            return

        for extension_type in sorted(extension_types):
            yield ProbeResult(
                service="aks",
                feature=f"extensionTypes.{_feature_slug(extension_type)}",
                result=FeatureResult(
                    status="available",
                    latency_ms=latency_ms,
                    message=f"AKS extension type '{extension_type}' is listed in {region}.",
                ),
            )

    def _list_extension_types(self, region: str) -> tuple[set[str], AzureCliError | None]:
        command = [
            az_executable(),
            "k8s-extension",
            "extension-types",
            "list-by-location",
            "--location",
            region,
            "--output",
            "json",
        ]

        try:
            completed = self._cli_runner(command)
        except FileNotFoundError:
            return set(), AzureCliError("AzureCliNotFound", "Azure CLI executable 'az' was not found.")

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Azure CLI command failed.").strip()
            if _is_unsupported_extension_catalog_location(message):
                return set(), None
            return set(), AzureCliError("AzureCliCommandFailed", message)

        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as error:
            return set(), AzureCliError("AzureCliInvalidJson", str(error))

        return _extract_extension_type_names(payload), None


def _extract_extension_type_names(payload: object) -> set[str]:
    if not isinstance(payload, list):
        return set()

    names: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        for key in ("extensionType", "name"):
            value = item.get(key)
            if isinstance(value, str):
                names.add(value.lower())
    return names


def _feature_slug(extension_type: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", extension_type.lower()).strip(".")


def _is_unsupported_extension_catalog_location(message: str) -> bool:
    """Return True for region-scoped unsupported-location provider errors.

    This keeps generic Azure CLI failures as unknown while allowing explicit
    `locations/extensionTypes` unsupported-location responses to normalize as an
    empty catalog for that region.
    """
    normalized = message.lower()
    return "noregisteredproviderfound" in normalized and "locations/extensiontypes" in normalized
