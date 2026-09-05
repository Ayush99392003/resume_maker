"""Google Gemini provider using google-genai SDK and Interactions API."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple, Type
from pydantic import BaseModel

from .base import ChatMessage, LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self.ensure_configured()
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=gemini"
            )

    def _prepare_messages(
        self, messages: List[ChatMessage]
    ) -> Tuple[Optional[str], str]:
        sys_parts = [m.content for m in messages if m.role == "system"]
        sys_instruction = "\n\n".join(sys_parts) if sys_parts else None

        non_system = [m for m in messages if m.role != "system"]
        if not non_system:
            raise ValueError(
                "No user/assistant messages provided to Gemini"
            )

        if len(non_system) == 1:
            input_text = non_system[0].content
        else:
            turns = []
            for m in non_system[:-1]:
                role = "User" if m.role == "user" else "Assistant"
                turns.append(f"{role}: {m.content}")
            input_text = (
                "Previous conversation:\n"
                + "\n".join(turns)
                + f"\n\nCurrent request:\n{non_system[-1].content}"
            )
        return sys_instruction, input_text

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        model: str,
        temperature: float = 0.4,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        client = self._get_client()
        sys_instruction, input_text = self._prepare_messages(messages)

        resolved_model = model or "gemini-3.5-flash-lite"
        if resolved_model.startswith("models/"):
            resolved_model = resolved_model[len("models/"):]

        kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "input": input_text,
        }
        if sys_instruction:
            kwargs["system_instruction"] = sys_instruction

        if response_format == "json":
            kwargs["response_format"] = {"type": "object"}

        res = client.interactions.create(**kwargs)
        content = getattr(res, "output_text", "") or ""

        usage: Dict[str, Any] = {}
        if hasattr(res, "usage") and res.usage:
            u = res.usage
            usage = {
                "prompt_tokens": getattr(u, "total_input_tokens", 0),
                "completion_tokens": getattr(u, "total_output_tokens", 0),
            }

        return LLMResponse(
            content=content,
            provider=self.name,
            model=resolved_model,
            raw=res,
            usage=usage,
        )

    def chat_model(
        self,
        messages: List[ChatMessage],
        response_model: Type[BaseModel],
        *,
        model: str,
        temperature: float = 0.4,
    ) -> BaseModel:
        client = self._get_client()
        sys_instruction, input_text = self._prepare_messages(messages)

        resolved_model = model or "gemini-3.5-flash-lite"
        if resolved_model.startswith("models/"):
            resolved_model = resolved_model[len("models/"):]

        kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "input": input_text,
            "response_format": response_model.model_json_schema(),
        }
        if sys_instruction:
            kwargs["system_instruction"] = sys_instruction

        res = client.interactions.create(**kwargs)
        output_text = getattr(res, "output_text", "") or "{}"
        try:
            data = json.loads(output_text)
            return response_model.model_validate(data)
        except Exception:
            cleaned = output_text.strip()
            if cleaned.startswith("```"):
                cleaned = (
                    cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                )
            return response_model.model_validate_json(cleaned)

