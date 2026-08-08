# Work log — Resume Maker

Chronological notes of what was built, broken, and fixed. Updated 2026-08-08.

## Scope locked

- **1C** — full agentic chat loop (zones, compile, refine)
- **2A** — explicit provider + model selection (no silent fallback)

Research papers deferred.

---

## Built (current system)

### Backend

| Area | Location / notes |
|------|------------------|
| LLM router | `backend/llm_router/` — openai, groq, gemini, anthropic, azure, aws; shared `chat()` |
| Zones | `backend/core/zones.py` — `% ZONE:NAME:START/END` extract/replace |
| Zone agents | `backend/core/zone_agents/` — intent router → HEADER/SUMMARY/EXPERIENCE/EDUCATION/SKILLS |
| Sessions | `backend/core/session_store.py` → `backend/data/sessions/*.json` |
| Auth | `backend/core/auth_store.py` — register/login, hashed passwords, profile API keys, tokens |
| AI agent | `backend/core/ai_agent.py` — chat turn, proposals, compile-error fix |
| Compiler | `backend/core/compiler.py` — Tectonic `-X compile`; path: `TECTONIC_PATH` → `backend/bin` → PATH |
| Logging | `backend/core/logging_setup.py` |
| Default template | **modern** (`article`) |

### Frontend

- Login/register gate; Profile modal (API keys + password)
- Empty key fields on save do **not** wipe existing keys; UI only gets `keys_configured`
- Chat left; Code/Render right; sessions rail; model picker; ATS secondary
- Vite proxy `/api` → `:8000`
- Soft-fail apply: shows compile note instead of only a hard error toast

### Auth APIs

`POST /auth/register`, `/login`, `/logout`, `GET /auth/me`, `PUT /auth/profile/keys`, `POST /auth/profile/password`

### Chat APIs

`POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `PATCH .../model`, `POST /chat`, `POST /chat/apply`

---

## Incidents & fixes

### 1. Auth 404

- **Cause:** stale uvicorn without auth routes
- **Fix:** restart backend after route changes

### 2. Profile keys wiped / fake key → Groq 401

- **Cause:** password-style empty inputs cleared `api_keys`; then a placeholder `gsk_fixed_test_key_abc` was stored
- **Fix:** empty fields skip update; never echo raw keys to UI; user pasted real Groq key into profile
- **Security:** key was exposed in chat once — **rotate Groq key** if that session is shared

### 3. Port 8000 in use (`Errno 10048`)

- **Cause:** orphaned previous `main.py` / uvicorn still listening
- **Fix:** stop owning PID(s), then start again  
  `Get-NetTCPConnection -LocalPort 8000 | % { Stop-Process -Id $_.OwningProcess -Force }`
- **2026-08-08 ~17:53:** user restart failed with 10048; freed PID 3592; later user successfully bound (PID 17016)

### 4. Tectonic CLI flags

- **Cause:** `--noninteractive` invalid on Tectonic **0.16.9**
- **Fix:** use `tectonic -X compile --outdir ... resume.tex`
- Binary placed at `backend/bin/tectonic.exe` (gitignored); download from GitHub releases if missing

### 5. Classic / moderncv PDF failure

- **Symptom:** `CompilationError: Tectonic failed` + `Fontconfig error: Cannot load default config file`
- **Sessions:** e.g. `b52e0aa4-...` and later `2341f2dc-...` with `template=classic`
- **modern** template compiles (~OK PDF); **classic** unreliable on this Windows + Tectonic build
- **Product default:** new sessions use **modern**

### 6. `POST /chat/apply` → HTTP 500

- **Causes:**
  1. Hard-fail on compile (classic broken)
  2. On zone-replace failure, entire doc replaced with a **fragment** (invalid LaTeX)
  3. `DraftVariant` missing `zone_id` → wrong zone / EXPERIENCE default
- **Fix (2026-08-08):**
  - Soft-fail compile on `/chat/apply` and `/apply` — return `compile_error`, keep LaTeX
  - Never treat fragment as full document
  - Persist `zone_id` on variants from proposals
  - Frontend: apply keeps latex; surfaces compile note
  - Tip in error when `template_name == classic`

### 7. Soft-fail already on `/chat`

- Chat saves zone updates even when compile fails; reply appends `(Compile issue: ...)`
- Observed 17:56–17:57: first_fill on classic → agent OK → compile failed → **HTTP 200** on `/chat`

---

## How to run (current)

```powershell
# Backend
cd backend
.\.venv\Scripts\Activate.ps1
uv run --python .venv\Scripts\python.exe python main.py

# Frontend
cd frontend
npm run dev
```

Ensure `backend/bin/tectonic.exe` exists or Tectonic is on PATH.

---

## Known open items

1. Make **classic**/`moderncv` compile on Windows (Fontconfig / fonts) or hide classic in UI until fixed
2. Soft-fail **`POST /compile`** the same way as chat (still hard 500 on classic sessions when loading PDF)
3. Optional: React Router for per-session URLs; parallel zone agents
4. User should rotate any Groq key that appeared in chat logs
5. Avoid committing `backend/data/` (profiles, sessions, tokens) — already gitignored

---

## Recent session snapshot (2026-08-08 ~17:55)

From local backend terminal after a clean start:

- `POST /sessions` 200 — new session created
- Loaded session `2341f2dc-400f-4264-8153-a0c224f37cca` with **template=classic**
- `POST /compile` → **500** Fontconfig / Tectonic failed
- `POST /chat` first_fill with Groq profile key → zones updated → compile failed → **200** (soft-fail)
- Backend later shut down cleanly (user Ctrl+C)

**Recommendation:** create a **new** session with template **`modern`** for PDF preview.
