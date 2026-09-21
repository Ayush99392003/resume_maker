"""Unit tests for dynamic zone engine."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.zones import zone_engine

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


def test_strip_zone_markers_cleans_nested_or_named_markers():
    """strip_zone_markers must remove any existing zone markers from inner text."""
    from core.zone_document import ZoneDocument, strip_zone_markers

    # Case 1: Inner text that already contains zone markers
    nested_inner = (
        "% ZONE:3:START\n"
        "Some inner content\n"
        "% ZONE:3:END\n"
    )
    cleaned = strip_zone_markers(nested_inner, 3)
    assert "% ZONE:" not in cleaned
    assert "Some inner content" in cleaned

    # Case 2: Named zone markers from template
    named_inner = (
        "% ZONE:KEYWORDS:START\n"
        "Keyword content\n"
        "% ZONE:KEYWORDS:END\n"
    )
    cleaned_named = strip_zone_markers(named_inner, 3)
    assert "% ZONE:" not in cleaned_named
    assert "Keyword content" in cleaned_named

    # Case 3: Re-wrapping should never produce duplicate markers
    doc = ZoneDocument()
    wrapped = doc.wrap_zone_body(3, nested_inner)
    assert wrapped.count("% ZONE:3:START") == 1
    assert wrapped.count("% ZONE:3:END") == 1
