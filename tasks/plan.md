# Implementation Plan: Compiler Breakdown & Root-Cause Fixes

## Overview
Investigation of `Logs.log` revealed four interconnected root causes causing catastrophic compiler failures across resume editing, layout squeezing, and IEEE paper compilation:
1. **JSON Newline Corruption (`\n` -> literal `\n`)**: In `backend/core/latex_sanitizer.py`, `_pre_escape_backslashes()` treated any `\n` followed by an alphabetic character (`\nAI`, `\nProgramming`, `\nDistributed`) as a LaTeX control sequence, doubling the backslash to `\\n`. `json.loads` decoded this to literal `\n`, producing `! Undefined control sequence \n` and cascading into disastrous fixer attempts that deleted `\end{rSection}` and left `\begin{list}` unclosed.
2. **IEEE Author Block Incompatibility with `tabular`**: In `backend/templates/ieee_starter.tex`, `\IEEEauthorblockA` was defined as `\newcommand{\IEEEauthorblockA}[1]{\textit{#1}\\}`. In standard `article` class, `\author` is evaluated inside a `tabular`. When an affiliation contains `\\`, `\textit{#1}` breaks across table cells leaving an unclosed `{`, causing `! Missing } inserted. l.33 \begin{abstract}`.
3. **Auto-Repair Engine False Positive Loop**: In `backend/core/latex_compatibility.py`, `MathHandler.is_math_error()` matched any log containing `"mathtools"` or `"amssymb"`. Because Tectonic logs loaded files like `(mathtools.sty ...)` on every run, `is_math_error` returned `True` for every error (including `! Missing } inserted.`). Furthermore, `inject_math_packages()` had a regex that failed to match multi-package declarations like `\usepackage{amsmath,amssymb}`, repeatedly injecting duplicate `\usepackage` lines up to the retry limit.
4. **Duplicate Zone Marker Nesting**: In `backend/core/zone_document.py`, `strip_zone_markers()` only stripped markers matching the exact numeric `zone_no`. If inner content already had zone markers, they remained unstripped and were wrapped again by `wrap_zone_body()`, creating invalid nested markers (`% ZONE:3:START\n% ZONE:3:START`).

---

## Architecture Decisions
- **Fix at the root (`ponytail` principle)**: Rather than adding workarounds or patchers downstream, fix the 4 exact points of failure at their source.
- **Differentiate JSON newlines from LaTeX macros**: In `_pre_escape_backslashes()`, `\n` in JSON is always a newline unless followed specifically by known LaTeX commands starting with `n` (`newcommand`, `newenvironment`, `newline`, `noindent`, `nocite`, `normalsize`, `null`, `number`, `nabla`, `neq`, `neg`).
- **Use tabular wrapper for author block**: Define `\IEEEauthorblockA` as `\newcommand{\IEEEauthorblockA}[1]{\begin{tabular}{@{}c@{}}\itshape #1\end{tabular}\\}` so multi-line affiliations with `\\` compile cleanly inside `article`'s `\author` tabular.
- **Strict log error matching**: `is_math_error` must only match actual math errors (e.g. `_MATH_CMD_RE` or `! LaTeX Error: ... amsmath`), never benign package-loading log lines `(...sty ...)`.

---

## Task List

### Phase 1: Core Root-Cause Fixes
- [ ] Task 1: Fix `_pre_escape_backslashes` in `backend/core/latex_sanitizer.py` to preserve JSON `\n` before words.
- [ ] Task 2: Fix `\IEEEauthorblockA` in `backend/templates/ieee_starter.tex` to support multi-line affiliations.
- [ ] Task 3: Fix `MathHandler` in `backend/core/latex_compatibility.py` to eliminate false-positive error classification and duplicate package injection.
- [ ] Task 4: Fix `strip_zone_markers` in `backend/core/zone_document.py` to prevent duplicate nested zone markers.

### Checkpoint: Core Fixes
- [ ] Automated tests pass (`test_latex_sanitizer.py`, `test_latex_compatibility.py`, `test_research_paper_mode.py`).
- [ ] Tectonic compiles `test3.tex` and sample paper sessions without `! Missing } inserted.` or `! Undefined control sequence \n`.

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| LaTeX commands starting with `\n` accidentally treated as newlines | Med | Explicitly whitelist `\newcommand`, `\newline`, `\noindent`, `\nocite`, etc. |
| Other starter templates have author block issues | Low | Audit `paper_starter.tex`, `acm_starter.tex`, `arxiv_starter.tex`. |
