"""Tectonic-compat softening for Overleaf pastes."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.latex_soften import soften_latex_for_tectonic  # noqa: E402


RAW = r"""
\documentclass{article}
\usepackage{fontawesome5}
\usepackage[Scale=0.85]{FiraMono}
\usepackage{contour}
\RequirePackage{fontspec}
\newcommand{\myuline}[1]{%
  \contour{white}{\underline{#1}}
}
\begin{document}
\faPhone* 555 \faEnvelope hi@x.com
\myuline{link}
\end{document}
"""


def test_soften_disables_crashy_packages():
    out, notes = soften_latex_for_tectonic(RAW)
    joined = " ".join(notes)
    assert "fontawesome5" in joined
    assert "FiraMono" in joined
    assert "contour" in joined or "myuline" in joined
    assert r"\usepackage{fontawesome5}" not in out
    assert "% fontawesome5 disabled" in out
    assert "% FiraMono disabled" in out
    assert "Tel" in out and "Email" in out
    assert r"\faPhone" not in out


def test_soften_idempotent():
    once, _n1 = soften_latex_for_tectonic(RAW)
    twice, n2 = soften_latex_for_tectonic(once)
    assert once == twice
    assert n2 == []


def test_soften_myuline_keeps_brace_balance():
    """Non-greedy regex used to leave orphan }} from \\contour{white}{...}."""
    raw = r"""
\documentclass{article}
\usepackage{contour}
\contourlength{0.8pt}
\newcommand{\myuline}[1]{%
  \contour{white}{\underline{{\color{dark-grey}#1}}}
}
\begin{document}
\myuline{hello}
\end{document}
"""
    out, notes = soften_latex_for_tectonic(raw)
    assert "rewrote \\myuline" in " ".join(notes)
    assert out.count("{") == out.count("}")
    assert r"\newcommand{\myuline}[1]{\textbf{#1}}" in out
    assert r"\contour{white}" not in out
    # Orphan remnant from the old buggy rewrite must not appear
    assert r"{\underline{{\color{dark-grey}#1}}}" not in out
