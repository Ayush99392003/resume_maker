"""Verify soften turns Harshibar-like Overleaf TeX into a compilable PDF."""

from __future__ import annotations

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from core.compiler import apply_fontconfig_env, compiler, ensure_fontconfig_files
from core.latex_soften import soften_latex_for_tectonic
from core.zone_document import ensure_full_document

COMPAT = BACKEND / "data" / "imports" / "harshibar_render" / "resume_compat.tex"
OUT = BACKEND / "data" / "imports" / "harshibar_render" / "harshibar_softened.pdf"

CRASHY_PREAMBLE = r"""
\usepackage{fontawesome5}
\usepackage[Scale=0.85]{FiraMono}
\usepackage{contour}
\contourlength{0.4pt}
\newcommand{\myulineCrash}[1]{%
  \contour{white}{\underline{#1}}
}
"""


def main() -> None:
    ensure_fontconfig_files()
    apply_fontconfig_env()
    compat = COMPAT.read_text(encoding="utf-8")
    raw = compat.replace(
        r"\usepackage[normalem]{ulem}",
        r"\usepackage[normalem]{ulem}" + "\n" + CRASHY_PREAMBLE,
        1,
    )
    raw = raw.replace("Tel", r"\faPhone*", 1)
    raw = raw.replace("Email", r"\faEnvelope", 1)
    raw = raw.replace("YT", r"\faYoutube", 1)
    raw = raw.replace("Loc", r"\faMapMarker*", 1)

    soft, notes = soften_latex_for_tectonic(raw)
    print("compat_notes:", notes)
    assert any("fontawesome5" in n for n in notes), notes
    assert r"\usepackage{fontawesome5}" not in soft
    latex = ensure_full_document(soft)
    pdf = compiler.compile(latex)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(pdf)
    print(f"OK pdf_bytes={len(pdf)} path={OUT}")


if __name__ == "__main__":
    main()
