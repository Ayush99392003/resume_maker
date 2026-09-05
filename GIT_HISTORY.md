# Project Git History & Sprint Changelog

## 📅 Yesterday — September 3, 2026
**Theme:** Multi-User Architecture, Session Isolation & Concurrency Guardrails

### Git Commits
- [`7a7a824`](#) — `feat(concurrency): implement multi-user session isolation and compile throttling`
  - **Session Isolation:** Attached ownership verification (`session.username`) to session creation, listing, retrieval, and LaTeX updates.
  - **Compile Concurrency Limiter:** Introduced `asyncio.Semaphore(2)` (`compile_semaphore`) to prevent resource exhaustion when multiple users invoke Tectonic concurrently.
  - **Token Atomic Persistence:** Implemented safe atomic write routines for user token authentication in `auth_store.py`.
  - **Automated Verification:** Added [`tests/test_multi_user_concurrency.py`](tests/test_multi_user_concurrency.py) testing concurrent compile safety, token persistence, and cross-user session leakage prevention.

---

## 📅 Today — September 4, 2026
**Theme:** Encrypted Provider Vault, Multi-Turn Chat Undo & UI Design Audit

### Git Commits
1. [`26588fe`](#) — `feat(security): add Fernet encrypted provider credentials and Azure/AWS LLM router integration`
   - **Encrypted Provider Vault:** Replaced plaintext API keys with Fernet symmetric encryption (`SESSION_SECRET` key derivation) for per-user credential storage.
   - **Multi-Cloud LLM Router:** Added unified credential extraction for Azure OpenAI (`endpoint`, `api_key`, `deployment`, `api_version`) and AWS Bedrock (`access_key_id`, `secret_access_key`, `region`, `model_id`).
   - **Provider Settings UI:** Dynamic tabbed credential modal allowing users to save, mask, and clear individual provider credentials.

2. [`6a3e23c`](#) — `feat(undo): introduce per-turn TurnSnapshot ring buffer and /sessions/{id}/undo rollback endpoint`
   - **Per-Turn Snapshot Engine:** Implemented `TurnSnapshot` ring buffer (depth: 10) in [`session_store.py`](backend/core/session_store.py) recording LaTeX source, zone models, header/footer, and tagged message IDs.
   - **Atomic Recovery Endpoint:** Added `POST /sessions/{session_id}/undo` in [`main.py`](backend/main.py), rolling back both chat conversation history and LaTeX document state with automatic Tectonic recompilation.
   - **Test Suite:** Created [`tests/test_undo.py`](tests/test_undo.py) validating snapshot push, tag, pop, and message truncation (100% pass rate).

3. [`d2e1e9d`](#) — `feat(ui): complete UI audit with sender distinctions, relative timestamps, unified model pill, and chat undo controls`
   - **Chat Panel Overhaul:** Distinct "You" (accent) vs "Assistant" (surface) message cards with relative timestamps (`formatRelTime`) and pulsing indicators (`animate-pulse`) for active zone edits.
   - **Input Experience:** Multi-line expanding textarea with character count indicator and keyboard shortcut hints (`⏎ Enter` to send, `Shift+Enter` for newline).
   - **Top Navigation Bar:** Replaced separate selects with a single cohesive provider/model pill dropdown showing configured API key statuses (`✓`).
   - **Sidebar & History:** Integrated relative timestamps (`2m ago`, `1h ago`) and uppercase provider badges (`GROQ`, `OPENAI`) with active state borders.
   - **Zone & Layout Controls:** Inline `+ Add zone` button, drag handle icons (`GripVertical`), horizontal overflow fade masks (`.mask-scroll-fade`), and explanatory tooltips on "Tighten layout" and "Full Rewrite".
   - **Preview Document Header:** Real-time document status bar with "Compiled PDF" / "Draft" badges and live LaTeX line counter.

---

## 📅 Tomorrow — September 5, 2026 (Planned Roadmap)
**Theme:** Production Containerization, Distributed Queue & Advanced Export

### Planned Git Commits & Milestones
1. `feat(docker): multi-stage production Dockerfile with bundled Tectonic and fontconfig`
   - Target: Package FastAPI backend, Vite static assets, Tectonic binary, and custom fonts into a production container.
   - Non-root execution user with volume mounts for `backend/data/` session persistence.

2. `feat(undo): add redo stack support and keyboard shortcut (Ctrl+Z / Ctrl+Y)`
   - Target: Track popped `TurnSnapshot` objects in a `redo_history` stack until a new chat turn is initiated.
   - Wire global keyboard listener for `Ctrl+Z` (Undo) and `Ctrl+Shift+Z` / `Ctrl+Y` (Redo).

3. `feat(export): add multi-format document exporter (DOCX, TXT, JSON ATS summary)`
   - Target: Provide clean one-click plain text and ATS-friendly JSON resume exports alongside compiled PDF.
   - Include printable link and QR code generation for candidate contact sections.

4. `perf(cache): Redis-backed session caching and asynchronous compilation job queue`
   - Target: Decouple synchronous Tectonic compilation from FastAPI request loop for zero-latency multi-turn agent streaming.
