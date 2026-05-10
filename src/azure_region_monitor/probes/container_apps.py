from __future__ import annotations

import json
import re
import time

from azure_region_monitor.config import (
    DEFAULT_CONTAINER_APPS_RESOURCE_FEATURES,
    ContainerAppsResourceFeature,
)
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


class ContainerAppsProviderCliProbe:
    name = "container-apps-provider-cli"

    def __init__(
        self,
        resource_features: list[ContainerAppsResourceFeature] | None = None,
        cli_runner: CliRunner | None = None,
    ) -> None:
        self._resource_features = resource_features or DEFAULT_CONTAINER_APPS_RESOURCE_FEATURES
        self._cli_runner = cli_runner or run_az
        self._resource_locations: tuple[dict[str, set[str]], AzureCliError | None] | None = None

    def run(self, region: str):
        started = time.perf_counter()
        resource_locations, error = self._list_resource_locations()
        latency_ms = round((time.perf_counter() - started) * 1000)
        normalized_region = _normalize_location(region)

        for resource_feature in self._resource_features:
            yield ProbeResult(
                service="containerApps",
                feature=resource_feature.feature,
                result=_resource_result(
                    region=region,
                    normalized_region=normalized_region,
                    resource_feature=resource_feature,
                    resource_locations=resource_locations,
                    error=error,
                    latency_ms=latency_ms,
                ),
            )

    def _list_resource_locations(self) -> tuple[dict[str, set[str]], AzureCliError | None]:
        if self._resource_locations is None:
            command = [
                az_executable(),
                "provider",
                "show",
                "--namespace",
                "Microsoft.App",
                "--expand",
                "resourceTypes/locations",
                "--output",
                "json",
            ]
            self._resource_locations = self._run_provider_command(command)
        return self._resource_locations

    def _run_provider_command(
        self, command: list[str]
    ) -> tuple[dict[str, set[str]], AzureCliError | None]:
        try:
            completed = self._cli_runner(command)
        except FileNotFoundError:
            return {}, AzureCliError("AzureCliNotFound", "Azure CLI executable 'az' was not found.")

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Azure CLI command failed.").strip()
            return {}, AzureCliError("AzureCliCommandFailed", message)

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as error:
            return {}, AzureCliError("AzureCliInvalidJson", str(error))

        return _extract_resource_locations(payload), None


def _resource_result(
    region: str,
    normalized_region: str,
    resource_feature: ContainerAppsResourceFeature,
    resource_locations: dict[str, set[str]],
    error: AzureCliError | None,
    latency_ms: int,
) -> FeatureResult:
    if error:
        return FeatureResult(
            status="unknown",
            latency_ms=latency_ms,
            error_code=error.error_code,
            message=error.message,
        )

    resource_type_key = _normalize_resource_type(resource_feature.resource_type)
    locations = resource_locations.get(resource_type_key)
    if locations is None:
        return FeatureResult(
            status="unavailable",
            latency_ms=latency_ms,
            message=(
                f"Microsoft.App resource type '{resource_feature.resource_type}' "
                "was not listed by provider metadata."
            ),
        )

    if normalized_region in locations:
        return FeatureResult(
            status="available",
            latency_ms=latency_ms,
            message=(
                f"Microsoft.App resource type '{resource_feature.resource_type}' "
                f"is advertised in {region}."
            ),
        )

    return FeatureResult(
        status="unavailable",
        latency_ms=latency_ms,
        message=(
            f"Microsoft.App resource type '{resource_feature.resource_type}' "
            f"was not advertised in {region}."
        ),
    )


def _extract_resource_locations(payload: object) -> dict[str, set[str]]:
    if not isinstance(payload, dict):
        return {}
    resource_types = payload.get("resourceTypes")
    if not isinstance(resource_types, list):
        return {}

    locations_by_type: dict[str, set[str]] = {}
    for resource_type in resource_types:
        if not isinstance(resource_type, dict):
            continue
        name = resource_type.get("resourceType")
        raw_locations = resource_type.get("locations")
        if not isinstance(name, str) or not isinstance(raw_locations, list):
            continue
        normalized_locations = {
            _normalize_location(location) for location in raw_locations if isinstance(location, str)
        }
        locations_by_type[_normalize_resource_type(name)] = {
            location for location in normalized_locations if location
        }

    return locations_by_type


def _normalize_location(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _normalize_resource_type(value: str) -> str:
    return value.strip().lower()