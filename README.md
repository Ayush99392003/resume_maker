# AI LaTeX Resume Maker

Chat-first, agentic resume builder: AI fills **dynamic LaTeX zones**, you iterate in chat, and the right panel toggles **Code / Render**. Multi-provider LLM routing (Groq, OpenAI, Gemini, Anthropic, Azure, AWS Bedrock) with durable sessions, login/profile API keys, and mid-chat model switching.

---

## 🚀 Key Features

- **Auth + Profile Key Store**: Register/login with local profile persistence (`auth_store.py`). Provider API keys stored server-side and never echoed raw to UI.
- **Overleaf Import & TeX Softener**: Paste any public Overleaf gallery or GitHub LaTeX resume URL (`overleaf_import.py`). The TeX softener ([`latex_soften.py`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/core/latex_soften.py)) converts crashy XeTeX/Font Awesome packages for seamless Windows Tectonic compilation.
- **Hierarchical Agentic Architecture**: Chat Router classifies prompt intent → Orchestrator plans steps → Zone Specialist Agents edit target zones (`HEADER`, `SUMMARY`, `EXPERIENCE`, `EDUCATION`, `SKILLS`).
- **Dynamic Numbered Zones**: `% ZONE:NAME:START` and `% ZONE:NAME:END` markers keep preamble, styling, and page layout fixed while agents safely edit section contents.
- **Multi-Provider LLM Router**: Explicit provider and model routing across `groq`, `openai`, `gemini`, `anthropic`, `azure`, and `aws`.
- **Soft-Fail Compilation**: Tectonic errors trigger up to 2 auto-fix retries ([`ai_agent.py`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/core/ai_agent.py)). Non-fatal syntax issues preserve session state and display clear compile notes.
- **ATS Keyword & Embedding Scorer**: Hybrid keyword match + vector embedding cosine similarity using Google Gemini (`ats_scorer.py`).

---

## 🏛️ System Architecture

```text
frontend (React / Vite on :3000)
    ↓ API Proxy (/api -> http://localhost:8001)
FastAPI Backend (backend/main.py on :8001)
    ├── auth_store (Profiles, Tokens & Keys)
    ├── session_store (Chat History & Zone Documents)
    ├── chat_router & orchestrator (Intent Routing & Step Planning)
    ├── zone_agents (Header, Summary, Experience, Education, Skills)
    ├── latex_soften (TeX Package & Macro Compatibility Transformer)
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
MODEL_NAME=llama-3.3-70b-versatile
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
