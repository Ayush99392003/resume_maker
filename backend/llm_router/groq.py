"""Groq Cloud provider (OpenAI-compatible API)."""

from __future__ import annotations

import os
from typing import Any, List, Optional

from .base import ChatMessage, LLMProvider, LLMResponse


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self._client: Any = None

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY is required when LLM_PROVIDER=groq"
            )

    @property
    def client(self):
        if self._client is None:
            self.ensure_configured()
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ImportError("Install openai: pip install openai") from e
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1",
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
        kwargs = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
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
            model=model,
            raw=resp,
            usage=usage,
        )
