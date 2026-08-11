# AGENTS.md — Resume Maker Agent Architecture & Workspace Guidelines

This document outlines the multi-agent architecture of **Resume Maker** as well as the rules and guidelines for AI agents working in this repository.

---

## 1. Multi-Agent System Architecture

Resume Maker uses a hierarchical multi-agent orchestration pipeline to parse, generate, refine, and compile LaTeX resumes into numbered zones.

```
                  ┌───────────────────────────────┐
                  │      User Chat Request        │
                  └──────────────┬────────────────┘
                                 │
                                 ▼
                  ┌───────────────────────────────┐
                  │    Chat Router (Classifier)   │
                  │  (direct_reply vs orchestrator)│
                  └──────────────┬────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
                 ▼                               ▼
      ┌────────────────────┐          ┌──────────────────────┐
      │ Direct Reply Agent │          │     Orchestrator     │
      └────────────────────┘          └──────────┬───────────┘
                                                 │
      ┌──────────────────────────────────────────┼──────────────────────────────────────────┐
      │                                          │                                          │
      ▼                                          ▼                                          ▼
┌──────────────┐                       ┌───────────────────┐                      ┌───────────────────┐
│ Zone Router  │                       │ Zone Add/Del/Move │                      │  LaTeX Fixer Agent│
└──────┬───────┘                       └───────────────────┘                      └───────────────────┘
       │
       ├───────────────┬───────────────┬───────────────┬───────────────┐
       ▼               ▼               ▼               ▼               ▼
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│ Header Agent ││Summary Agent ││Exper. Agent  ││Edu. Agent    ││Skills Agent  │
└──────────────┘└──────────────┘└──────────────┘└──────────────┘└──────────────┘
```

### Agent Roles & Components

| Agent / Module | Location | Purpose |
|----------------|----------|---------|
| **Chat Router** | `backend/core/chat_router.py` | Top-level classifier. Determines whether a prompt is conversational (`direct_reply`) or requires document manipulation (`orchestrator`). |
| **Orchestrator** | `backend/core/orchestrator.py` | Manages complex document plans, step execution, zone creation/deletion/reordering, and state synchronization. |
| **Zone Router & Specialists** | `backend/core/zone_agents/` | Routes edit tasks to domain specialists: `HeaderAgent`, `SummaryAgent`, `ExperienceAgent`, `EducationAgent`, and `SkillsAgent`. |
| **AI Fixer / Repair Agent** | `backend/core/ai_agent.py` | Auto-heals LaTeX syntax errors when Tectonic compilation fails, attempting up to `max_retries` fixes. |
| **LLM Router** | `backend/llm_router/` | Multi-provider abstraction supporting OpenAI, Groq, Gemini, Anthropic, Azure OpenAI, and AWS Bedrock. |

---

## 2. Workspace Coding & Behavioral Rules

When contributing code or modifying this repository, AI agents must strictly adhere to the following rules:

### Python & Formatting
- **PEP 8 Compliance**: Strictly comply with PEP 8 naming, imports, and structure.
- **Line Length**: Maximum line length of **79 characters** for Python files.
- **Formatter/Linter**: Use `ruff` or `black` for formatting and `ruff` for linting.
- **Type Hints**: Include type annotations on all public functions and methods (checked via `mypy`).

### Environment & Tooling
- **Dependency Management**: Use `uv` exclusively for dependency and environment operations.
  - Run scripts: `uv run script.py`
  - Manage packages: `uv add <package>` / `uv remove <package>`
  - Sync environment: `uv sync`
- **Virtual Environment**: Keep `.venv` gitignored; never commit virtual environment files.

### LLM Integrations
- **Response API**: All OpenAI calls must use `openai.responses.create()` (not `chat.completions`).
- **Centralized Routing**: Delegate all model requests through `backend/llm_router`.

### Tracing & Telemetry (Arize Phoenix)
- **OpenTelemetry Export**: Trace all LLM calls using `arize-phoenix-otel`.
- **Collector Endpoint**: Read from `PHOENIX_COLLECTOR_ENDPOINT` (default: `http://localhost:6006/v1/traces`).
- **Required Span Attributes**:
  - `span.name = "openai.responses.create"`
  - `span.set_attribute("llm.model", model_name)`
  - `span.set_attribute("llm.input_messages", ...)`
  - `span.set_attribute("llm.output_messages", ...)`
  - `span.set_attribute("session.id", session_id)`

### Logging & Diagnostics
- **Rich Output**: Use `rich.logging` and `rich.console.Console` for all terminal logging.
- **No Bare Prints**: Avoid `print()` statements in production code.
- **Error Context**: Log actionable error summaries. Tracebacks should be logged only in debug mode or stored in app log files (`backend/data/logs/app.log`).

### Compilation & Resilience
- **Soft-Fail Compilation**: Always handle Tectonic compile failures gracefully by returning `compile_error` details to the user/UI without corrupting session LaTeX state.
- **TeX Softener**: Run Overleaf `.tex` imports through `backend/core/latex_soften.py` to replace fragile TeX packages (e.g. `fontawesome5`, `contour`) before Tectonic execution.

---

## 3. How to Run & Test

```powershell
# Activate virtual environment and run backend
cd backend
uv run python main.py

# Run test suite
backend\.venv\Scripts\pytest.exe
```
