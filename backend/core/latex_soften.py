"""Make pasted Overleaf-style LaTeX safer for Windows Tectonic."""

from __future__ import annotations

import re

try:
    from core.logging_setup import get_logger
except ImportError:
    from .logging_setup import get_logger

log = get_logger("latex_soften")

# Packages that crash or require XeTeX/LuaTeX on this Windows Tectonic build.
_CRASHY_PACKAGES = (
    "fontawesome5",
    "fontawesome",
    "FiraMono",
    "contour",
)

_PKG_LINE = re.compile(
    r"^([ \t]*)\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{("
    + "|".join(re.escape(p) for p in _CRASHY_PACKAGES)
    + r")\}[ \t]*$",
    re.MULTILINE,
)

_ICON_REPLACEMENTS = [
    (r"\faPhone*", "Tel"),
    (r"\faPhone", "Tel"),
    (r"\faEnvelope", "Email"),
    (r"\faYoutube", "YT"),
    (r"\faMapMarker*", "Loc"),
    (r"\faMapMarker", "Loc"),
    (r"\faGithub", "GitHub"),
    (r"\faLinkedin", "LinkedIn"),
    (r"\faGlobe", "Web"),
    (r"\faTwitter", "Twitter"),
    (r"\faHome", "Home"),
]

_SIMPLE_MYULINE = r"\newcommand{\myuline}[1]{\textbf{#1}}"


