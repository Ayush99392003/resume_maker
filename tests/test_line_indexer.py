import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.line_indexer import (
    build_line_index,
    zone_line_range,
    build_debug_payload,
    _error_line_numbers,
    _context_window,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_LATEX = """\
\\documentclass{article}
\\begin{document}
% ZONE:EXPERIENCE:START
\\section{Experience}
\\item Line A
\\item Line B
% ZONE:EXPERIENCE:END
\\end{document}
"""

NUMERIC_LATEX = """\
\\documentclass{article}
\\begin{document}
% ZONE:1:START
\\section{Header}
Name: John
% ZONE:1:END
% ZONE:2:START
\\section{Skills}
Python, LaTeX
% ZONE:2:END
\\end{document}
"""

ERROR_LOG = (
    "note: Running TeX ...\n"
    "error: resume.tex:5: LaTeX Error: Lonely \\item\n"
    "error: halted on potentially-recoverable error\n"
)


# ---------------------------------------------------------------------------
# build_line_index
# ---------------------------------------------------------------------------

class TestBuildLineIndex:
    def test_returns_1indexed_dict(self):
        idx = build_line_index("alpha\nbeta\ngamma")
        assert idx[1] == "alpha"
        assert idx[2] == "beta"
        assert idx[3] == "gamma"

    def test_empty_string_returns_empty_dict(self):
        assert build_line_index("") == {}

    def test_single_line_no_newline(self):
        idx = build_line_index("only line")
        assert idx == {1: "only line"}


# ---------------------------------------------------------------------------
# zone_line_range
# ---------------------------------------------------------------------------

class TestZoneLineRange:
    def test_named_zone_found(self):
        rng = zone_line_range(SIMPLE_LATEX, "EXPERIENCE")
        lines = SIMPLE_LATEX.splitlines()
        assert rng is not None
        start, end = rng
        assert "EXPERIENCE:START" in lines[start - 1]
        assert "EXPERIENCE:END" in lines[end - 1]

    def test_numeric_zone_found(self):
        rng = zone_line_range(NUMERIC_LATEX, "1")
        assert rng is not None
        assert rng[0] < rng[1]

    def test_nonexistent_zone_returns_none(self):
        assert zone_line_range(SIMPLE_LATEX, "NONEXISTENT") is None

    def test_range_is_inclusive(self):
        rng = zone_line_range(SIMPLE_LATEX, "EXPERIENCE")
        assert rng is not None
        lines = SIMPLE_LATEX.splitlines()
        # Both endpoints should be the ZONE marker lines
        assert "START" in lines[rng[0] - 1] or "END" in lines[rng[0] - 1]


# ---------------------------------------------------------------------------
# _error_line_numbers
# ---------------------------------------------------------------------------

class TestErrorLineNumbers:
    def test_extracts_single_line_number(self):
        assert _error_line_numbers(ERROR_LOG) == [5]

    def test_multiple_references(self):
        log = "resume.tex:10: error\nresume.tex:20: another error"
        assert _error_line_numbers(log) == [10, 20]

    def test_no_references_returns_empty(self):
        assert _error_line_numbers("nothing here") == []


# ---------------------------------------------------------------------------
# _context_window
# ---------------------------------------------------------------------------

class TestContextWindow:
    def test_window_includes_center_and_padding(self):
        idx = {i: f"line {i}" for i in range(1, 21)}
        window = _context_window(idx, [10], padding=2)
        assert set(window.keys()) == {8, 9, 10, 11, 12}

    def test_clamps_to_available_lines(self):
        idx = {1: "a", 2: "b", 3: "c"}
        window = _context_window(idx, [1], padding=10)
        assert set(window.keys()) == {1, 2, 3}


# ---------------------------------------------------------------------------
# build_debug_payload
# ---------------------------------------------------------------------------

class TestBuildDebugPayload:
    def test_payload_keys_present(self):
        payload = build_debug_payload(SIMPLE_LATEX, ERROR_LOG)
        assert "error_log" in payload
        assert "target_zone" in payload
        assert "line_range" in payload
        assert "lines" in payload

    def test_infers_zone_from_error_line(self):
        payload = build_debug_payload(SIMPLE_LATEX, ERROR_LOG)
        # line 5 is inside EXPERIENCE zone
        assert payload["target_zone"] == "EXPERIENCE"

    def test_lines_are_string_keyed(self):
        payload = build_debug_payload(NUMERIC_LATEX, ERROR_LOG)
        for key in payload["lines"]:
            assert isinstance(key, str)
            int(key)  # must be parseable as int

    def test_explicit_zone_id_override(self):
        payload = build_debug_payload(
            NUMERIC_LATEX, ERROR_LOG, zone_id="2"
        )
        assert payload["target_zone"] == "2"

    def test_error_log_truncated_to_800(self):
        long_log = "x" * 2000
        payload = build_debug_payload(SIMPLE_LATEX, long_log)
        assert len(payload["error_log"]) <= 800
