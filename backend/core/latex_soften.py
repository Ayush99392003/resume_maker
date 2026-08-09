"""Make pasted Overleaf-style LaTeX safer for Windows Tectonic."""

from __future__ import annotations

import re
from typing import List, Tuple

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
    "fontspec",
    "unicode-math",
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


def _replace_newcommand_body(src: str, macroname: str, new_def: str) -> Tuple[str, bool]:
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


def soften_latex_for_tectonic(latex: str) -> Tuple[str, List[str]]:
    """
    Disable packages that commonly crash this Tectonic Windows build
    and replace FA icons with text.

    Returns (softened_latex, list of human-readable change notes).
    """
    src = latex or ""
    changes: List[str] = []
    if not src.strip():
        return src, changes

    disabled: List[str] = []

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

    # fontspec / unicode-math leftover commands (noop-ish stubs)
    for cmd, note in [
        (r"\\setmainfont(?:\[[^\]]*\])?\{[^}]*\}", "removed \\setmainfont"),
        (r"\\setsansfont(?:\[[^\]]*\])?\{[^}]*\}", "removed \\setsansfont"),
        (r"\\setmonofont(?:\[[^\]]*\])?\{[^}]*\}", "removed \\setmonofont"),
    ]:
        src2, n = re.subn(cmd, "% fontspec cmd removed", src)
        if n:
            src = src2
            changes.append(note)

    for a, b in _ICON_REPLACEMENTS:
        if a in src:
            src = src.replace(a, b)
            changes.append(f"replaced {a} -> {b}")

    # Remaining Font Awesome icons: \faPhone, \faGithub, \faMapMarker* …
    # Require a capital letter after "fa" so we never touch \fancyhf / \familydefault.
    leftover_fa = sorted(set(re.findall(r"\\fa[A-Z][A-Za-z]*\*?", src)))
    if leftover_fa:
        src = re.sub(r"\\fa[A-Z][A-Za-z]*\*?", "", src)
        changes.append(f"stripped leftover FA macros: {', '.join(leftover_fa)}")

    has_myuline = r"\myuline" in src
    has_def = (
        r"\newcommand{\myuline}" in src
        or r"\renewcommand{\myuline}" in src
        or r"\providecommand{\myuline}" in src
    )
    if has_myuline and not has_def:
        if r"\begin{document}" in src:
            src = src.replace(
                r"\begin{document}",
                r"\providecommand{\myuline}[1]{\textbf{#1}}"
                r"\begin{document}",
                1,
            )
            changes.append("injected \\providecommand{\\myuline}")
        else:
            src = r"\providecommand{\myuline}[1]{\textbf{#1}}" + "\n" + src
            changes.append("injected \\providecommand{\\myuline}")

    if changes:
        log.info("soften.step: changes=%s", changes)
    else:
        log.debug("soften.step: no changes chars=%s", len(src))

    return src, changes
