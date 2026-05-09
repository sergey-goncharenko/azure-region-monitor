import subprocess

from azure_region_monitor.probes import azure_cli


def test_run_az_returns_completed_process_on_timeout(monkeypatch):
    def slow_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setenv("AZURE_CLI_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(subprocess, "run", slow_run)

    completed = azure_cli.run_az(["az", "account", "show"])

    assert completed.returncode == 124
    assert completed.stderr == "Azure CLI command timed out after 1 seconds."