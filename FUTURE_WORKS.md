# Future works — Resume Maker

Product ideas parked for later. Not committed scope until picked up.

---

## Feature: Compat Lab (measure → ratio → save → iterate → tool)

**Status:** future  
**Seeded by:** 2026-08-09 Overleaf paste / Tectonic soften work  
**Related today:** `backend/core/latex_soften.py`, compile soft-fail, `compat_notes`

### Problem

Overleaf (pdfLaTeX/XeLaTeX + full TeX Live) and our stack (Windows Tectonic + Python API) speak different “dialects” of the same resume:

| Side | Spec / reality |
|------|----------------|
| **LaTeX / Overleaf** | Packages (`fontawesome5`, `contour`, `fontspec`), icons, fonts, multi-file zips, `\newcommand` patterns that assume a full engine |
| **Python / Resume Maker** | Numbered zones JSON, soften transforms, Tectonic compile, session persistence, agent edits |

Today we **hand-tune** softens when something crashes. That does not scale across templates.

### Idea

Build a **Compat Lab** tool (CLI first, then in-app) that treats compatibility like an experiment loop—similar in spirit to how you’d measure docs/API coverage in Python, but for LaTeX → Tectonic:

1. **Ingest** — raw Overleaf `.tex` / gallery zip / session latex  
2. **Measure (LaTeX side)** — packages used, engines implied, FA icons, nested defs, `\input`/`\includegraphics`, brace depth, zone-ability  
3. **Measure (runtime side)** — Tectonic exit, error class (heap / undefined / braces / missing file), PDF bytes, time, soften changes applied  
4. **Ratio** — scores such as  
   - packages supported / packages used  
   - compile success rate over N templates  
   - visual/layout proxies later (optional page-count, text extraction overlap)  
5. **Save** — append rows to a dataset (`backend/data/compat/` or SQLite): template id, metrics, errors, soften version, before/after hashes  
6. **Iterate** — use failures to propose softener rules or agent fixer prompts; re-run corpus; track ratio over time  
7. **Ship as tool** — expose `POST /compat/run` + a small UI panel (“Test this template”) and/or `python -m tools.compat_lab`

### Why “like Python docs”

Python tooling often:

- introspects / samples  
- scores coverage  
- stores fixtures  
- regresses on CI  

Compat Lab does the same for **resume LaTeX vs our compiler**: fixtures = Overleaf templates; coverage = package/feature matrix; regression = soften + compile must not go red.

### Suggested phases

| Phase | Deliverable |
|-------|-------------|
| **P0** | Offline script: run soften + compile on a folder of `.tex`; write CSV/JSON metrics |
| **P1** | Error taxonomy + ratios dashboard in logs / markdown report |
| **P2** | Auto-suggest softener rules from recurring error patterns (human approve) |
| **P3** | In-app Compat Lab: paste URL/tex → score + notes + “apply soften” |
| **P4** | CI corpus smoke (subset of public gallery templates) |

### Non-goals (initially)

- Pixel-perfect Overleaf parity  
- Supporting every XeTeX-only font stack  
- Replacing the chat orchestrator  

### Success metrics

- Rising **compile success ratio** on a fixed public-template corpus  
- Falling rate of “silent” Tectonic deaths after soften  
- Softener changes tied to measured failures, not one-off guesses  

### Hooks in current code

- Soften: `backend/core/latex_soften.py`  
- Compile: `backend/core/compiler.py`, `compile_with_retry`  
- Import: `_doc_from_import` / `POST /setup/import`  
- Work log incidents: `logs_work.md` (2026-08-09 soften errors)

---

## Other future ideas (short)

- Hide or quarantine `classic` / moderncv until Fontconfig path is solid  
- Drag-and-drop zone reorder in UI  
- Parallel zone agents for first fill  
- Per-session URLs (React Router)  
- Private Overleaf: zip upload path (beyond paste)

---

*Add new feature briefs under a `## Feature: …` heading. Link incidents from `logs_work.md` when they motivate the idea.*
