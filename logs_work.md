# Work log — Resume Maker

Chronological notes of what was built, broken, and fixed. Updated 2026-08-09 (EOD — continue tomorrow).

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

## Known open items / continue tomorrow

1. **Re-test Overleaf paste in UI** after brace-fix soften (user must use **New chat** + fresh paste; old sessions may still hold broken `\myuline` remnant latex)
2. Watch for any remaining Tectonic errors on other Overleaf templates (not just Harshibar) — expand softener as needed
3. Make **classic**/`moderncv` compile on Windows or hide classic in UI
4. Port **8000** orphan processes (`Errno 10048`) — kill PID then restart; common after aborted agent shells
5. Optional: React Router for per-session URLs; parallel zone agents; drag-and-drop zone reorder
6. Rotate any Groq key that appeared in older chat logs
7. Avoid committing `backend/data/` (sessions, imports, logs) — gitignored
8. **Future feature:** Compat Lab (measure LaTeX vs Tectonic/Python runtime → ratio → save → iterate → tool) — see [`FUTURE_WORKS.md`](FUTURE_WORKS.md)

---

## 2026-08-09 — Numbered zones + router + orchestrator

- Sessions store `header` / `footer` / `zones[]` / `zone_order` / `next_zone_no`
- `latex_to_zones` converts built/bundled `.tex` → Zone 1..N JSON
- Chat: top-level `chat_router` (`direct_reply` vs `orchestrator`) then fill/edit/add/remove/reorder/describe agents
- APIs: `POST /setup/import`, `POST/DELETE .../zones`, `PATCH .../zone-order`
- UI: Overleaf URL on new chat, zone chips (click to remove), + Add zone

---

## 2026-08-09 — Overleaf → Tectonic soften + debug logging (EOD)

### Built today

| Area | Notes |
|------|--------|
| Rich step/error logs | `*.step:` / `*.error:` across API, router, orchestrator, agent, compile, import |
| Log file | `backend/data/logs/app.log`; `LOG_LEVEL=DEBUG` in `.env` for more detail |
| Fontconfig (Windows) | `backend/fonts/fonts.conf` + env in `compiler.py` |
| Soften pipeline | `backend/core/latex_soften.py` — disable crashy pkgs, FA → text, brace-safe `\myuline` |
| Soften on import | `_doc_from_import` softens **before** `latex_to_zones`; returns `compat_notes` |
| Soften on compile/put | `ensure_full_document` + `PUT .../latex` |
| UI | Blue compat banner; editor gets softened latex after paste |
| Sample render | `backend/data/imports/harshibar_render/` (`resume_compat.tex`, PDFs) |
| Tests | `tests/test_latex_soften.py`, `tests/test_latex_to_zones.py` |

### Errors seen today (log for tomorrow)

#### A. Empty Tectonic log / heap-style fail (paste Overleaf)

- **UI/log:** `Tectonic failed` with only `Running TeX...` then die; `project_dir=False`
- **Cause:** packages like `fontawesome5` / `FiraMono` / `contour` crash this Windows Tectonic build
- **Also:** stale backend without soften (old log lines looked like `compile: latex_chars=` not `compile.step:`)
- **Mitigation:** auto-soften on paste/import/compile; restart backend after pulls

#### B. `Too many }'s` at `resume.tex:42` (user-facing ~10:50)

- **Exact message:**  
  `error: resume.tex:42: Too many }'s`  
  plus misleading tip about fontawesome crash
- **Root cause:** soften regex for `\newcommand{\myuline}[1]{%...\contour{white}{...}}` stopped at the **first** `}` → left orphan `{\underline{...}}}` in preamble
- **Fix (landed, backend restarted PID ~38160):** brace-balanced `_replace_newcommand_body`; crash tip only when there is **no** real TeX `error:`
- **Tomorrow:** confirm in UI with **New chat → paste raw Harshibar/Overleaf `.tex`**; do not reuse session that already saved broken latex

#### C. Port 8000 `Errno 10048`

- Orphan `python` still LISTENING after agent/shell abort (e.g. PID 37856)
- **Fix:** `netstat -ano | findstr :8000` → `Stop-Process -Id <pid> -Force` → start `main.py` again

#### D. Soften leftover-FA regex bug (fixed same day)

- Pattern `\fa[A-Za-z]+` also matched `\fancyhf` / `\familydefault` → broke document shell (`Missing \begin{document}`)
- **Fix:** only strip `\fa` + **Capital** letter (`\faPhone`, etc.)

#### E. Stale session / double-escape in ad-hoc API tests

- PowerShell-escaped pastes produced `\\faPhone*` in latex; not a product bug
- Prefer `backend/scripts/verify_soften_harshibar.py` and `verify_soften_api.py` for checks

### Verified green (before EOD)

- Unit: soften + zones tests pass
- Script: softened Harshibar-like raw → PDF (`harshibar_softened.pdf`)
- API: `POST /setup/import` with crashy packages → `compat_notes` + `pdf_base64`, `compile_error: null`

### How to resume tomorrow

```powershell
# Backend (kill orphan first if 10048)
netstat -ano | findstr :8000
cd backend
uv run --python .venv\Scripts\python.exe python main.py

# Frontend
cd frontend
npm run dev
```

1. New chat → Template URL tab → paste full Overleaf `.tex` → Start chat  
2. Expect blue banner (“Adjusted for Windows Tectonic…”) + PDF  
3. If compile fails: copy exact `compile_error` + last lines from backend terminal / `backend/data/logs/app.log` into this file under a new incident

### Key files to touch next

- `backend/core/latex_soften.py` — more packages / templates as errors appear  
- `backend/main.py` — `_tectonic_crash_tip`, import/compile responses  
- `frontend/src/App.jsx` — paste / compat banner  
- `logs_work.md` — append new errors here
