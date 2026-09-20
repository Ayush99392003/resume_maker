"""Tests for latex_sanitizer and style_agent."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.latex_sanitizer import safe_escape_latex_text, safe_extract_json
from core.style_agent import (
    apply_color_theme,
    apply_column_layout,
    apply_font_family,
    apply_font_size,
    apply_margins,
    style_agent,
)


def test_safe_extract_json_markdown_fences():
    raw = (
        "```json\n"
        '{"content": "\\begin{itemize}\\item Worked on Python\\end{itemize}", '
        '"summary": "Updated summary"}\n'
        "```"
    )
    data = safe_extract_json(raw)
    assert "content" in data
    assert "\\begin{itemize}" in data["content"]
    assert data["summary"] == "Updated summary"


def test_safe_extract_json_preserves_latex_linebreaks():
    raw = (
        '{"address": "City, State \\\\ email@example.com \\\\ '
        '(555) 555-5555"}'
    )
    data = safe_extract_json(raw)
    assert "\\\\" in data["address"]


def test_safe_extract_json_preserves_control_sequences():
    raw = (
        '{"latex": "\\begin{itemize}\\n\\item \\resumeItem{FastAPI backend}'
        '\\n\\item \\textbf{Key achievement}\\end{itemize}"}'
    )
    data = safe_extract_json(raw)
    assert "\\begin{itemize}" in data["latex"]
    assert "\\resumeItem{FastAPI backend}" in data["latex"]
    assert "\\textbf{Key achievement}" in data["latex"]


def test_safe_escape_latex_text_hex_colors_and_macros():
    text = "Color #2563EB and macro #1 with bare # in text"
    escaped = safe_escape_latex_text(text)
    assert "#2563EB" in escaped
    assert "#1" in escaped
    assert r"\#" in escaped


def test_safe_escape_latex_text_inline_percent_vs_comment():
    text = (
        "% ZONE:1:START\n"
        "Increased revenue by 50% year over year.\n"
        "% ZONE:1:END\n"
    )
    escaped = safe_escape_latex_text(text)
    assert "% ZONE:1:START" in escaped
    assert "% ZONE:1:END" in escaped
    assert r"50\%" in escaped


def test_safe_escape_latex_text_protected_commands():
    text = (
        r"\href{https://example.com/foo_bar#anchor}{Click Here} and "
        r"\cite{author_2020} and \includegraphics{figures/model_arch.png} and "
        r"\colorlet{dest_color}{src_color} and \label{sec_1}"
    )
    escaped = safe_escape_latex_text(text)
    assert r"\href{https://example.com/foo_bar#anchor}" in escaped
    assert r"\cite{author_2020}" in escaped
    assert r"\includegraphics{figures/model_arch.png}" in escaped
    assert r"\colorlet{dest_color}{src_color}" in escaped
    assert r"\label{sec_1}" in escaped


def test_safe_escape_latex_text_math_environments():
    text = (
        r"\begin{align} a & b \\ c & d \end{align} and "
        r"$\alpha_i & \beta_j$ and $x_1 + x_2$"
    )
    escaped = safe_escape_latex_text(text)
    assert r"\begin{align} a & b \\ c & d \end{align}" in escaped
    assert r"$\alpha_i & \beta_j$" in escaped
    assert r"$x_1 + x_2$" in escaped


def test_style_agent_heuristic_margins():
    req = style_agent._heuristic_parse("set 0.5in margins")
    assert req.margins == "0.5in"

    req2 = style_agent._heuristic_parse("use compact margins and 11pt font")
    assert req2.margins == "compact"
    assert req2.font_size == "11pt"

    req3 = style_agent._heuristic_parse(
        "switch to twocolumn layout with blue theme"
    )
    assert req3.column_layout == "twocolumn"
    assert req3.color_theme == "blue"


def test_style_agent_modifies_header():
    header = "\\documentclass{article}\n\\begin{document}\n"
    h1, _ = apply_font_family(header, "times")
    assert "newtxtext" in h1

    h2, _ = apply_font_size(h1, "11pt")
    assert "\\documentclass[11pt]{article}" in h2

    h3, _ = apply_color_theme(h2, theme="royal_blue")
    assert "\\definecolor{primary}{HTML}{2563EB}" in h3

    h4, _ = apply_margins(h3, "0.5in")
    assert "\\usepackage[margin=0.5in]{geometry}" in h4

    h5, _ = apply_column_layout(h4, "twocolumn")
    assert "twocolumn" in h5
