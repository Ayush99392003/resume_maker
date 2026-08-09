"""Tests for LaTeX → numbered zones conversion and assemble."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.latex_to_zones import latex_to_zones  # noqa: E402
from core.zone_document import ZoneDocument  # noqa: E402

SAMPLE = r"""
\documentclass{article}
\begin{document}
% ZONE:HEADER:START
{\Large Name}
% ZONE:HEADER:END

\section*{Summary}
% ZONE:SUMMARY:START
Hello bio
% ZONE:SUMMARY:END

\section*{Experience}
% ZONE:EXPERIENCE:START
Old job
% ZONE:EXPERIENCE:END
\end{document}
"""


def test_named_zones_become_numbered():
    doc = latex_to_zones(SAMPLE)
    assert doc.zone_order == [1, 2, 3]
    assert doc.zones[0].description == "Name, contact, links"
    assert "Summary" in doc.zone_inner(2) or "Hello bio" in doc.zone_inner(2)
    assert "\\begin{document}" in doc.header
    assert "\\end{document}" in doc.footer


def test_assemble_roundtrip_markers():
    doc = latex_to_zones(SAMPLE)
    assembled = doc.assemble()
    assert "% ZONE:1:START" in assembled
    assert "% ZONE:3:END" in assembled
    assert "\\begin{document}" in assembled
    assert assembled.count("\\end{document}") == 1


def test_add_remove_reorder():
    doc = latex_to_zones(SAMPLE)
    rec = doc.add_zone(description="Projects", after_zone_no=1)
    assert rec.zone_no == 4
    assert doc.zone_order[1] == 4
    doc.swap(1, 3)
    assert doc.zone_order[0] == 3
    removed = doc.remove_zone(4)
    assert removed.description == "Projects"
    assert 4 not in doc.zone_order


def test_section_split_without_markers():
    latex = r"""
\documentclass{article}
\begin{document}
John Doe\\
email@x.com
\section{Experience}
Worked hard
\section{Education}
BS CS
\end{document}
"""
    doc = latex_to_zones(latex)
    assert len(doc.zones) >= 2
    assert doc.next_zone_no == len(doc.zones) + 1