def _replace_newcommand_body(src: str, macroname: str, new_def: str) -> tuple[str, bool]:
    """
    Replace \\newcommand{\\macroname}[n]{...} using brace-balanced matching.
    Avoids the classic bug where a non-greedy regex stops at the first '}'.
    """
    for prefix in (r"\newcommand", r"\renewcommand"):
        needle = f"{prefix}{{\\{macroname}}}"
        idx = src.find(needle)
        if idx < 0:
            continue
        i = idx + len(needle)
        # optional [n]
        if i < len(src) and src[i] == "[":
            close = src.find("]", i)
            if close < 0:
                return src, False
            i = close + 1
        if i >= len(src) or src[i] != "{":
            return src, False
        depth = 0
        j = i
        while j < len(src):
            ch = src[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return src[:idx] + new_def + src[j + 1 :], True
            j += 1
        return src, False
    return src, False


def soften_latex_for_tectonic(latex: str) -> tuple[str, list[str]]:
    """
    Disable packages that commonly crash this Tectonic Windows build
    and replace FA icons with text.

    Returns (softened_latex, list of human-readable change notes).
    """
    src = latex or ""
    changes: list[str] = []
    if not src.strip():
        return src, changes

    # Pass options to xcolor before \documentclass to prevent option clashes
    if not re.search(r"\\PassOptionsToPackage\{[^}]*\}\{xcolor\}", src):
        doc_match = re.search(r"^[ \t]*\\documentclass", src, re.MULTILINE)
        if doc_match:
            pass_opt = (
                "\\PassOptionsToPackage"
                "{dvipsnames,svgnames,x11names}{xcolor}\n"
            )
            src = (
                src[: doc_match.start()]
                + pass_opt
                + src[doc_match.start() :]
            )
            changes.append("added \\PassOptionsToPackage for xcolor")

    disabled: list[str] = []

    # ------------------------------------------------------------------ #
    # pdfTeX-only primitives — Tectonic uses XeTeX so these always crash. #
    # Strip them up-front so the AI fixer never wastes retry budget here. #
    # ------------------------------------------------------------------ #

    # \input{glyphtounicode} — pdfTeX glyph-mapping, not available in XeTeX
    src2, n_glyph = re.subn(
        r"^[ \t]*\\input\{glyphtounicode\}[ \t]*$",
        "% glyphtounicode disabled (pdfTeX-only, not available in Tectonic/XeTeX)",
        src,
        flags=re.MULTILINE,
    )
    if n_glyph:
        src = src2
        changes.append("disabled \\input{glyphtounicode} (pdfTeX-only)")

    # \pdfgentounicode=1 — pdfTeX primitive
    src2, n_pdfgen = re.subn(
        r"^[ \t]*\\pdfgentounicode\s*=\s*\d+[ \t]*$",
        "% pdfgentounicode disabled (pdfTeX-only, not available in Tectonic/XeTeX)",
        src,
        flags=re.MULTILINE,
    )
    if n_pdfgen:
        src = src2
        changes.append("disabled \\pdfgentounicode (pdfTeX-only)")

    # \input{particulars} or \input{particulars.tex} — orphaned Overleaf
    # side-file reference.  Match both forms (with and without .tex extension).
    # Comment the line out so compile can proceed without the file.
    src2, n_part = re.subn(
        r"^([ \t]*)\\input\{particulars(?:\.tex)?\}([ \t]*)$",
        r"\1% \\input{particulars} disabled (side-file not present)\2",
        src,
        flags=re.MULTILINE,
    )
    if n_part:
        src = src2
        changes.append("disabled \\input{particulars} (side-file not present)")

    def _disable_pkg(m: re.Match) -> str:
        pkg = m.group(2)
        if pkg not in disabled:
            disabled.append(pkg)
        return f"{m.group(1)}% {pkg} disabled (Tectonic compat)"

    new_src, n = _PKG_LINE.subn(_disable_pkg, src)
    if n:
        src = new_src
        for pkg in disabled:
            changes.append(f"disabled {pkg}")

    # ------------------------------------------------------------------ #
    # xcolor: upgrade to dvipsnames+svgnames so named colors like         #
    # NAVYBLUE, Maroon, DarkSlateBlue etc. resolve without errors.        #
    # Only touch \usepackage{xcolor} lines that have NO option list yet.  #
    # ------------------------------------------------------------------ #
    _XCOLOR_BARE = re.compile(
        r"^([ \t]*)\\usepackage(\s*)\{xcolor\}([ \t]*)$",
        re.MULTILINE,
    )
    _XCOLOR_OPTS = re.compile(
        r"\\usepackage\s*\[[^\]]*\]\s*\{xcolor\}",
    )
    if _XCOLOR_BARE.search(src) and not _XCOLOR_OPTS.search(src):
        src2, n_xc = _XCOLOR_BARE.subn(
            r"\1\\usepackage[dvipsnames,svgnames,x11names]\2{xcolor}\3",
            src,
        )
        if n_xc:
            src = src2
            changes.append(
                "upgraded \\usepackage{xcolor} -> [dvipsnames,svgnames,x11names]"
            )
    elif _XCOLOR_OPTS.search(src):
        # Already has options — ensure dvipsnames is present
        def _add_dvipsnames(m: re.Match) -> str:
            opts = m.group(0)
            if "dvipsnames" not in opts:
                opts = opts.replace(
                    "\\usepackage[",
                    "\\usepackage[dvipsnames,svgnames,",
                    1,
                )
                return opts
            return m.group(0)
        src2 = _XCOLOR_OPTS.sub(_add_dvipsnames, src)
        if src2 != src:
            src = src2
            changes.append("added dvipsnames to \\usepackage[...]{xcolor}")

    # Contour-based \myuline (Harshibar etc.) — brace-balanced rewrite
    if r"\myuline" in src and (
        r"\contour" in src
        or r"\newcommand{\myuline}" in src
        or r"\renewcommand{\myuline}" in src
    ):
        src2, ok = _replace_newcommand_body(src, "myuline", _SIMPLE_MYULINE)
        if ok and src2 != src:
            src = src2
            changes.append("rewrote \\myuline without contour")

    src2, n = re.subn(r"\\contourlength\{[^}]*\}\s*", "", src)
    if n:
        src = src2
        changes.append("removed \\contourlength")

    # Strip remaining \contour{color}{text} with nested braces in text
    while True:
        m = re.search(r"\\contour\{", src)
        if not m:
            break
        # color arg
        i = m.end() - 1  # at '{'
        depth = 0
        j = i
        color_end = -1
        while j < len(src):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    color_end = j
                    break
            j += 1
        if color_end < 0 or color_end + 1 >= len(src) or src[color_end + 1] != "{":
            break
        # text arg
        k = color_end + 1
        depth = 0
        text_start = k + 1
        text_end = -1
        while k < len(src):
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
                if depth == 0:
                    text_end = k
                    break
            k += 1
        if text_end < 0:
            break
        inner = src[text_start:text_end]
        src = src[: m.start()] + inner + src[text_end + 1 :]
        changes.append("stripped \\contour{...}{text}")

    # ------------------------------------------------------------------ #
    # Font remapping: map non-standard fonts to TeX Gyre instead of      #
    # stripping \setmainfont / \setsansfont / \setmonofont declarations. #
    # ------------------------------------------------------------------ #
    _STANDARD_FONTS = frozenset(
        [
            "tex gyre termes",
            "tex gyre heros",
            "tex gyre cursor",
            "tex gyre pagella",
            "tex gyre bonum",
            "tex gyre schola",
            "tex gyre adventor",
            "times new roman",
            "arial",
            "helvetica",
            "courier new",
            "consolas",
            "georgia",
            "verdana",
            "calibri",
            "cambria",
            "dejavu sans",
            "liberation sans",
            "latin modern roman",
            "latin modern sans",
            "latin modern mono",
        ]
    )

    def _remap_font(match: re.Match) -> str:
        cmd = match.group(1)
        opts = match.group(2) or ""
        fname = match.group(3).strip()
        low = fname.lower()
        if low in _STANDARD_FONTS:
            return match.group(0)

        # Classify font family
        if "sans" in cmd.lower() or any(
            k in low
            for k in (
                "sans",
                "helvetica",
                "arial",
                "roboto",
                "lato",
                "montserrat",
            )
        ):
            fallback = "TeX Gyre Heros"
        elif "mono" in cmd.lower() or any(
            k in low
            for k in ("mono", "code", "courier", "fira", "consolas")
        ):
            fallback = "TeX Gyre Cursor"
        else:
            fallback = "TeX Gyre Termes"

        changes.append(f"mapped non-standard font '{fname}' -> '{fallback}'")
        return f"{cmd}{opts}{{{fallback}}}"

    _FONT_CMD_RE = re.compile(
        r"(\\(?:setmainfont|setsansfont|setmonofont))"
        r"([ \t]*\[[^\]]*\])?[ \t]*\{([^}]+)\}"
    )
    src = _FONT_CMD_RE.sub(_remap_font, src)

    for a, b in _ICON_REPLACEMENTS:
        if a in src:
            src = src.replace(a, b)
            changes.append(f"replaced {a} -> {b}")

    # Strip [pdftex] driver option from \usepackage[pdftex]{hyperref} for Tectonic/XeTeX compatibility
    src2, n_hyp = re.subn(r"\\usepackage\[[^\]]*pdftex[^\]]*\]\{hyperref\}", r"\\usepackage{hyperref}", src)
    if n_hyp:
        src = src2
        changes.append("removed [pdftex] driver option from hyperref package")

    # Auto-repair stripped \esume macros from legacy session state
    if r"\esume" in src:
        src, n = re.subn(r"\\esume([A-Za-z])", r"\\resume\1", src)
        if n:
            changes.append("repaired \\esume -> \\resume")

    # Remaining Font Awesome icons: \faPhone, \faGithub, \faMapMarker* …
    # Require a capital letter after "fa" so we never touch \fancyhf / \familydefault.
    leftover_fa = sorted(set(re.findall(r"\\fa[A-Z][A-Za-z]*\*?", src)))
    if leftover_fa:
        src = re.sub(r"\\fa[A-Z][A-Za-z]*\*?", "", src)
        changes.append(f"stripped leftover FA macros: {', '.join(leftover_fa)}")

    # Common resume macros that may be used across different template types
    _FALLBACK_COMMANDS = [
        (
            r"\myuline",
            r"\providecommand{\myuline}[1]{\textbf{#1}}",
        ),
        (
            r"\cventry",
            r"\providecommand{\cventry}[6]{\textbf{#2} -- #3 \hfill #1\\{\small #4 #5}\\\ifx&#6&\else#6\fi\par\medskip}",
        ),
        (
            r"\cvitem",
            r"\providecommand{\cvitem}[2]{\textbf{#1}: #2\par}",
        ),
        (
            r"\resumeItemListStart",
            r"\providecommand{\resumeItemListStart}{\begin{itemize}}",
        ),
        (
            r"\resumeItemListEnd",
            r"\providecommand{\resumeItemListEnd}{\end{itemize}}",
        ),
        (
            r"\resumeSubHeadingListStart",
            r"\providecommand{\resumeSubHeadingListStart}{\begin{itemize}}",
        ),
        (
            r"\resumeSubHeadingListEnd",
            r"\providecommand{\resumeSubHeadingListEnd}{\end{itemize}}",
        ),
        (
            r"\resumeSubheading",
            r"\providecommand{\resumeSubheading}[4]{\item \textbf{#1} \hfill #2\\\textit{#3} \hfill \textit{#4}\vspace{-2pt}}",
        ),
        (
            r"\resumeProjectHeading",
            r"\providecommand{\resumeProjectHeading}[2]{\item \textbf{#1} \hfill #2\vspace{-2pt}}",
        ),
        (
            r"\resumeItem",
            r"\providecommand{\resumeItem}[1]{\item #1}",
        ),
        (
            r"\degree",
            r"\providecommand{\degree}[1]{\textbf{#1}}",
        ),
        (
            r"\school",
            r"\providecommand{\school}[1]{\textit{#1}}",
        ),
        (
            r"\institution",
            r"\providecommand{\institution}[1]{\textit{#1}}",
        ),
        (
            r"\location",
            r"\providecommand{\location}[1]{#1}",
        ),
        (
            r"\dates",
            r"\providecommand{\dates}[1]{\hfill #1}",
        ),
        (
            r"\gpa",
            r"\providecommand{\gpa}[1]{GPA: #1}",
        ),
    ]

    injected_defs = []
    for macro_token, stub_def in _FALLBACK_COMMANDS:
        has_macro = macro_token in src
        has_def = (
            f"\\newcommand{{{macro_token}}}" in src
            or f"\\renewcommand{{{macro_token}}}" in src
            or f"\\providecommand{{{macro_token}}}" in src
            or f"\\newcommand{macro_token}" in src
            or f"\\renewcommand{macro_token}" in src
            or f"\\providecommand{macro_token}" in src
        )
        if has_macro and not has_def:
            injected_defs.append(stub_def)
            changes.append(f"injected fallback definition for {macro_token}")

    if injected_defs:
        stubs_block = "\n".join(injected_defs) + "\n"
        if r"\begin{document}" in src:
            src = src.replace(r"\begin{document}", stubs_block + r"\begin{document}", 1)
        else:
            src = stubs_block + src

    # Normalize non-ASCII Unicode characters that crash 8-bit TeX fonts
    unicode_map = {
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "--",  # en dash
        "\u2014": "---",  # em dash
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote
        "\u201a": "'",  # single low quote
        "\u201b": "'",  # single high-reversed quote
        "\u201c": "``",  # left double quote
        "\u201d": "''",  # right double quote
        "\u201e": ",,",  # double low quote
        "\u00a0": "~",  # non-breaking space
        "\u202f": "~",  # narrow no-break space
        "\u2022": "\\textbullet{}",  # bullet
        "\u2026": "\\dots{}",  # ellipsis
    }
    for uc, rep in unicode_map.items():
        if uc in src:
            src = src.replace(uc, rep)
            changes.append(f"normalized unicode {hex(ord(uc))} -> {rep}")

    # Auto-escape bare currency dollar signs without mangling math mode
    try:
        from core.latex_sanitizer import safe_escape_latex_text
    except ImportError:
        from .latex_sanitizer import safe_escape_latex_text  # type: ignore

    src2 = safe_escape_latex_text(src)
    if src2 != src:
        src = src2
        changes.append("escaped raw currency/special characters")

    # Clean up lonely line-break \\ that trigger "There's no line here to end"
    src2, n_lb = re.subn(r"(?m)^\s*\\\\(?:\s*\[[^\]]*\])?\s*$", "", src)
    src2, n_lb2 = re.subn(r"(?m)^\s*\\\\\s*", "", src2)
    src2, n_lb3 = re.subn(r"(\\\\[ \t]*){2,}", r"\\\\", src2)
    if n_lb or n_lb2 or n_lb3:
        src = src2
        changes.append("cleaned up invalid leading/consecutive \\\\ breaks")

    if changes:
        log.info("soften.step: changes=%s", changes)
    else:
        log.debug("soften.step: no changes chars=%s", len(src))

    return src, changes
