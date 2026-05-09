from __future__ import annotations

import os
import signal
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

CliRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AzureCliError:
    error_code: str
    message: str


def run_az(command: list[str]) -> subprocess.CompletedProcess[str]:
    timeout_seconds = int(os.environ.get("AZURE_CLI_TIMEOUT_SECONDS", "90"))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _kill_process(process)
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=stdout or error.stdout or "",
            stderr=f"Azure CLI command timed out after {timeout_seconds} seconds.",
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _kill_process(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        process.kill()
        return
    os.killpg(process.pid, signal.SIGKILL)


def az_executable() -> str:
    return shutil.which("az") or shutil.which("az.cmd") or "az"
