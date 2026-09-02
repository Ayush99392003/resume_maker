"""Application settings — credentials come from environment."""

from __future__ import annotations

import os

import dotenv

dotenv.load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

# Logging / debugging (Rich console + optional file)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_FILE = os.getenv("LOG_FILE", "")  # default set in logging_setup for dev
LOG_RICH = os.getenv("LOG_RICH", "1").strip()
LOG_LOCALS = os.getenv("LOG_LOCALS", "0").strip()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
# llama-3.1-8b-instant is always available on Groq free tier
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-120b").strip()

# Provider keys (read by llm_router)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_BEDROCK_MODEL_ID = os.getenv("AWS_BEDROCK_MODEL_ID")

# Optional Gemini configure for embeddings (ATS)
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        pass
