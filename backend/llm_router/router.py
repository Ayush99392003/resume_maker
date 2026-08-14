"""Explicit LLM router — selects provider from LLM_PROVIDER / overrides."""

from __future__ import annotations

import os
from pydantic import BaseModel
from typing import Dict, List, Optional, Type

from .anthropic_provider import AnthropicProvider
from .aws import AWSProvider
from .azure import AzureProvider
from .base import ChatMessage, LLMProvider, LLMResponse
from .gemini import GeminiProvider
from .groq import GroqProvider
from .openai_provider import OpenAIProvider

SUPPORTED_PROVIDERS = (
    "openai",
    "groq",
    "gemini",
    "anthropic",
    "azure",
    "aws",
)


class LLMRouter:
    """Routes chat calls to an explicitly selected provider."""

    def default_provider(self) -> str:
        return os.getenv("LLM_PROVIDER", "groq").strip().lower()

    def default_model(self) -> str:
        return os.getenv("MODEL_NAME", "llama-3.3-70b-versatile").strip()

    def make_provider(
        self,
        name: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
    ) -> LLMProvider:
        """Build a provider instance; request api_key overrides env."""
        provider_name = (name or self.default_provider()).strip().lower()
        key = (api_key or "").strip() or None

        if provider_name == "openai":
            return OpenAIProvider(api_key=key)
        if provider_name == "groq":
            return GroqProvider(api_key=key)
        if provider_name == "gemini":
            return GeminiProvider(api_key=key)
        if provider_name == "anthropic":
            return AnthropicProvider(api_key=key)
        if provider_name == "azure":
            return AzureProvider(api_key=key)
        if provider_name == "aws":
            return AWSProvider()
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    def get_provider(
        self,
        name: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
    ) -> LLMProvider:
        provider = self.make_provider(name, api_key=api_key)
        provider.ensure_configured()
        return provider

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.4,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        prov = self.get_provider(provider, api_key=api_key)
        model_name = (model or self.default_model()).strip()
        if not model_name:
            raise ValueError("MODEL_NAME is required")
        return prov.chat(
            messages,
            model=model_name,
            temperature=temperature,
            response_format=response_format,
        )

    def chat_model(
        self,
        messages: List[ChatMessage],
        response_model: Type[BaseModel],
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.4,
    ) -> BaseModel:
        prov = self.get_provider(provider, api_key=api_key)
        model_name = (model or self.default_model()).strip()
        if not model_name:
            raise ValueError("MODEL_NAME is required")
        return prov.chat_model(
            messages,
            response_model,
            model=model_name,
            temperature=temperature,
        )

    def list_configured(self) -> Dict[str, bool]:
        """Return which providers have credentials available (best-effort)."""
        checks = {
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "gemini": bool(os.getenv("GEMINI_API_KEY")),
            "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
            "azure": bool(
                os.getenv("AZURE_OPENAI_API_KEY")
                and os.getenv("AZURE_OPENAI_ENDPOINT")
                and os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
            ),
            "aws": bool(
                os.getenv("AWS_ACCESS_KEY_ID")
                and os.getenv("AWS_SECRET_ACCESS_KEY")
            ),
        }
        return checks


# Singleton
llm_router = LLMRouter()
