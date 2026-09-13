import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from core.compiler import compiler
from core.latex_compatibility import (
    ColorHandler,
    ErrorClassifier,
    FontHandler,
    PackageHandler,
    RepairEngine,
)


def test_classify_latex_error():
    font_log = 'error: simpleresumecv.cls:148: Package fontspec Error: The font "Tinos-Regular" cannot be found.'
    assert ErrorClassifier.classify(font_log) == "font"

    color_log = "error: resume.tex:66: Package xcolor Error: Undefined color `awesome-red'."
    assert ErrorClassifier.classify(color_log) == "color"

    file_log = "! LaTeX Error: File `particulars.tex' not found."
    assert ErrorClassifier.classify(file_log) == "package_or_file"

    cmd_log = "! Undefined control sequence. l.12 \\badmacro"
    assert ErrorClassifier.classify(cmd_log) == "command"


def test_font_handler_repair():
    src = r"""
\documentclass{article}
\usepackage{fontspec}
\setmainfont{Tinos-Regular}
\setsansfont{Montserrat}
\setmonofont{Fira Code}
\begin{document}
Hello
\end{document}
"""
    log_err = 'Package fontspec Error: The font "Tinos-Regular" cannot be found.'
    missing = FontHandler.extract_missing_font(log_err)
    assert missing == "Tinos-Regular"

    repaired, action = FontHandler.repair_missing_font(src, missing)
    assert action is not None
    assert action["type"] == "font"
    assert "TeX Gyre Termes" in repaired
    assert "Tinos-Regular" not in repaired


def test_color_handler_repair():
    src = r"""
\documentclass{article}
\usepackage{xcolor}
\begin{document}
\textcolor{awesome-red}{Important Text}
\end{document}
"""
    log_err = "Package xcolor Error: Undefined color `awesome-red'."
    missing = ColorHandler.extract_missing_color(log_err)
    assert missing == "awesome-red"

    repaired, action = ColorHandler.define_missing_color(src, missing)
    assert action is not None
    assert action["type"] == "color"
    assert r"\providecolor{awesome-red}" in repaired


def test_package_handler_missing_file():
    src = r"""
\documentclass{article}
\begin{document}
\input{particulars.tex}
Content
\end{document}
"""
    log_err = "! LaTeX Error: File `particulars.tex' not found."
    missing = PackageHandler.extract_missing_file(log_err)
    assert missing == "particulars.tex"

    repaired, action = PackageHandler.repair_missing_file(src, missing)
    assert action is not None
    assert "removed missing \\input{particulars.tex}" in repaired


def test_compiler_auto_repairs_undefined_color():
    """Verify compiler automatically repairs and succeeds on undefined color."""
    src = r"""
\documentclass{article}
\usepackage{xcolor}
\begin{document}
\textcolor{customaccentcolor}{Hello World}
\end{document}
"""
    pdf_bytes = compiler.compile(src)
    assert len(pdf_bytes) > 0
