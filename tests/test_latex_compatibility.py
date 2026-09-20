import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.compiler import compiler
from core.latex_compatibility import (
    ColorHandler,
    ErrorClassifier,
    FontHandler,
    PackageHandler,
)


def test_classify_latex_error():
    font_log = (
        'error: simpleresumecv.cls:148: Package fontspec Error: '
        'The font "Tinos-Regular" cannot be found.'
    )
    assert ErrorClassifier.classify(font_log) == "font"

    color_log = (
        "error: resume.tex:66: Package xcolor Error: "
        "Undefined color `awesome-red'."
    )
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
    log_err = (
        'Package fontspec Error: The font "Tinos-Regular" cannot be found.'
    )
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
    """Verify compiler auto repairs and succeeds on undefined color."""
    src = r"""
\documentclass{article}
\usepackage{xcolor}
\begin{document}
\textcolor{customaccentcolor}{Hello World}
\end{document}
"""
    pdf_bytes = compiler.compile(src)
    assert len(pdf_bytes) > 0


def test_math_handler_repair():
    from core.latex_compatibility import MathHandler

    math_log = "! Undefined control sequence. l.15 \\align"
    assert MathHandler.is_math_error(math_log)

    src = "\\documentclass{article}\n\\begin{document}\n\\end{document}"
    new_src, act = MathHandler.inject_math_packages(src)
    assert act is not None
    assert "\\usepackage{amsmath,amssymb,mathtools}" in new_src


def test_table_handler_repair():
    from core.latex_compatibility import TableHandler

    table_log = "! Undefined control sequence. l.20 \\toprule"
    assert TableHandler.is_table_error(table_log)

    src = "\\documentclass{article}\n\\begin{document}\n\\end{document}"
    new_src, act = TableHandler.inject_table_packages(src)
    assert act is not None
    assert "\\usepackage{booktabs,multirow}" in new_src


def test_citation_handler_repair():
    from core.latex_compatibility import CitationHandler

    cite_log = (
        "LaTeX Warning: Citation `vaswani2017' on page 1 "
        "undefined on input line 40."
    )
    missing = CitationHandler.extract_missing_citation(cite_log)
    assert missing == "vaswani2017"

    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\cite{vaswani2017}\n"
        "\\end{document}"
    )
    new_src, act = CitationHandler.insert_placeholder_bibitem(src, missing)
    assert act is not None
    assert "\\bibitem{vaswani2017}" in new_src


def test_figure_handler_repair():
    from core.latex_compatibility import FigureHandler

    fig_log = "! LaTeX Error: File `figures/arch.png' not found."
    missing = FigureHandler.extract_missing_figure(fig_log)
    assert missing == "figures/arch.png"

    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics{figures/arch.png}\n"
        "\\end{document}"
    )
    new_src, act = FigureHandler.substitute_figure(src, missing)
    assert act is not None
    assert "\\fbox" in new_src


def test_error_classifier_prioritizes_fatal_over_warning():
    """Fatal table error takes priority over citation warning in log."""
    mixed_log = (
        "LaTeX Warning: Citation `smith2020' on page 1 "
        "undefined on input line 5.\n"
        "! Undefined control sequence. l.25 \\toprule\n"
    )
    assert ErrorClassifier.classify(mixed_log) == "table"
