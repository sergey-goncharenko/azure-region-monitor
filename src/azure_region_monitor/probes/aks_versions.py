from __future__ import annotations

import json
import time

from azure_region_monitor.config import DEFAULT_AKS_KUBERNETES_VERSION_PREFIXES
from azure_region_monitor.models import FeatureResult
from azure_region_monitor.probes.azure_cli import AzureCliError, CliRunner, az_executable, run_az
from azure_region_monitor.probes.base import ProbeResult


class AksKubernetesVersionCliProbe:
    name = "aks-version-cli"

    def __init__(
        self,
        version_prefixes: list[str] | None = None,
        cli_runner: CliRunner | None = None,
    ) -> None:
        self._version_prefixes = version_prefixes or DEFAULT_AKS_KUBERNETES_VERSION_PREFIXES
        self._cli_runner = cli_runner or run_az

    def run(self, region: str):
        started = time.perf_counter()
        versions, error = self._list_versions(region)
        latency_ms = round((time.perf_counter() - started) * 1000)

        for version_prefix in self._version_prefixes:
            feature = f"kubernetesVersions.{version_prefix}"
            if error:
                yield ProbeResult(
                    service="aks",
                    feature=feature,
                    result=FeatureResult(
                        status="unknown",
                        latency_ms=latency_ms,
                        error_code=error.error_code,
                        message=error.message,
                    ),
                )
                continue

            matching_versions = sorted(
                version for version in versions if _matches_version_prefix(version, version_prefix)
            )
            yield ProbeResult(
                service="aks",
                feature=feature,
                result=FeatureResult(
                    status="available" if matching_versions else "unavailable",
                    latency_ms=latency_ms,
                    message=_version_message(region, version_prefix, matching_versions),
                ),
            )

    def _list_versions(self, region: str) -> tuple[set[str], AzureCliError | None]:
        command = [
            az_executable(),
            "aks",
            "get-versions",
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
            if _is_unsupported_aks_versions_location(message):
                return set(), None
            return set(), AzureCliError("AzureCliCommandFailed", message)

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as error:
            return set(), AzureCliError("AzureCliInvalidJson", str(error))

        return _extract_versions(payload), None


def _is_unsupported_aks_versions_location(message: str) -> bool:
    normalized = message.lower()
    return "noregisteredproviderfound" in normalized and "locations/kubernetesversions" in normalized


def _matches_version_prefix(version: str, version_prefix: str) -> bool:
    return version == version_prefix or version.startswith(f"{version_prefix}.")


def _version_message(region: str, version_prefix: str, matching_versions: list[str]) -> str:
    if not matching_versions:
        return f"No AKS Kubernetes versions matching '{version_prefix}' were listed in {region}."
    return (
        f"AKS Kubernetes versions matching '{version_prefix}' in {region}: "
        f"{', '.join(matching_versions)}."
    )


def _extract_versions(payload: object) -> set[str]:
    versions: set[str] = set()
    _collect_versions(payload, versions)
    return versions


def _collect_versions(value: object, versions: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_versions(item, versions)
        return

    if not isinstance(value, dict):
        return

    for key in value:
        if isinstance(key, str) and key[:1].isdigit():
            versions.add(key)

    for key in ("orchestratorVersion", "kubernetesVersion", "version"):
        raw_version = value.get(key)
        if isinstance(raw_version, str) and raw_version[:1].isdigit():
            versions.add(raw_version)

    for nested_value in value.values():
        _collect_versions(nested_value, versions)
