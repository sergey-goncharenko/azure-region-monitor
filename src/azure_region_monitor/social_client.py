from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_MAX_OUTPUT_TOKENS = 1_200


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
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._opener = opener or urllib.request.build_opener()

    @classmethod
    def from_env(
        cls,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
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
        )

    def generate(self, *, system: str, user: str) -> str:
        payload = {
            "model": self._deployment,
            "instructions": system,
            "input": user,
            "max_output_tokens": self._max_output_tokens,
            "reasoning": {"effort": "low"},
        }
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
            raise RuntimeError(f"Azure OpenAI social draft request failed: HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, http.client.HTTPException, OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Azure OpenAI social draft request failed: {error}") from error

        text = _response_text(body)
        if not text:
            raise RuntimeError("Azure OpenAI social draft response did not contain output text.")
        return text

    def _responses_url(self) -> str:
        if self._endpoint.endswith("/openai/v1"):
            return f"{self._endpoint}/responses"
        return f"{self._endpoint}/openai/v1/responses"


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
