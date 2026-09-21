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


def test_math_handler_does_not_trigger_on_package_loading_banners():
    """Tectonic loading banners like (mathtools.sty) must not trigger math repair."""
    from core.latex_compatibility import MathHandler

    log_with_banners = (
        "(mathtools.sty (calc.sty) (mhsetup.sty))\n"
        "(amssymb.sty (amsfonts.sty))\n"
        "! Missing } inserted.\n"
        "l.43 \\begin{abstract}\n"
    )
    assert not MathHandler.is_math_error(log_with_banners)
    assert ErrorClassifier.classify(log_with_banners) != "math"


def test_math_handler_inject_does_not_duplicate_existing_packages():
    """Existing comma-separated packages must be detected to avoid duplicates."""
    from core.latex_compatibility import MathHandler

    src = (
        "\\documentclass{article}\n"
        "\\usepackage{amsmath,amssymb}\n"
        "\\begin{document}\n"
        "\\end{document}"
    )
    new_src, act = MathHandler.inject_math_packages(src)
    assert act is not None
    # Only mathtools should be added
    assert act["action"] == "injected \\usepackage{mathtools}"
    assert new_src.count("amsmath") == 1
    assert new_src.count("amssymb") == 1

    # If all 3 are present, no action
    src_all = (
        "\\documentclass{article}\n"
        "\\usepackage{amsmath,amssymb,mathtools}\n"
        "\\begin{document}\n"
        "\\end{document}"
    )
    new_src_all, act_none = MathHandler.inject_math_packages(src_all)
    assert act_none is None
    assert new_src_all == src_all


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


def test_math_handler_repair_missing_dollar():
    from core.latex_compatibility import MathHandler

    log_text = (
        "! Missing $ inserted.\n"
        "<inserted text>\n"
        "                $\n"
        "l.171 ...decay of \\$5 \\times 10\\^{-4}\\$. To account ...\n"
    )
    assert MathHandler.is_math_error(log_text)
    assert ErrorClassifier.classify(log_text) == "math"

    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "weight decay of \\$5 \\times 10\\^{-4}\\$.\n"
        "\\end{document}"
    )
    new_src, act = MathHandler.repair_math(src, log_text)
    assert act is not None
    assert "$5 \\times 10^{-4}$" in new_src
    assert "\\$5" not in new_src


def test_math_handler_repair_extra_rbrace_forgotten_dollar():
    from core.latex_compatibility import MathHandler

    log_text = (
        "! Extra }, or forgotten $.\n"
        "<template> \\unskip \\hfil }\n"
        "                          \\hskip\n"
        "\\tabcolsep \\endtemplate\n"
        "l.120 Licit (\\$0$)    &\n"
    )
    assert MathHandler.is_math_error(log_text)
    assert ErrorClassifier.classify(log_text) == "math"

    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{tabular}{lrr}\n"
        "Licit (\\$0$) & 42,019 & 20.62\\% \\\\\n"
        "\\end{tabular}\n"
        "\\end{document}"
    )
    new_src, act = MathHandler.repair_math(src, log_text)
    assert act is not None
    assert "($0$)" in new_src
    assert "\\$0$" not in new_src


def test_math_handler_repair_missing_brace():
    import re

    from core.latex_compatibility import MathHandler

    log_text = (
        "! Missing } inserted.\n"
        "<inserted text>\n"
        "                }\n"
        "l.110 \\end{align}\n"
    )
    assert MathHandler.is_math_error(log_text)
    assert ErrorClassifier.classify(log_text) == "math"

    src = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{align}\n"
        "\\mathcal{L} = -\\sum_{i=1}^N {y_i \\log(\\hat{y}_i)\n"
        "\\end{align}\n"
        "\\end{document}"
    )
    new_src, act = MathHandler.repair_math(src, log_text)
    assert act is not None
    assert "}" in act["action"]
    # Verify braces are now balanced in the align environment
    align_match = re.search(
        r"\\begin\{align\}(.*?)\\end\{align\}", new_src, re.DOTALL
    )
    assert align_match is not None
    body = align_match.group(1)
    assert body.count("{") == body.count("}")
