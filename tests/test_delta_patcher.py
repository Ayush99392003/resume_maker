"""Unit tests for backend.core.delta_patcher."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.delta_patcher import apply_line_delta, patch_latex, apply_zone_delta

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_LINES = [
    "\\documentclass{article}",  # 1
    "\\begin{document}",          # 2
    "% ZONE:2:START",             # 3
    "\\section{Experience}",       # 4
    "\\item Bad line A",           # 5
    "\\item Bad line B",           # 6
    "% ZONE:2:END",               # 7
    "\\end{document}",            # 8
]

LATEX_STR = "\n".join(BASE_LINES) + "\n"


# ---------------------------------------------------------------------------
# apply_line_delta
# ---------------------------------------------------------------------------

class TestApplyLineDelta:
    def test_single_line_replacement(self):
        delta = {"5": "\\begin{itemize}\\item Fixed A\\end{itemize}"}
        result = apply_line_delta(list(BASE_LINES), delta)
        assert "\\begin{itemize}" in result[4]
        assert "\\item Bad line A" not in result

    def test_range_replacement(self):
        delta = {"5-6": "\\begin{itemize}\n\\item Fixed\n\\end{itemize}"}
        result = apply_line_delta(list(BASE_LINES), delta)
        flat = "\n".join(result)
        assert "\\item Fixed" in flat
        assert "\\item Bad line A" not in flat
        assert "\\item Bad line B" not in flat

    def test_empty_delta_returns_unchanged(self):
        result = apply_line_delta(list(BASE_LINES), {})
        assert result == BASE_LINES

    def test_out_of_range_key_is_skipped(self):
        delta = {"999": "ghost line"}
        result = apply_line_delta(list(BASE_LINES), delta)
        assert result == BASE_LINES

    def test_invalid_key_format_is_skipped(self):
        delta = {"abc": "should be skipped"}
        result = apply_line_delta(list(BASE_LINES), delta)
        assert result == BASE_LINES

    def test_multiple_ranges_applied_bottom_up(self):
        delta = {
            "5": "\\begin{itemize}",
            "6": "\\item Fixed",
        }
        result = apply_line_delta(list(BASE_LINES), delta)
        assert result[4] == "\\begin{itemize}"
        assert result[5] == "\\item Fixed"

    def test_preserves_surrounding_lines(self):
        delta = {"5": "\\begin{itemize}\\item X\\end{itemize}"}
        result = apply_line_delta(list(BASE_LINES), delta)
        assert result[0] == "\\documentclass{article}"
        assert result[1] == "\\begin{document}"
        assert result[-1] == "\\end{document}"


# ---------------------------------------------------------------------------
# patch_latex
# ---------------------------------------------------------------------------

class TestPatchLatex:
    def test_patch_latex_applies_to_string(self):
        delta = {"5": "\\begin{itemize}\\item Good A\\end{itemize}"}
        result = patch_latex(LATEX_STR, delta)
        assert "\\begin{itemize}" in result
        assert "\\item Bad line A" not in result

    def test_patch_latex_preserves_trailing_newline(self):
        delta = {"5": "replaced"}
        result = patch_latex(LATEX_STR, delta)
        assert result.endswith("\n")

    def test_empty_delta_returns_original(self):
        assert patch_latex(LATEX_STR, {}) == LATEX_STR


# ---------------------------------------------------------------------------
# apply_zone_delta
# ---------------------------------------------------------------------------

class TestApplyZoneDelta:
    def test_replaces_zone_content(self):
        fixed_inner = (
            "\\section{Experience}\n"
            "\\begin{itemize}\n"
            "\\item Fixed bullet\n"
            "\\end{itemize}"
        )
        result = apply_zone_delta(LATEX_STR, "2", fixed_inner)
        assert "\\item Fixed bullet" in result
        assert "\\item Bad line A" not in result

    def test_preserves_zone_markers(self):
        fixed_inner = "\\section{Skills}\nPython, LaTeX"
        result = apply_zone_delta(LATEX_STR, "2", fixed_inner)
        assert "% ZONE:2:START" in result
        assert "% ZONE:2:END" in result

    def test_invalid_zone_returns_original(self):
        original = LATEX_STR
        result = apply_zone_delta(LATEX_STR, "NONEXISTENT", "content")
        assert result == original
