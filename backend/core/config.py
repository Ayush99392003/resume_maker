import os
import dotenv
import google.generativeai as genai
from openai import AzureOpenAI

dotenv.load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SESSION_SECRET = os.getenv("SESSION_SECRET")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

model = os.getenv("MODEL", "gemini")

client = None
if AZURE_OPENAI_API_KEY:
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        api_version="2024-02-01",
    )


def call_azure_openai(prompt: str) -> str:
    """Helper for Azure OpenAI calls."""
    if not client:
        return "Azure OpenAI not configured."
    response = client.responses.create(
        input=prompt,
    )
    return response.output_text


def call_gemini(prompt: str) -> str:
    """Helper for Gemini text-only calls."""
    model_instance = genai.GenerativeModel("gemini-1.5-flash")
    response = model_instance.generate_content(prompt)
    return response.text


def llm_call(prompt: str) -> str:
    if model == "azure":
        return call_azure_openai(prompt)
    else:
        return call_gemini(prompt)
