"""AWS Bedrock provider via boto3 Converse API."""

from __future__ import annotations

import os
from typing import List, Optional

from .base import ChatMessage, LLMProvider, LLMResponse


class AWSProvider(LLMProvider):
    name = "aws"

    def __init__(
        self,
        region: Optional[str] = None,
        model_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
    ):
        self.region = (region or "").strip() or os.getenv(
            "AWS_REGION", "us-east-1"
        )
        self.default_model_id = (model_id or "").strip() or os.getenv(
            "AWS_BEDROCK_MODEL_ID"
        )
        # Explicit credentials override env vars / IAM role
        self._access_key_id = (access_key_id or "").strip() or None
        self._secret_access_key = (secret_access_key or "").strip() or None
        self._client = None

    def ensure_configured(self) -> None:
        # Accept explicit creds, env vars, IAM role, or shared credentials.
        access = self._access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        secret = self._secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        if not access or not secret:
            # Allow IAM role / shared credentials; only warn via import check
            try:
                import boto3  # noqa: F401
            except ImportError as e:
                raise ImportError(
                    "Install boto3 package: pip install boto3"
                ) from e

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as e:
                raise ImportError(
                    "Install boto3 package: pip install boto3"
                ) from e
            kwargs: dict = {"region_name": self.region}
            if self._access_key_id and self._secret_access_key:
                kwargs["aws_access_key_id"] = self._access_key_id
                kwargs["aws_secret_access_key"] = self._secret_access_key
            self._client = boto3.client("bedrock-runtime", **kwargs)
        return self._client

    def chat(
        self,
        messages: List[ChatMessage],
        *,
        model: str,
        temperature: float = 0.4,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        self.ensure_configured()
        model_id = model or self.default_model_id
        if not model_id:
            raise ValueError(
                "AWS Bedrock model id required "
                "(MODEL_NAME or AWS_BEDROCK_MODEL_ID)"
            )

        system = [
            {"text": m.content} for m in messages if m.role == "system"
        ]
        converse_messages = []
        for m in messages:
            if m.role == "system":
                continue
            role = "assistant" if m.role == "assistant" else "user"
            text = m.content
            if (
                response_format == "json"
                and role == "user"
                and m is messages[-1]
            ):
                text += "\n\nRespond with a single valid JSON object only."
            if converse_messages and converse_messages[-1]["role"] == role:
                converse_messages[-1]["content"][0]["text"] += "\n" + text
            else:
                converse_messages.append(
                    {"role": role, "content": [{"text": text}]}
                )

        kwargs = {
            "modelId": model_id,
            "messages": converse_messages,
            "inferenceConfig": {"temperature": temperature},
        }
        if system:
            kwargs["system"] = system

        resp = self.client.converse(**kwargs)
        content = ""
        for block in resp.get("output", {}).get("message", {}).get(
            "content", []
        ):
            if "text" in block:
                content += block["text"]

        usage = resp.get("usage", {})
        return LLMResponse(
            content=content,
            provider=self.name,
            model=model_id,
            raw=resp,
            usage={
                "prompt_tokens": usage.get("inputTokens"),
                "completion_tokens": usage.get("outputTokens"),
            },
        )
