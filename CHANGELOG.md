# Changelog — AI LaTeX Resume Maker

All notable changes, architectural optimizations, and feature enhancements from **August 26, 2026 to September 1, 2026**.

---

## [September 15 – September 16, 2026]

### 🛠️ LaTeX Compatibility Layer, Error Recovery Engine & Session Class Isolation
- **Dynamic Font Fallback Chain (`FontHandler`, `core/latex_compatibility.py`)**:
  - Automatically intercepts missing font errors from XeTeX/fontspec (e.g. `Tinos-Regular`, `Montserrat`, `Fira Code`) on Windows Tectonic.
  - Dynamically substitutes missing font definitions with standard TeX Gyre fonts (`TeX Gyre Termes`, `TeX Gyre Heros`, `TeX Gyre Cursor`) across both `.tex` and workspace `.cls` class files.
- **Deterministic Color Recovery (`ColorHandler`, `core/latex_compatibility.py`)**:
  - Automatically upgrades `\usepackage{xcolor}` declarations with `[dvipsnames,svgnames,x11names]`.
  - Captures `Undefined color` compilation failures and injects safe neutral or theme `\providecolor` fallback definitions into the preamble before compiling.
- **Targeted Auto-Repair Loop (`RepairEngine`, `ErrorClassifier`)**:
  - Replaced brittle full-document LLM rewriting for basic compilation errors with a targeted deterministic repair loop in `compiler.compile()` (`MAX_REPAIR_ATTEMPTS = 5`).
  - Repairs errors in under 0.5s with zero token overhead and zero risk of LaTeX macro loss.
- **Side-File & Template Softening (`PackageHandler`, `core/latex_soften.py`)**:
  - Broadened side-file handling to neutralize missing references like `\input{particulars.tex}` and touch dummy placeholders in compile directories.
- **Session Workspace Class Seeding & Starter Template**:
  - Removed rigid legacy `classic` and `modern` templates.
  - Isolated custom `.cls` class definitions per session workspace via `_seed_cls_files()`.
  - Added clean ATS-ready `starter.tex` with fully validated `rSubsection` item lists (23KB PDF output).
- **Agent Router JSON Parsing Resilience (`core/zone_agents/__init__.py`)**:
  - Implemented `_extract_json()` with `_pre_escape_backslashes()` to fix `NameError: name '_extract_json' is not defined`.
- **Test Suite Decryption & Skip Grace (`tests/`)**:
  - Updated all test suites to decrypt profile API credentials via `auth_store.get_provider_config` and skip gracefully when external credentials are not present.

---

## [September 1, 2026]

### ⚡ Token Optimization & Fast-Path Zone Architecture
- **Compact Context Digest (`compact_digest`)**:
  - Implemented `ZoneDocument.compact_digest(active_zone_no=n)` which strips comments and raw LaTeX commands from non-target zones, passing a lightweight 1-line structural map (~50–80 tokens context) instead of the full ~3,500-token raw document.
- **Fast-Path Specialist Routing**:
  - Added `target_zone` support to `/chat` endpoint, `chat_router.py`, and `orchestrator.py`.
  - When the user selects a section chip or provides unambiguous single-zone intent, the system bypasses both the **Chat Router LLM** and the **Orchestrator Planner LLM**.
  - Edit requests execute directly in **1 single specialist LLM call** (reducing calls by **67%**).
- **Interactive Section Selector UX (`frontend/src/App.jsx`)**:
  - Added horizontal chip selector above the chat input bar (`Auto`, `Header`, `Education`, `Skills`, `Experience`, `Projects`, `Full Rewrite`).
  - Automatically resets to `Auto` after message dispatch to prevent accidental mode stickiness.
  - Added resolved target zone badges to assistant message bubbles (e.g. `🏷️ Editing: Skills Summary`).
- **Sequential Multi-Zone Execution**:
  - In-memory `ZoneDocument` updates rolling state between sequential zone specialist calls, followed by a single incremental Tectonic PDF compilation pass to stay safely within rate limit envelopes (e.g. 8K TPM).
- **Benchmarking & Validation**:
  - Created `tests/test_token_optimization.py` and `tests/test_auto_vs_section_comparison.py`.
  - Benchmarked on `openai/gpt-oss-120b`: achieved **86.6% average token savings** (~1,270 tokens vs. ~9,500 tokens) and **4x faster turnaround** (~2.0s – 3.3s).

---

## [August 29 – August 31, 2026]

### 🧪 Custom Template E2E Suite & Compiler Self-Healing
- **Custom Template E2E Verification (`test_e2e_custom_template_10_changes.py`)**:
  - Implemented a 10-change sequential test suite against Ayush Agarwal's custom LaTeX resume template (`Anubhav Singh` base).
  - Validates live Tectonic compilation, PDF sizing, and token metrics across all 10 changes with JSON and markdown artifact reporting.
- **Windows Console Encoding Fixes**:
  - Configured UTF-8 stdout/stderr streams to eliminate CP1252 charmap encoding errors with Rich console loggers.
- **Groq Model Router Extensions**:
  - Added support and probing for `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.6-27b`, and `qwen/qwen3.8-27b`.

---

## [August 26 – August 28, 2026]

### 🛡️ Guardrails, LaTeX Softening & Localized Line Patching
- **Bottom-Up Line Indexer & Delta Patcher**:
  - Created `line_indexer.py` to extract 1-based error line numbers from raw Tectonic compiler error logs with surrounding context.
  - Implemented `delta_patcher.py` to apply targeted line replacements from the bottom up to preserve line numbering.
- **TeX Softener Resilience (`latex_soften.py`)**:
  - Sanitized multi-line regexes and added safe stub definitions for fragile font and contour macros (`\myuline`, `\contour`, `fontawesome5`).
  - Added Unicode normalization and symbol auto-escaping for math and text mode boundaries.
- **Pydantic Specialist Agents**:
  - Enforced structured JSON outputs and retry loops across all six core specialist agents (`HeaderAgent`, `SummaryAgent`, `ExperienceAgent`, `EducationAgent`, `SkillsAgent`, `ProjectsAgent`).
