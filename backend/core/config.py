"""Application settings — credentials come from environment."""

from __future__ import annotations

import os

import dotenv

dotenv.load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile").strip()

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
