"""Groq Cloud provider (OpenAI-compatible API)."""

from __future__ import annotations

import os
from typing import Any, List, Optional, Type
from pydantic import BaseModel

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

        import time
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
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
            except Exception as err:
                err_str = str(err).lower()
                if "response_format" in kwargs and ("json" in err_str or "400" in err_str):
                    kwargs.pop("response_format", None)
                    continue
                if ("429" in err_str or "rate_limit" in err_str or "rate limit" in err_str) and attempt < max_attempts - 1:
                    time.sleep(6.0 * (attempt + 1))
                    continue
                raise err

    def chat_model(
        self,
        messages: List[ChatMessage],
        response_model: Type[BaseModel],
        *,
        model: str,
        temperature: float = 0.4,
    ) -> BaseModel:
        import instructor
        client = instructor.from_openai(self.client)
        return client.chat.completions.create(
            model=model,
            response_model=response_model,
            messages=[
                {"role": m.role, "content": m.content} for m in messages
            ],
            temperature=temperature,
        )
