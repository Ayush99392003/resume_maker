# AI LaTeX Resume Maker

Chat-first, agentic resume builder: AI fills **dynamic LaTeX zones**, you iterate in chat, and the right panel toggles **Code / Render**. Multi-provider LLM routing (Groq, OpenAI, Gemini, Anthropic, Azure, AWS Bedrock) with durable sessions, login/profile API keys, and mid-chat model switching.

---

## 🚀 Key Features

- **Auth + Profile Key Store**: Register/login with local profile persistence (`auth_store.py`). Provider API keys stored server-side and never echoed raw to UI.
- **Overleaf Import & TeX Softener**: Paste any public Overleaf gallery or GitHub LaTeX resume URL (`overleaf_import.py`). The TeX softener ([`latex_soften.py`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/core/latex_soften.py)) converts crashy XeTeX/Font Awesome packages and normalizes Unicode characters for seamless Windows Tectonic compilation.
- **Hierarchical Agentic Architecture**: Chat Router classifies prompt intent → Orchestrator plans steps → Zone Specialist Agents edit target zones (`HEADER`, `SUMMARY`, `EXPERIENCE`, `EDUCATION`, `SKILLS`, `PROJECTS`).
- **Dynamic Numbered Zones**: `% ZONE:NAME:START` and `% ZONE:NAME:END` markers keep preamble, styling, and page layout fixed while agents safely edit section contents.
- **Pydantic Guardrails & Context-Aware Escaping**: Auto-escapes LaTeX special characters (`&`, `$`, `^`, `~`, `%`, `_`, `#`) without breaking math mode, while token-aware parsers prevent macro corruption.
- **Macro Fallback Resilience**: Built-in fallback stubs for `\cventry`, `\cvitem`, `\degree`, `\school`, `\resumeSubheading`, and custom list macros (`\resumeItemListStart`) ensure multi-template compatibility.
- **Atomic Session Snapshots & Soft-Fail Rollback**: Sessions snapshot prior to edits; if Tectonic fails compilation, session state cleanly rolls back to the last-known good render.
- **ATS Keyword & Embedding Scorer**: Hybrid keyword match + vector embedding cosine similarity using Google Gemini (`ats_scorer.py`).

---

## 🏛️ System Architecture

```text
frontend (React / Vite on :3000)
    ↓ API Proxy (/api -> http://localhost:8001)
FastAPI Backend (backend/main.py on :8001)
    ├── auth_store (Profiles, Tokens & Keys)
    ├── session_store (Chat History & Zone Documents with Snapshots)
    ├── chat_router & orchestrator (Intent Routing & Step Planning)
    ├── zone_agents (Header, Summary, Experience, Education, Skills, Projects)
    ├── latex_soften (TeX Package, Unicode & Macro Compatibility Transformer)
    ├── line_indexer (Bottom-Up Error Localization for AI Fixer)
    ├── llm_router (OpenAI, Groq, Gemini, Anthropic, Azure, AWS Bedrock)
    └── compiler (Windows Tectonic CLI Compiler & Auto-Fixer Loop)
```

For detailed agent design specs and workspace rules, see [`AGENTS.md`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/AGENTS.md).

---

## 🛠️ Setup & Local Development

### Prerequisites

- **Python 3.11+** with [`uv`](https://github.com/astral-sh/uv) package manager
- **Node.js 18+**
- **Tectonic CLI**: Place `tectonic.exe` in [`backend/bin/`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/bin) or ensure Tectonic is available on system `PATH`.
- At least one provider API key (Groq recommended).

### Environment Configuration

Copy `.env.template` → `.env`:

```env
LLM_PROVIDER=groq
MODEL_NAME=openai/gpt-oss-120b
GROQ_API_KEY=your_key_here
```

### Running Locally

```powershell
# 1. Start Backend (Terminal 1 - Port 8001)
cd backend
uv run python main.py

# 2. Start Frontend (Terminal 2 - Port 3000)
cd frontend
npm install
npm run dev
```

- **Frontend Application**: `http://localhost:3000`
- **Backend API Docs**: `http://localhost:8001/docs`

---

## 🧪 Testing

Run the comprehensive test suite with `uv`:

```powershell
# Run all unit and integration tests
backend\.venv\Scripts\pytest.exe tests\ -v

# Run 5-change E2E live pipeline verification
backend\.venv\Scripts\python.exe tests\test_e2e_5_changes.py
```

---

## 📋 API Endpoints Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/auth/register` · `/login` · `/logout` | `POST` | User authentication & token management |
| `/auth/me` | `GET` | Current user profile & configured provider keys |
| `/auth/profile/keys` | `PUT` | Save provider API keys |
| `/setup/import` | `POST` | Download, soften, and split Overleaf/GitHub template into zones |
| `/sessions` | `POST` / `GET` | Create or list chat sessions |
| `/sessions/{id}` | `GET` / `PATCH` | Load session or switch active provider/model |
| `/chat` | `POST` | Agentic chat turn & document zone update |
| `/chat/apply` | `POST` | Apply an edit proposal variant |
| `/compile` | `POST` | Render LaTeX code to PDF base64 |
| `/score` | `POST` | Calculate ATS keyword & semantic similarity score |
| `/providers` | `GET` | List supported and configured LLM providers |

---

## 📝 License

MIT
