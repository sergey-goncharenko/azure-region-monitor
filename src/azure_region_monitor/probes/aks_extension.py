from __future__ import annotations

import os
import json
import time

from azure_region_monitor.config import AksExtensionFeature, DEFAULT_AKS_EXTENSION_FEATURES
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


_MIN_AKS_EXTENSION_AZ_CLI_TIMEOUT_SECONDS = 120


class AksExtensionCliProbe:
    name = "aks-extension-cli"

    def __init__(
        self,
        features: list[AksExtensionFeature] | None = None,
        cli_runner: CliRunner | None = None,
    ) -> None:
        self._features = features or DEFAULT_AKS_EXTENSION_FEATURES
        if cli_runner is not None:
            self._cli_runner = cli_runner
            return

        def cli_runner_with_min_timeout(command: list[str]):
            # Some workflows set AZURE_CLI_TIMEOUT_SECONDS too low for the
            # k8s-extension extension-types list command; enforce a minimum so
            # timeouts don't unnecessarily increase `unknown` results.
            timeout_seconds = int(os.environ.get("AZURE_CLI_TIMEOUT_SECONDS", "90"))
            if timeout_seconds >= _MIN_AKS_EXTENSION_AZ_CLI_TIMEOUT_SECONDS:
                return run_az(command)

            previous_timeout = os.environ.get("AZURE_CLI_TIMEOUT_SECONDS")
            os.environ["AZURE_CLI_TIMEOUT_SECONDS"] = str(_MIN_AKS_EXTENSION_AZ_CLI_TIMEOUT_SECONDS)
            try:
                return run_az(command)
            finally:
                if previous_timeout is None:
                    os.environ.pop("AZURE_CLI_TIMEOUT_SECONDS", None)
                else:
                    os.environ["AZURE_CLI_TIMEOUT_SECONDS"] = previous_timeout

        self._cli_runner = cli_runner_with_min_timeout

    def run(self, region: str):
        started = time.perf_counter()
        extension_types, error = self._list_extension_types(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        for feature in self._features:
            if error:
                yield ProbeResult(
                    service="aks",
                    feature=feature.feature,
                    result=FeatureResult(
                        status="unknown",
                        latency_ms=latency_ms,
                        error_code=error.error_code,
                        message=error.message,
                    ),
                )
                continue

            is_available = feature.extension_type.lower() in extension_types
            yield ProbeResult(
                service="aks",
                feature=feature.feature,
                result=FeatureResult(
                    status="available" if is_available else "unavailable",
                    latency_ms=latency_ms,
                    message=f"Checked AKS extension type '{feature.extension_type}' in {region}.",
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