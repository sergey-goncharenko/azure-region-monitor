from __future__ import annotations

import json
import re
import time

from azure_region_monitor.config import (
    DEFAULT_FUNCTION_RUNTIME_FEATURES,
    FunctionRuntimeFeature,
)
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


class FunctionsFlexConsumptionCliProbe:
    name = "function-flex-cli"

    def __init__(
        self,
        runtime_features: list[FunctionRuntimeFeature] | None = None,
        cli_runner: CliRunner | None = None,
    ) -> None:
        self._runtime_features = runtime_features or DEFAULT_FUNCTION_RUNTIME_FEATURES
        self._cli_runner = cli_runner or run_az
        self._flex_locations: tuple[set[str], AzureCliError | None] | None = None
        self._linux_runtimes: tuple[set[str], AzureCliError | None] | None = None

    def run(self, region: str):
        started = time.perf_counter()
        flex_locations, flex_error = self._list_flex_locations()
        linux_runtimes, runtime_error = self._list_linux_runtimes()
        latency_ms = round((time.perf_counter() - started) * 1000)

        normalized_region = _normalize_location(region)
        flex_available = normalized_region in flex_locations

        yield ProbeResult(
            service="functions",
            feature="hostingPlans.flexConsumption",
            result=_hosting_result(region, flex_available, flex_error, latency_ms),
        )

        for runtime_feature in self._runtime_features:
            yield ProbeResult(
                service="functions",
                feature=runtime_feature.feature,
                result=_runtime_result(
                    region=region,
                    runtime_feature=runtime_feature,
                    flex_available=flex_available,
                    flex_error=flex_error,
                    runtime_error=runtime_error,
                    linux_runtimes=linux_runtimes,
                    latency_ms=latency_ms,
                ),
            )

    def _list_flex_locations(self) -> tuple[set[str], AzureCliError | None]:
        if self._flex_locations is None:
            self._flex_locations = self._run_json_command(
                [az_executable(), "functionapp", "list-flexconsumption-locations", "--output", "json"],
                _extract_flex_locations,
            )
        return self._flex_locations

    def _list_linux_runtimes(self) -> tuple[set[str], AzureCliError | None]:
        if self._linux_runtimes is None:
            self._linux_runtimes = self._run_json_command(
                [az_executable(), "functionapp", "list-runtimes", "--os", "linux", "--output", "json"],
                _extract_runtime_tokens,
            )
        return self._linux_runtimes

    def _run_json_command(self, command: list[str], extractor) -> tuple[set[str], AzureCliError | None]:
        try:
            completed = self._cli_runner(command)
        except FileNotFoundError:
            return set(), AzureCliError("AzureCliNotFound", "Azure CLI executable 'az' was not found.")

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Azure CLI command failed.").strip()
            return set(), AzureCliError("AzureCliCommandFailed", message)

        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as error:
            return set(), AzureCliError("AzureCliInvalidJson", str(error))

        return extractor(payload), None


def _hosting_result(
    region: str,
    flex_available: bool,
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
    if flex_available:
        return FeatureResult(
            status="available",
            latency_ms=latency_ms,
            message=f"Azure Functions Flex Consumption is listed in {region}.",
        )
    return FeatureResult(
        status="unavailable",
        latency_ms=latency_ms,
        message=f"Azure Functions Flex Consumption was not listed in {region}.",
    )


def _runtime_result(
    region: str,
    runtime_feature: FunctionRuntimeFeature,
    flex_available: bool,
    flex_error: AzureCliError | None,
    runtime_error: AzureCliError | None,
    linux_runtimes: set[str],
    latency_ms: int,
) -> FeatureResult:
    error = flex_error or runtime_error
    if error:
        return FeatureResult(
            status="unknown",
            latency_ms=latency_ms,
            error_code=error.error_code,
            message=error.message,
        )

    if not flex_available:
        return FeatureResult(
            status="unavailable",
            latency_ms=latency_ms,
            message=(
                f"Runtime '{runtime_feature.runtime}' is not marked available in {region} "
                "because Flex Consumption is not listed there."
            ),
        )

    if _runtime_is_listed(runtime_feature.runtime, linux_runtimes):
        return FeatureResult(
            status="available",
            latency_ms=latency_ms,
            message=f"Linux Functions runtime '{runtime_feature.runtime}' is listed for Flex checks.",
        )

    return FeatureResult(
        status="unavailable",
        latency_ms=latency_ms,
        message=f"Linux Functions runtime '{runtime_feature.runtime}' was not listed by Azure CLI.",
    )


def _extract_flex_locations(payload: object) -> set[str]:
    locations: set[str] = set()
    _collect_locations(payload, locations)
    return locations


def _collect_locations(value: object, locations: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_locations(item, locations)
        return
    if isinstance(value, str):
        normalized = _normalize_location(value)
        if normalized:
            locations.add(normalized)
        return
    if not isinstance(value, dict):
        return

    for key in ("name", "location", "displayName", "regionalDisplayName"):
        raw_location = value.get(key)
        if isinstance(raw_location, str):
            normalized = _normalize_location(raw_location)
            if normalized:
                locations.add(normalized)


def _extract_runtime_tokens(payload: object) -> set[str]:
    runtimes: set[str] = set()
    _collect_runtime_tokens(payload, runtimes)
    return runtimes


def _collect_runtime_tokens(value: object, runtimes: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_runtime_tokens(item, runtimes)
        return
    if isinstance(value, str):
        normalized = _normalize_runtime(value)
        if "|" in normalized:
            runtimes.add(normalized)
        return
    if not isinstance(value, dict):
        return

    runtime_name = value.get("name") or value.get("runtime")
    runtime_version = value.get("version") or value.get("runtimeVersion")
    if isinstance(runtime_name, str) and isinstance(runtime_version, str):
        runtimes.add(_normalize_runtime(f"{runtime_name}|{runtime_version}"))

    for key in ("runtimeVersion", "linuxFxVersion", "linuxRuntime", "supportedRuntime"):
        raw_runtime = value.get(key)
        if isinstance(raw_runtime, str):
            normalized = _normalize_runtime(raw_runtime)
            if "|" in normalized:
                runtimes.add(normalized)

    for nested_value in value.values():
        _collect_runtime_tokens(nested_value, runtimes)


def _runtime_is_listed(expected_runtime: str, listed_runtimes: set[str]) -> bool:
    normalized = _normalize_runtime(expected_runtime)
    return any(runtime == normalized or runtime.startswith(f"{normalized}.") for runtime in listed_runtimes)


def _normalize_location(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _normalize_runtime(value: str) -> str:
    normalized = value.strip().replace(":", "|").lower()
    return re.sub(r"\s+", "", normalized)