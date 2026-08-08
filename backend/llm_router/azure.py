"""Azure OpenAI provider."""

from __future__ import annotations

import os
from typing import Any, List, Optional

from .base import ChatMessage, LLMProvider, LLMResponse


class AzureProvider(LLMProvider):
    name = "azure"

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        deployment: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = deployment or os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_NAME"
        )
        self.api_version = api_version or os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-02-01"
        )
        self._client: Any = None

    def ensure_configured(self) -> None:
        missing = []
        if not self.api_key:
            missing.append("AZURE_OPENAI_API_KEY")
        if not self.endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not self.deployment:
            missing.append("AZURE_OPENAI_DEPLOYMENT_NAME")
        if missing:
            raise ValueError(
                "Missing Azure config: " + ", ".join(missing)
            )

    @property
    def client(self):
        if self._client is None:
            self.ensure_configured()
            try:
                from openai import AzureOpenAI
            except ImportError as e:
                raise ImportError("Install openai: pip install openai") from e
            self._client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
        return self._client

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        model: str,
        temperature: float = 0.4,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        # Azure uses deployment name; prefer env deployment, allow model override
        deployment = model or self.deployment
        kwargs = {
            "model": deployment,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "temperature": temperature,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        resp = self.client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        return LLMResponse(
            content=content,
            provider=self.name,
            model=deployment,
            raw=resp,
            usage=usage,
        )
