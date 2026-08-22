from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_MAX_OUTPUT_TOKENS = 1_200
MICROSOFT_LEARN_MCP_URL = "https://learn.microsoft.com/api/mcp?maxTokenBudget=2000"
MICROSOFT_LEARN_MCP_TOOLS = ("microsoft_docs_search", "microsoft_docs_fetch")
MAX_MICROSOFT_LEARN_URLS = 20


class AzureOpenAiTextClient:
    """Generates structured text from an Azure OpenAI Responses deployment."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        deployment: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        enable_microsoft_learn_mcp: bool = False,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._enable_microsoft_learn_mcp = enable_microsoft_learn_mcp
        self._opener = opener or urllib.request.build_opener()
        self._generation_metadata: dict[str, object] = {
            "narrative_mcp_status": "available" if enable_microsoft_learn_mcp else "disabled",
            "narrative_mcp_error": None,
            "narrative_grounding_status": "scan_facts_only",
            "narrative_microsoft_learn_urls": [],
        }

    @classmethod
    def from_env(
        cls,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        enable_microsoft_learn_mcp: bool = False,
    ) -> "AzureOpenAiTextClient":
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        missing = [
            name
            for name, value in (
                ("AZURE_OPENAI_API_KEY", api_key),
                ("AZURE_OPENAI_ENDPOINT", endpoint),
                ("AZURE_OPENAI_DEPLOYMENT", deployment),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing Azure text-generation configuration: {', '.join(missing)}")
        return cls(
            api_key=api_key,
            endpoint=endpoint,
            deployment=deployment,
            timeout_seconds=int(os.environ.get("AI_SOCIAL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
            max_output_tokens=max_output_tokens,
            enable_microsoft_learn_mcp=enable_microsoft_learn_mcp,
        )

    def generate(self, *, system: str, user: str) -> str:
        payload = {
            "model": self._deployment,
            "instructions": system,
            "input": user,
            "max_output_tokens": self._max_output_tokens,
            "reasoning": {"effort": "low"},
        }
        if self._enable_microsoft_learn_mcp:
            payload["tools"] = [
                {
                    "type": "mcp",
                    "server_label": "microsoft_learn",
                    "server_url": MICROSOFT_LEARN_MCP_URL,
                    "allowed_tools": list(MICROSOFT_LEARN_MCP_TOOLS),
                    "require_approval": "never",
                }
            ]
        request = urllib.request.Request(
            self._responses_url(),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Azure OpenAI social draft request failed: HTTP {error.code}: {detail}"
            ) from error
        except (urllib.error.URLError, http.client.HTTPException, OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Azure OpenAI social draft request failed: {error}") from error

        self._record_grounding(body)
        if self._generation_metadata["narrative_mcp_status"] == "failed":
            raise RuntimeError(
                f"Microsoft Learn MCP request failed: {self._generation_metadata['narrative_mcp_error']}"
            )
        text = _response_text(body)
        if not text:
            raise RuntimeError("Azure OpenAI social draft response did not contain output text.")
        return text

    @property
    def deployment(self) -> str:
        """Return the configured deployment name without exposing credentials."""
        return self._deployment

    @property
    def generation_metadata(self) -> dict[str, object]:
        """Expose non-sensitive generation provenance to the history writer."""
        return dict(self._generation_metadata)

    def _responses_url(self) -> str:
        if self._endpoint.endswith("/openai/v1"):
            return f"{self._endpoint}/responses"
        return f"{self._endpoint}/openai/v1/responses"

    def _record_grounding(self, payload: object) -> None:
        if not self._enable_microsoft_learn_mcp:
            return
        status, error, urls = _microsoft_learn_mcp_result(payload)
        self._generation_metadata.update(
            {
                "narrative_mcp_status": status,
                "narrative_mcp_error": error,
                "narrative_grounding_status": "microsoft_learn" if status == "consulted" and urls else "scan_facts_only",
                "narrative_microsoft_learn_urls": urls,
            }
        )


def _response_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _microsoft_learn_mcp_result(payload: object) -> tuple[str, str | None, list[str]]:
    if not isinstance(payload, dict):
        return "available", None, []
    output = payload.get("output")
    if not isinstance(output, list):
        return "available", None, []

    urls: set[str] = set()
    for item in output:
        if not isinstance(item, dict) or item.get("server_label") != "microsoft_learn":
            continue
        item_type = item.get("type")
        if item_type == "mcp_approval_request":
            return "failed", "approval_requested", []
        if item_type in {"mcp_error", "mcp_call"} and (
            item_type == "mcp_error"
            or item.get("error")
            or item.get("status") in {"cancelled", "error", "failed", "incomplete"}
        ):
            return "failed", _mcp_error_name(item), []
        if item_type == "mcp_call":
            urls.update(_microsoft_learn_urls(item.get("result")))

    ordered_urls = sorted(urls)[:MAX_MICROSOFT_LEARN_URLS]
    return ("consulted" if urls else "available"), None, ordered_urls


def _mcp_error_name(item: dict[str, object]) -> str:
    error = item.get("error")
    if isinstance(error, dict):
        error_type = error.get("type") or error.get("code")
        if isinstance(error_type, str) and error_type:
            return error_type[:120]
    if isinstance(error, str) and error:
        return error[:120]
    status = item.get("status")
    return status if isinstance(status, str) else "tool_error"


def _microsoft_learn_urls(value: object) -> set[str]:
    if isinstance(value, str):
        parsed = urlparse(value)
        if (
            parsed.scheme == "https"
            and parsed.netloc == "learn.microsoft.com"
            and parsed.path
            and parsed.path != "/api/mcp"
        ):
            return {value}
        return set()
    if isinstance(value, list):
        return set().union(*(_microsoft_learn_urls(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_microsoft_learn_urls(item) for item in value.values()))
    return set()
