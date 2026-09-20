# Tasks: Compiler Breakdown & Root-Cause Fixes

## Task 1: Fix `_pre_escape_backslashes` in `backend/core/latex_sanitizer.py`
**Description:** Stop treating standard JSON newlines (`\n` followed by letters such as `\nAI`, `\nProgramming`) as LaTeX control sequences. Whitelist specific LaTeX commands starting with `n` (`newcommand`, `newenvironment`, `newline`, `noindent`, `nocite`, `normalsize`, etc.) and preserve `\n` as genuine JSON whitespace for all other words.

**Acceptance criteria:**
- [ ] `"\\nAI Engineer"` in JSON decodes to `"\nAI Engineer"`, NOT `"\\nAI Engineer"`.
- [ ] `"\\newcommand{\\foo}"` in JSON preserves `\\newcommand`.
- [ ] No `! Undefined control sequence \n` generated in output LaTeX.

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_latex_sanitizer.py -v`

**Files likely touched:**
- `backend/core/latex_sanitizer.py`
- `tests/test_latex_sanitizer.py`

---

## Task 2: Fix `\IEEEauthorblockA` in `backend/templates/ieee_starter.tex`
**Description:** Update `\IEEEauthorblockA` to wrap affiliations in `\begin{tabular}{@{}c@{}}\itshape #1\end{tabular}\\` so that multi-line affiliations containing `\\` can be safely typeset inside `article.cls`'s `\author` tabular without causing `! Missing } inserted.`.

**Acceptance criteria:**
- [ ] Multi-line author blocks containing `\\` inside `\IEEEauthorblockA` compile cleanly with Tectonic.
- [ ] `! Missing } inserted. l.33 \begin{abstract}` error is eliminated.

**Verification:**
- [ ] Run python script to compile `ieee_starter.tex` with multi-line affiliation using Tectonic.

**Files likely touched:**
- `backend/templates/ieee_starter.tex`

---

## Task 3: Fix `MathHandler` in `backend/core/latex_compatibility.py`
**Description:**
1. Fix `is_math_error()` so it does NOT match benign Tectonic package-loading log messages like `(mathtools.sty ...)`.
2. Fix `inject_math_packages()` regex to detect packages within comma-separated `\usepackage{amsmath,amssymb}` and avoid repeatedly injecting duplicate package lines.

**Acceptance criteria:**
- [ ] `is_math_error` returns `False` when log only contains package loading notifications `(mathtools.sty)`.
- [ ] `inject_math_packages` recognizes existing packages in `\usepackage{amsmath,amssymb}` and does not inject duplicate `\usepackage` lines.

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_latex_compatibility.py -v`

**Files likely touched:**
- `backend/core/latex_compatibility.py`
- `tests/test_latex_compatibility.py`

---

## Task 4: Fix `strip_zone_markers` in `backend/core/zone_document.py`
**Description:** Update `strip_zone_markers` to remove any existing `% ZONE:.*?:START` and `% ZONE:.*?:END` comments so that nested duplicate markers (`% ZONE:3:START\n% ZONE:3:START`) are never produced when re-wrapping zone bodies.

**Acceptance criteria:**
- [ ] Calling `wrap_zone_body` on a block that already had zone markers results in exactly one outer pair of `% ZONE:N:START` / `% ZONE:N:END`.
- [ ] No duplicate nested zone markers in `doc.assemble()`.

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_zone_document.py -v` (or relevant test suite).

**Files likely touched:**
- `backend/core/zone_document.py`

---

## Checkpoint: All Core Fixes Complete
- [ ] `backend\.venv\Scripts\pytest.exe -k "not e2e and not test_zone_compilation"` passes 100%.
- [ ] Test compiling a resume with layout squeeze and an IEEE research paper end-to-end.
