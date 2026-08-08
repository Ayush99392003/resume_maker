"""Anthropic Claude provider."""

from __future__ import annotations

import os
from typing import List, Optional

from .base import ChatMessage, LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic"
            )

    @property
    def client(self):
        if self._client is None:
            self.ensure_configured()
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise ImportError(
                    "Install anthropic package: pip install anthropic"
                ) from e
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        model: str,
        temperature: float = 0.4,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        system = "\n\n".join(
            m.content for m in messages if m.role == "system"
        )
        api_messages = []
        for m in messages:
            if m.role == "system":
                continue
            role = "assistant" if m.role == "assistant" else "user"
            content = m.content
            if response_format == "json" and role == "user" and m is messages[-1]:
                content = (
                    content
                    + "\n\nRespond with a single valid JSON object only."
                )
            if api_messages and api_messages[-1]["role"] == role:
                api_messages[-1]["content"] += "\n" + content
            else:
                api_messages.append({"role": role, "content": content})

        kwargs = {
            "model": model,
            "max_tokens": 8192,
            "temperature": temperature,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system

        resp = self.client.messages.create(**kwargs)
        content = ""
        for block in resp.content:
            if hasattr(block, "text"):
                content += block.text

        usage = {}
        if getattr(resp, "usage", None):
            usage = {
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
            }
        return LLMResponse(
            content=content,
            provider=self.name,
            model=model,
            raw=resp,
            usage=usage,
        )
