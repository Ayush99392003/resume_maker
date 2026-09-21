"""Tests for LaTeX → numbered zones conversion and assemble."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.latex_to_zones import latex_to_zones

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


def test_resilient_reorder_and_move():
    doc = latex_to_zones(SAMPLE)
    # doc has zones 1, 2, 3
    # Partial reorder: [3, 1] should keep 3, 1 and append 2
    doc.reorder([3, 1])
    assert doc.zone_order == [3, 1, 2]
    # Extra IDs in reorder should be filtered out safely
    doc.reorder([2, 999, 1])
    assert doc.zone_order == [2, 1, 3]
    # Move zone 3 to target_index 0
    doc.move(3, target_index=0)
    assert doc.zone_order == [3, 2, 1]
    # Move zone 3 to target_index 2 (end)
    doc.move(3, target_index=2)
    assert doc.zone_order == [2, 1, 3]


def test_mode_aware_add_zone():
    doc = latex_to_zones(SAMPLE)
    # Research paper mode should generate \section{...}
    paper_rec = doc.add_zone(
        description="Related Work",
        document_mode="research_paper",
    )
    assert r"\section{Related Work}" in paper_rec.latex
    assert "% TODO" not in paper_rec.latex

    # Resume mode should generate \section*{...}
    resume_rec = doc.add_zone(
        description="Certifications",
        document_mode="resume",
    )
    assert r"\section*{Certifications}" in resume_rec.latex



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


def test_nested_braces_and_academic_environments():
    latex = r"""
\documentclass{article}
\begin{document}
\title{Paper Title}
\author{Alice Smith}
\maketitle

\begin{abstract}
This is the abstract.
\end{abstract}

\begin{IEEEkeywords}
deep learning, optimization
\end{IEEEkeywords}

  \section{\textbf{Introduction and Background}}
Intro text here.

\section{Methodology \& Design}
Method text here.

\appendix
Appendix content.

\begin{thebibliography}{99}
\bibitem{ref1} Author, Title, 2024.
\end{thebibliography}
\end{document}
"""
    doc = latex_to_zones(latex)
    descriptions = [z.description for z in doc.zones]
    assert "Title and authors" in descriptions
    assert "Abstract" in descriptions
    assert "Keywords / Index terms" in descriptions
    assert "Introduction And Background" in descriptions
    assert "Methodology And Design" in descriptions
    assert "References" in descriptions
    assert "Appendix" in descriptions


def test_ieee_starter_descriptions_preserved_with_numeric_markers():
    latex = r"""
\documentclass{article}
\begin{document}
% ZONE:1:START
\title{\textbf{Neural Representation}}
\author{Alex Rivera}
\date{}
\maketitle
% ZONE:1:END

% ZONE:2:START
\begin{abstract}
Abstract text.
\end{abstract}
% ZONE:2:END

% ZONE:3:START
\paragraph{\textbf{Index Terms}}
Distributed systems, document engineering.
% ZONE:3:END

% ZONE:4:START
\section{Introduction}
Intro text.
% ZONE:4:END
\end{document}
"""
    doc = latex_to_zones(latex)
    assert doc.zones[0].description == "Title and authors"
    assert doc.zones[0].kind == "predefined_title_authors"
    assert doc.zones[1].description == "Abstract"
    assert doc.zones[1].kind == "predefined_abstract"
    assert "Index Terms" in doc.zones[2].description
    assert doc.zones[2].kind == "predefined_keywords"
    assert doc.zones[3].description == "Introduction"

    # Now simulate adding a new zone "Related Work" after Zone 4
    rec = doc.add_zone(
        description="Related Work",
        after_zone_no=4,
        document_mode="research_paper",
    )
    assert rec.description == "Related Work"
    # Verify Zone 1 and Zone 3 did NOT become "Zone 1" or "Zone 3"
    assert doc.zones[0].description == "Title and authors"
    assert "Index Terms" in doc.zones[2].description
