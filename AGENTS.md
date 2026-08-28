AGENTS.md — Resume Maker
Architecture

Resume Maker is a hierarchical multi-agent pipeline:

User → Chat Router → Direct Reply | Orchestrator

The Orchestrator manages document plans, zone creation/deletion/reordering, execution, and state sync. It delegates to:

Zone Router: backend/core/zone_agents/
HeaderAgent
SummaryAgent
ExperienceAgent
EducationAgent
SkillsAgent
LaTeX Fixer: backend/core/ai_agent.py
Repairs Tectonic compilation errors, up to max_retries.
LLM Router: backend/llm_router/
Supports OpenAI, Groq, Gemini, Anthropic, Azure OpenAI, AWS Bedrock.

Chat Router: backend/core/chat_router.py — classifies requests as direct_reply or orchestrator.

Orchestrator: backend/core/orchestrator.py — executes complex document operations and synchronizes state.

Coding Rules
Python must follow PEP 8, max 79 chars/line.
Use ruff/black; use ruff for linting.
Add type hints to all public functions/methods; maintain mypy compatibility.
Use uv exclusively for dependencies/environment:
uv run ...
uv add/remove ...
uv sync
.venv must remain gitignored.
LLM Rules
OpenAI calls must use openai.responses.create(), never
chat.completions.
Route all model requests through backend/llm_router.
Trace LLM calls with arize-phoenix-otel.
Collector: PHOENIX_COLLECTOR_ENDPOINT, default
<http://localhost:6006/v1/traces>.
Required span attributes:
span.name = "openai.responses.create"
llm.model
llm.input_messages
llm.output_messages
session.id
Logging & Compilation
Use rich.logging and rich.console.Console.
No bare print() in production.
Log actionable errors; tracebacks only in debug mode or app logs.
Tectonic failures must soft-fail: return compile_error details without
corrupting session LaTeX state.
Process Overleaf .tex imports through
backend/core/latex_soften.py before Tectonic to replace fragile packages
such as fontawesome5 and contour.
Run & Test
cd backend
uv run python main.py

backend\.venv\Scripts\pytest.exe
