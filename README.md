# AI LaTeX Resume Maker

Chat-first, agentic resume builder: AI fills **dynamic LaTeX zones**, you iterate in chat, and the right panel toggles **Code / Render**. Multi-provider LLM routing (Groq, OpenAI, Gemini, Anthropic, Azure, AWS Bedrock) with durable sessions, login/profile API keys, and mid-chat model switching.

## Features

- **Auth + profile keys** — register/login; store provider API keys server-side (never echoed raw to the UI)
- **Chat resume loop** — paste a bio, refine via natural language
- **Zone specialists** — router classifies intent → HEADER / SUMMARY / EXPERIENCE / EDUCATION / SKILLS agents
- **Dynamic zones** — `% ZONE:NAME:START/END` markers keep the skeleton stable
- **LLM router** — explicit `LLM_PROVIDER` + `MODEL_NAME` (or per-turn / UI picker)
- **Durable sessions** — JSON under `backend/data/sessions/` (survives restarts)
- **Soft-fail compile** — `/chat` and `/chat/apply` keep LaTeX when PDF fails; UI shows the compile note
- **Tectonic compile** — PDF with AI fix retries
- **ATS tool** — secondary keyword / semantic match (optional Gemini embeddings)

## Architecture

```text
frontend (React)
    → FastAPI
        → auth_store (profiles / tokens)
        → session_store (chat history + latex)
        → zone agents + ai_agent
        → llm_router/{groq,openai,gemini,anthropic,azure,aws}
        → Tectonic (backend/bin or PATH)
```

## Templates

| Name | Engine | Status on Windows + Tectonic 0.16.9 |
|------|--------|--------------------------------------|
| **modern** (default) | `article` | Works — use this for PDF |
| executive | `article`-style | Prefer for layout variety |
| classic | `moderncv` | Unreliable — Fontconfig / crash; LaTeX edits may still save |

Always start a **new chat with `modern`** if you need a working preview PDF.

## Setup

### Prerequisites

- Python 3.9+, Node 18+
- [Tectonic](https://tectonic-typesetting.org/install/) **or** place `tectonic.exe` in `backend/bin/`
- At least one provider API key (Groq recommended)

### Environment

Copy `.env.template` → `.env`:

```env
LLM_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile
GROQ_API_KEY=your_key_here
```

Supported providers: `groq`, `openai`, `gemini`, `anthropic`, `azure`, `aws`. Selection is **explicit** — the chosen provider’s key must be set (env or Profile → API keys).

### Local development

```bash
# Backend
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# or with uv:
uv run --python .venv\Scripts\python.exe python main.py

pip install -r requirements.txt   # if not using uv sync
python main.py

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

- UI: http://localhost:3000  
- API: http://localhost:8000 /docs  

**Port already in use (Errno 10048):** another process holds 8000. Free it, then restart:

```powershell
Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### Docker

```bash
docker-compose up --build
```

Session/profile data live under `backend/data` (gitignored).

## API (high level)

| Endpoint | Purpose |
|----------|---------|
| `POST /auth/register` · `/login` · `/logout` | Auth |
| `GET /auth/me` | Current user + which keys are configured |
| `PUT /auth/profile/keys` | Save provider keys (empty fields do not wipe) |
| `POST /sessions` | Create chat (`template_name` default: `modern`) |
| `GET /sessions` · `GET /sessions/{id}` | List / load |
| `PATCH /sessions/{id}/model` | Switch provider/model |
| `POST /chat` | Agentic turn (profile key via Bearer) |
| `POST /chat/apply` | Apply a proposal variant (soft-fail compile) |
| `POST /compile` | Render PDF |
| `GET /providers` | Defaults + which env keys are present |

## Zones

Templates in `backend/templates/` use markers like:

```latex
% ZONE:EXPERIENCE:START
...
% ZONE:EXPERIENCE:END
```

Agents update zone interiors only; packages and layout stay fixed.

## Ops notes

- **Tectonic CLI:** v0.16+ uses `tectonic -X compile` (not legacy `--noninteractive`).
- **Logging:** `resume_maker.api` ASCII-safe logs (Windows-friendly).
- **Secrets:** do not commit `.env` or `backend/data/`. Rotate any key pasted into chat.
- Work log / incident history: see [`logs_work.md`](logs_work.md).

## Future

- Research paper document type (same zone + agent pattern)
- Fix classic/`moderncv` under Tectonic on Windows
- Multi-user cloud sync beyond local JSON profiles

## License

MIT
