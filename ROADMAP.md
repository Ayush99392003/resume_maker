# Agentic Resume Maker — Architecture Roadmap

## Phase 1: Zone Engine & Agentic Chat UI
- Dynamic LaTeX zone extraction and replacement (`% ZONE:NAME:START` ... `% ZONE:NAME:END`).
- Multi-provider LLM router (Groq, OpenAI, Gemini, Anthropic).
- FastAPI backend with persistent chat sessions and auth.

## Phase 2: Guardrails & Self-Healing Compilation
- Pydantic models for structured output validation and retry loops.
- Bottom-up line delta patcher for localized Tectonic compiler fixes.

## Phase 3: Token Optimization & Production UX
- Compact context digests for 80%+ token reduction.
- Interactive section selector chips and live dual-panel PDF preview.
