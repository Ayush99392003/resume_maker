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
    """Routes chat calls to an explicitly selected provider and tracks token/call metrics."""

    def __init__(self):
        self._call_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def get_metrics(self) -> Dict[str, int]:
        """Return cumulative call count and token usage dict."""
        return {
            "call_count": self._call_count,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": self._prompt_tokens + self._completion_tokens,
        }

    def reset_metrics(self) -> Dict[str, int]:
        """Reset and return previous token and call count metrics."""
        prev = self.get_metrics()
        self._call_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        return prev

    def default_provider(self) -> str:
        return os.getenv("LLM_PROVIDER", "groq").strip().lower()

    def default_model(self) -> str:
        return os.getenv("MODEL_NAME", "openai/gpt-oss-120b").strip()

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

    def make_provider_from_config(
        self,
        provider: str,
        cfg: "ProviderConfig",  # type: ignore[name-defined]
    ) -> LLMProvider:
        """Build a fully-configured provider from a ProviderConfig object.

        Used for per-user credential injection — all provider-specific
        fields (Azure endpoint, AWS credentials, etc.) flow through here.
        """
        p = provider.strip().lower()
        if p == "azure":
            return AzureProvider(
                api_key=(cfg.api_key or "").strip() or None,
                endpoint=(cfg.endpoint or "").strip() or None,
                deployment=(cfg.deployment or "").strip() or None,
                api_version=(cfg.api_version or "2024-02-01").strip(),
            )
        if p == "aws":
            return AWSProvider(
                access_key_id=(cfg.access_key_id or "").strip() or None,
                secret_access_key=(
                    cfg.secret_access_key or ""
                ).strip() or None,
                region=(cfg.region or "us-east-1").strip(),
                model_id=(cfg.model_id or "").strip() or None,
            )
        # Simple key providers: openai / groq / gemini / anthropic
        return self.make_provider(p, api_key=(cfg.api_key or "").strip() or None)

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
        resp = prov.chat(
            messages,
            model=model_name,
            temperature=temperature,
            response_format=response_format,
        )
        self._call_count += 1
        if resp.usage:
            self._prompt_tokens += resp.usage.get("prompt_tokens", 0)
            self._completion_tokens += resp.usage.get("completion_tokens", 0)
        return resp

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
