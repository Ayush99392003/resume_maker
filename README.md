# AI LaTeX Resume Maker

Chat-first, agentic resume builder: AI fills and refines **dynamic LaTeX zones**, you iterate in conversation, and the right panel toggles live **Code / Render**. Features multi-provider LLM routing (Groq, OpenAI, Gemini, Anthropic, Azure, AWS Bedrock) with durable sessions, local profile keys, interactive section chips, and an **86.6% token-optimized zone architecture**.

---

## 🚀 Key Features

- **86.6% Token-Optimized Zone Architecture**:
  - **Compact Document Digest (`compact_digest`)**: Strips non-target raw LaTeX bloat down to a 1-line structural map (~50–80 tokens context vs. ~3,500 raw tokens).
  - **Fast-Path Specialist Routing**: Direct rule and chip matching routes straight to specialist agents in **1 single LLM call** (~1,270 tokens total vs. ~9,500 across previous 3-agent cascades).
- **Interactive Section Selector UX**:
  - Quick-pick chips above the chat input bar (`Auto`, `Header`, `Education`, `Skills`, `Experience`, `Projects`, `Full Rewrite`).
  - Atomic payload transmission with automatic reset to `Auto`.
  - Resolved zone feedback badges displayed directly on assistant chat bubbles (e.g. `🏷️ Editing: Skills Summary`).
- **Sequential Multi-Zone Execution**:
  - Sequential specialist LLM calls with rolling compact digest refreshes, followed by a single incremental Tectonic PDF compilation to stay safely within rate limits (e.g. 8K TPM).
- **Overleaf Import & TeX Softener**:
  - Download and parse public Overleaf gallery links or pasted `.tex` files.
  - Automatic softening ([`latex_soften.py`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/core/latex_soften.py)) replaces crashy XeTeX/Font Awesome packages and normalizes Unicode for Windows Tectonic compilation.
- **Hierarchical Specialist Agents**:
  - Domain-specific specialists (`HeaderAgent`, `SummaryAgent`, `ExperienceAgent`, `EducationAgent`, `SkillsAgent`, `ProjectsAgent`) with Pydantic output validation and auto-escaping for LaTeX characters (`&`, `$`, `%`, `_`, `#`).
- **Self-Healing LaTeX & Line-Delta Patching**:
  - If Tectonic compilation fails, [`line_indexer.py`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/core/line_indexer.py) and [`delta_patcher.py`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/core/delta_patcher.py) localize the error lines and apply targeted line replacements in under 3s without corrupting session state.
- **ATS Keyword & Embedding Scorer**:
  - ATS keyword analysis and semantic vector matching powered by Google Gemini embeddings.

---

## 🏛️ System Architecture

```text
frontend (React / Vite on :3000)
    ↓ API Proxy (/api -> http://localhost:8001)
FastAPI Backend (backend/main.py on :8001)
    ├── auth_store (Profiles, Tokens & Keys)
    ├── session_store (Chat History & Zone Documents with Snapshots)
    ├── chat_router (Rule-based & LLM Intent Classification)
    ├── orchestrator (Step Planning, Sequential Execution & Compact Rolling Digest)
    ├── zone_agents (Header, Summary, Experience, Education, Skills, Projects)
    ├── latex_soften (TeX Package, Unicode & Macro Compatibility Transformer)
    ├── line_indexer & delta_patcher (Localized Line-Level Self-Healing Compiler)
    ├── llm_router (OpenAI, Groq, Gemini, Anthropic, Azure, AWS Bedrock)
    └── compiler (Windows Tectonic CLI Compiler & Soft-Fail Fallback)
```

---

## 🛠️ Setup & Local Development

### Prerequisites

- **Python 3.11+** with [`uv`](https://github.com/astral-sh/uv) package manager
- **Node.js 18+**
- **Tectonic CLI**: Placed in [`backend/bin/`](file:///c:/Users/ayush/Pictures/Resume_Maker/resume_maker/backend/bin) or installed on system `PATH`.
- At least one provider API key (Groq recommended).

### Environment Configuration

Create `.env` in `backend/`:

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

## 🧪 Testing & Benchmarks

```powershell
# Run all unit and integration tests
backend\.venv\Scripts\pytest.exe tests\ -v

# Run Token Optimization & Routing Comparison Benchmark
backend\.venv\Scripts\python.exe tests\test_auto_vs_section_comparison.py

# Run Custom Template E2E Verification
backend\.venv\Scripts\python.exe tests\test_e2e_custom_template_10_changes.py
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
| `/chat` | `POST` | Agentic chat turn & document zone update (supports `target_zone`) |
| `/chat/apply` | `POST` | Apply an edit proposal variant |
| `/compile` | `POST` | Render LaTeX code to PDF base64 |
| `/score` | `POST` | Calculate ATS keyword & semantic similarity score |
| `/providers` | `GET` | List supported and configured LLM providers |

---

## 📝 License

MIT
