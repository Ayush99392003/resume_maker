"""Unit tests for dynamic zone engine."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.zones import zone_engine  # noqa: E402


SAMPLE = r"""
\documentclass{article}
\begin{document}
% ZONE:SUMMARY:START
Hello
% ZONE:SUMMARY:END
\section{Experience}
% ZONE:EXPERIENCE:START
Old job
% ZONE:EXPERIENCE:END
\end{document}
"""


def test_list_and_extract():
    assert zone_engine.list_zones(SAMPLE) == ["SUMMARY", "EXPERIENCE"]
    zones = zone_engine.extract_zones(SAMPLE)
    assert "Hello" in zones["SUMMARY"]
    assert "Old job" in zones["EXPERIENCE"]


def test_replace_preserves_markers():
    updated = zone_engine.replace_zone(SAMPLE, "EXPERIENCE", "New role\\\\")
    assert "% ZONE:EXPERIENCE:START" in updated
    assert "% ZONE:EXPERIENCE:END" in updated
    assert "New role" in updated
    assert "Old job" not in updated
    assert "Hello" in updated


def test_validate_ok():
    ok, issues = zone_engine.validate(SAMPLE)
    assert ok
    assert issues == []
