import subprocess

from azure_region_monitor.config import parse_ai_model_features
from azure_region_monitor.probes.ai_models import AiModelCatalogCliProbe


def test_ai_model_probe_emits_all_listed_models_by_default():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        assert command[1:4] == ["cognitiveservices", "model", "list"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '[{"kind":"OpenAI","model":{"name":"gpt-4o","version":"2024-08-06",'
                '"publisher":"OpenAI","lifecycleStatus":"GenerallyAvailable",'
                '"skus":[{"name":"GlobalStandard"}]}}]'
            ),
            stderr="",
        )

    probe = AiModelCatalogCliProbe(cli_runner=cli_runner)

    results = list(probe.run("eastus"))

    assert results[0].service == "ai"
    assert results[0].feature == "aiModels.openai.gpt-4o.2024-08-06"
    assert results[0].result.status == "available"
    assert "GlobalStandard" in results[0].result.message


def test_ai_model_probe_marks_configured_model_unavailable_when_absent():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '[{"kind":"OpenAI","model":{"name":"gpt-4o-mini","version":"2024-07-18",'
                '"publisher":"OpenAI"}}]'
            ),
            stderr="",
        )

    probe = AiModelCatalogCliProbe(
        model_features=parse_ai_model_features("aiModels.openai.gpt-4o.2024-08-06=gpt-4o@2024-08-06"),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].feature == "aiModels.openai.gpt-4o.2024-08-06"
    assert results[0].result.status == "unavailable"


def test_ai_model_probe_matches_configured_model_with_publisher_prefix():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '[{"kind":"OpenAI","model":{"name":"gpt-4o","version":"2024-08-06",'
                '"publisher":"OpenAI"}}]'
            ),
            stderr="",
        )

    probe = AiModelCatalogCliProbe(
        model_features=parse_ai_model_features("aiModels.openai.gpt-4o.2024-08-06=OpenAI/gpt-4o@2024-08-06"),
        cli_runner=cli_runner,
    )

    results = list(probe.run("eastus"))

    assert results[0].result.status == "available"


def test_ai_model_probe_captures_cli_error_as_unknown():
    def cli_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="forbidden")

    probe = AiModelCatalogCliProbe(cli_runner=cli_runner)

    results = list(probe.run("eastus"))

    assert results[0].feature == "aiModelCatalog"
    assert results[0].result.status == "unknown"
    assert results[0].result.error_code == "AzureCliCommandFailed"


def test_parse_ai_model_features_defaults_to_all_models():
    assert parse_ai_model_features(None) == []
    assert parse_ai_model_features("all") == []


def test_parse_ai_model_features_from_environment_value():
    features = parse_ai_model_features(
        "aiModels.openai.gpt-4o.2024-08-06=gpt-4o@2024-08-06,"
        "aiModels.openai.text-embedding-3-large.1=text-embedding-3-large@1"
    )

    assert [feature.feature for feature in features] == [
        "aiModels.openai.gpt-4o.2024-08-06",
        "aiModels.openai.text-embedding-3-large.1",
    ]
    assert [feature.model for feature in features] == [
        "gpt-4o@2024-08-06",
        "text-embedding-3-large@1",
    ]