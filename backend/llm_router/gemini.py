"""Google Gemini provider."""

from __future__ import annotations

import os
from typing import List, Optional

from .base import ChatMessage, LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._configured = False

    def _genai(self):
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "Install google-generativeai: pip install google-generativeai"
            ) from e
        return genai

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=gemini"
            )
        if not self._configured:
            genai = self._genai()
            genai.configure(api_key=self.api_key)
            self._configured = True

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        model: str,
        temperature: float = 0.4,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        self.ensure_configured()
        genai = self._genai()

        system_parts = [m.content for m in messages if m.role == "system"]
        history = []
        for m in messages:
            if m.role == "system":
                continue
            role = "user" if m.role == "user" else "model"
            # Gemini alternates user/model; merge consecutive same roles
            if history and history[-1]["role"] == role:
                history[-1]["parts"][0] += "\n" + m.content
            else:
                history.append({"role": role, "parts": [m.content]})

        generation_config = {"temperature": temperature}
        if response_format == "json":
            generation_config["response_mime_type"] = "application/json"

        gm = genai.GenerativeModel(
            model_name=model,
            system_instruction="\n\n".join(system_parts) if system_parts else None,
            generation_config=generation_config,
        )

        if not history:
            raise ValueError("No user/assistant messages provided to Gemini")

        # Last message is the prompt; prior are history
        if len(history) == 1:
            resp = gm.generate_content(history[0]["parts"][0])
        else:
            chat = gm.start_chat(history=history[:-1])
            resp = chat.send_message(history[-1]["parts"][0])

        content = getattr(resp, "text", None) or ""
        return LLMResponse(
            content=content,
            provider=self.name,
            model=model,
            raw=resp,
        )
