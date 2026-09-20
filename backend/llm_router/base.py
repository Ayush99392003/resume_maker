"""Shared types and protocol for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    raw: Any = None
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Provider interface — every backend implements chat()."""

    name: str

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.4,
        response_format: str | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        response_format: None | "json" — request JSON when supported.
        """
        raise NotImplementedError

    @abstractmethod
    def chat_model(
        self,
        messages: list[ChatMessage],
        response_model: type[BaseModel],
        *,
        model: str,
        temperature: float = 0.4,
    ) -> BaseModel:
        """Send a chat completion request returning a Pydantic model."""
        raise NotImplementedError

    def ensure_configured(self) -> None:
        """Raise ValueError if required credentials are missing."""
        raise NotImplementedError
