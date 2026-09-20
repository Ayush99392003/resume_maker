"""LaTeX sanitizer for robust JSON extraction and LaTeX escaping.

Provides safe JSON parsing of LLM outputs containing raw LaTeX control
sequences and context-aware escaping of special LaTeX characters.
"""

from __future__ import annotations

import json
import re
from typing import Any

try:
    from core.logging_setup import get_logger
except ImportError:
    from .logging_setup import get_logger

log = get_logger("latex_sanitizer")

_JSON_ESCAPES = frozenset('"\\/ bfnrtu')
_HEX = frozenset("0123456789abcdefABCDEF")

_MATH_ENVS = frozenset(
    [
        "align",
        "align*",
        "aligned",
        "equation",
        "equation*",
        "gather",
        "gather*",
        "multline",
        "multline*",
        "split",
        "matrix",
        "pmatrix",
        "bmatrix",
        "vmatrix",
        "Vmatrix",
        "cases",
        "array",
        "dcases",
        "rcases",
    ]
)

_TABULAR_ENVS = frozenset(
    [
        "tabular",
        "tabular*",
        "tabularx",
        "tabulary",
        "longtable",
    ]
)

# Commands whose arguments must be protected from character escaping
_PROTECTED_FIRST_ARG_CMDS = frozenset(
    [
        "cite",
        "citep",
        "citet",
        "nocite",
        "bibitem",
        "label",
        "ref",
        "pageref",
        "eqref",
        "autoref",
        "cref",
        "Cref",
        "definecolor",
        "providecolor",
        "colorlet",
        "color",
        "textcolor",
        "pagecolor",
        "href",
        "url",
        "includegraphics",
        "input",
        "include",
        "bibliography",
        "bibliographystyle",
        "usepackage",
        "RequirePackage",
        "lstinputlisting",
    ]
)

_COLOR_KEY_PATTERN = re.compile(
    r"(?i)\b(?:color|colback|colframe|linkcolor|citecolor|urlcolor|"
    r"filecolor|anchorcolor)\s*=\s*[a-zA-Z0-9_]*$"
)

_HEX_COLOR_RE = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"
)


def _pre_escape_backslashes(raw: str) -> str:
    r"""Pre-process raw LLM text before JSON parse.

    Walk the string character-by-character, tracking whether we are inside
    a JSON string literal. When inside a string:
    - Protect LaTeX line breaks: convert ``\\`` to ``\\\\`` so json.loads
      preserves ``\\`` instead of collapsing to single ``\``.
    - Preserve ``\b``, ``\f``, ``\n``, ``\r``, ``\t`` when followed by
      alpha characters (e.g. ``\begin``, ``\frac``, ``\resumeItem``) by
      doubling the backslash.
    - Double any backslash followed by non-JSON escape characters (e.g.
      ``\c``, ``\s``, ``\d``, ``\p``).
    """
    result: list[str] = []
    i = 0
    n = len(raw)
    in_string = False

    while i < n:
        ch = raw[i]
        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        # Inside a JSON string literal
        if ch == '"':
            # Check if this quote was escaped by an odd number of backslashes
            bs_count = 0
            j = i - 1
            while j >= 0 and raw[j] == "\\":
                bs_count += 1
                j -= 1
            if bs_count % 2 == 0:
                in_string = False
            result.append(ch)
            i += 1
            continue

        if ch == "\\" and i + 1 < n:
            nxt = raw[i + 1]

            # Case 1: Double backslash "\\" -> LaTeX line break
            # We emit "\\\\" so json.loads decodes it to "\\"
            if nxt == "\\":
                result.append("\\\\\\\\")
                i += 2
                continue

            # Case 2: Standard escapes: b, f, n, r, t
            if nxt in "bfnrt":
                after = raw[i + 2] if i + 2 < n else ""
                if after.isalpha():
                    # LaTeX command (e.g. \begin, \frac, \resumeItem, \textbf)
                    result.append("\\\\")
                    result.append(nxt)
                    i += 2
                    continue
                # Genuine JSON whitespace escape (\n, \t, etc.)
                result.append(ch)
                result.append(nxt)
                i += 2
                continue

            # Case 3: Unicode escape \uXXXX
            if nxt == "u":
                hex4 = raw[i + 2 : i + 6]
                if len(hex4) == 4 and all(c in _HEX for c in hex4):
                    # Genuine JSON unicode escape
                    result.append(ch)
                    result.append(nxt)
                    i += 2
                    continue
                # LaTeX command like \underline or \usepackage
                result.append("\\\\")
                result.append(nxt)
                i += 2
                continue

            # Case 4: Valid JSON escapes \" and \/
            if nxt in '"/':
                result.append(ch)
                result.append(nxt)
                i += 2
                continue

            # Case 5: Any other character (e.g. \c, \s, \d, \p, etc.)
            # Double the backslash to make it a valid JSON escape
            result.append("\\\\")
            result.append(nxt)
            i += 2
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def _clean_backslash_typos(text: str) -> str:
    """Restore backslashes on commands merged with newlines (e.g. \\nitem)."""
    pattern = (
        r"\\n(item|begin|end|cventry|cvitem|section|"
        r"subsection|textbf|textit|href)\b"
    )
    return re.sub(pattern, r"\n\\\1", text)


def _is_math_pair(text: str, start_idx: int) -> int:
    """Return closing $ index if text[start_idx] starts math pair, else -1.
    """
    if start_idx + 1 >= len(text):
        return -1
    next_ch = text[start_idx + 1]
    if next_ch.isdigit() or next_ch in " \t\r\n.,;:)":
        return -1
    eol = text.find("\n", start_idx)
    limit = eol if eol != -1 else len(text)
    close_idx = text.find("$", start_idx + 1, limit)
    if close_idx == -1:
        return -1
    if close_idx > 0 and text[close_idx - 1] == "\\":
        return -1
    inner = text[start_idx + 1 : close_idx].strip()
    # If inner looks like currency ($100k or $50 to $100), not math
    if any(c.isdigit() for c in inner) and not any(
        op in inner for op in "+-*/=^_\\{}<>"
    ):
        return -1
    return close_idx


def safe_escape_latex_text(text: str) -> str:
    """Context-aware escaper for LaTeX special characters.

    Protects:
    - '#' in hex colors (#2563EB), URLs (\\href), and macro params (#1)
    - '_' in color names (dark_blue), labels, citations, and math mode
    - '&' in all math environments (align, equation, matrix, cases)
      and tabular environments

    Escapes bare '%', '_', '#', '&', '$', '^', '~' in standard text mode.
    """
    if not text:
        return ""

    result: list[str] = []
    i = 0
    n = len(text)
    math_end_idx = -1
    prev_backslash = False
    active_envs: list[str] = []

    while i < n:
        # Check display math \[ ... \] or \( ... \)
        if text[i : i + 2] in (r"\[", r"\("):
            close_delimiter = r"\]" if text[i : i + 2] == r"\[" else r"\)"
            close_pos = text.find(close_delimiter, i + 2)
            if close_pos != -1:
                result.append(text[i : close_pos + 2])
                i = close_pos + 2
                prev_backslash = False
                continue

        # Check $$ ... $$ display math
        if text[i : i + 2] == "$$":
            close_pos = text.find("$$", i + 2)
            if close_pos != -1:
                result.append(text[i : close_pos + 2])
                i = close_pos + 2
                prev_backslash = False
                continue

        # Check \begin{env} or \end{env}
        if text[i : i + 7] == r"\begin{":
            end_brace = text.find("}", i + 7)
            if end_brace != -1:
                env_name = text[i + 7 : end_brace].strip()
                active_envs.append(env_name)
                result.append(text[i : end_brace + 1])
                i = end_brace + 1
                prev_backslash = False
                continue
        elif text[i : i + 5] == r"\end{":
            end_brace = text.find("}", i + 5)
            if end_brace != -1:
                env_name = text[i + 5 : end_brace].strip()
                if active_envs and active_envs[-1] == env_name:
                    active_envs.pop()
                elif env_name in active_envs:
                    active_envs.remove(env_name)
                result.append(text[i : end_brace + 1])
                i = end_brace + 1
                prev_backslash = False
                continue

        # Check protected command arguments e.g. \cite{key}, \href{url}{text}
        is_protected_cmd = False
        for cmd in _PROTECTED_FIRST_ARG_CMDS:
            needle = f"\\{cmd}"
            if text[i:].startswith(needle):
                after_cmd = i + len(needle)
                # Verify word boundary or optional argument bracket
                if after_cmd < n and text[after_cmd] in "{[* \t":
                    # Handle optional argument [options] if any
                    k = after_cmd
                    while k < n and text[k] in " \t":
                        k += 1
                    if k < n and text[k] == "[":
                        opt_close = text.find("]", k)
                        if opt_close != -1:
                            k = opt_close + 1
                    while k < n and text[k] in " \t":
                        k += 1
                    if k < n and text[k] == "{":
                        depth = 0
                        arg_end = -1
                        for idx in range(k, n):
                            if text[idx] == "{" and (
                                idx == 0 or text[idx - 1] != "\\"
                            ):
                                depth += 1
                            elif text[idx] == "}" and (
                                idx == 0 or text[idx - 1] != "\\"
                            ):
                                depth -= 1
                                if depth == 0:
                                    arg_end = idx
                                    break
                        if arg_end != -1:
                            max_args = 1
                            if cmd == "colorlet":
                                max_args = 2
                            elif cmd in ("definecolor", "providecolor"):
                                max_args = 3
                            curr_end = arg_end
                            for _ in range(1, max_args):
                                next_k = curr_end + 1
                                while next_k < n and text[next_k] in " \t":
                                    next_k += 1
                                if next_k < n and text[next_k] == "{":
                                    d = 0
                                    next_end = -1
                                    for idx in range(next_k, n):
                                        if text[idx] == "{" and (
                                            idx == 0 or text[idx - 1] != "\\"
                                        ):
                                            d += 1
                                        elif text[idx] == "}" and (
                                            idx == 0 or text[idx - 1] != "\\"
                                        ):
                                            d -= 1
                                            if d == 0:
                                                next_end = idx
                                                break
                                    if next_end != -1:
                                        curr_end = next_end
                                    else:
                                        break
                                else:
                                    break
                            result.append(text[i : curr_end + 1])
                            i = curr_end + 1
                            is_protected_cmd = True
                            prev_backslash = False
                            break
        if is_protected_cmd:
            continue

        ch = text[i]

        if prev_backslash:
            result.append(ch)
            prev_backslash = ch.isalpha()
            i += 1
            continue

        if ch == "\\":
            result.append(ch)
            prev_backslash = True
            i += 1
            continue

        # Check inline math mode ($...$)
        if i <= math_end_idx:
            result.append(ch)
            if i == math_end_idx:
                math_end_idx = -1
            i += 1
            continue

        if ch == "$":
            closing = _is_math_pair(text, i)
            if closing != -1:
                math_end_idx = closing
                result.append(ch)
                i += 1
                continue
            # Currency dollar sign
            result.append(r"\$")
            i += 1
            continue

        # Check if currently inside any math environment
        in_math_env = any(e in _MATH_ENVS for e in active_envs)
        in_tabular_env = any(e in _TABULAR_ENVS for e in active_envs)

        # LaTeX comment: % to end of line ONLY if % is at start of line
        if ch == "%":
            line_start = max(0, text.rfind("\n", 0, i))
            prefix_line = (
                text[line_start + 1 : i] if "\n" in text[:i] else text[:i]
            )
            if not prefix_line.strip():
                eol = text.find("\n", i)
                if eol == -1:
                    result.append(text[i:])
                    break
                result.append(text[i : eol + 1])
                i = eol + 1
                continue
            # Inline percent in text (e.g. 50%, 100%, sales % increase)
            result.append(r"\%")
            i += 1
            continue

        # Ampersand: preserve in math envs and tabular envs
        if ch == "&":
            if in_math_env or in_tabular_env:
                result.append(ch)
            else:
                result.append(r"\&")
            i += 1
            continue

        # Underscore & Caret: preserve in math mode or color assignments
        if ch in ("_", "^"):
            if in_math_env or (math_end_idx != -1 and i <= math_end_idx):
                result.append(ch)
            else:
                line_start = max(0, text.rfind("\n", 0, i))
                pre_text = text[line_start:i]
                if ch == "_" and _COLOR_KEY_PATTERN.search(pre_text):
                    result.append(ch)
                else:
                    result.append(r"\_" if ch == "_" else r"\^{}")
            i += 1
            continue

        # Hash / Number sign:
        if ch == "#":
            # 1. Macro parameter: #1 to #9
            if i + 1 < n and text[i + 1].isdigit():
                result.append(ch)
                i += 1
                continue
            # 2. Hex color: #2563EB or #FFF
            hex_match = _HEX_COLOR_RE.match(text[i:])
            if hex_match:
                matched_hex = hex_match.group(0)
                result.append(matched_hex)
                i += len(matched_hex)
                continue
            # Otherwise escape in text
            result.append(r"\#")
            i += 1
            continue

        # Tilde: preserve in URLs or math
        if ch == "~":
            if in_math_env or (math_end_idx != -1 and i <= math_end_idx):
                result.append(ch)
            else:
                result.append(r"\textasciitilde{}")
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def _post_sanitize(obj: Any) -> Any:
    """Post-sanitize object after json.loads to restore TeX macros."""
    if isinstance(obj, str):
        # Fix CR + letter -> \r + letter (restores \resumeItem etc.)
        obj = re.sub(r"\r([a-zA-Z])", r"\\r\1", obj)
        # De-duplicate \\cmd -> \cmd (over-escaped by some LLMs)
        obj = re.sub(r"\\{2,}([a-zA-Z])", r"\\\1", obj)
        # Collapse excessive backslashes (e.g. \\\\ -> \\)
        obj = re.sub(r"\\{3,}", r"\\\\", obj)
        obj = _clean_backslash_typos(obj)
        obj = safe_escape_latex_text(obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _post_sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_post_sanitize(x) for x in obj]
    return obj


def safe_extract_json(text: str) -> dict:
    """Parse JSON from model output, tolerating markdown fences and LaTeX.

    1. Strips markdown code fences.
    2. Performs context-aware pre-escaping of LaTeX control sequences.
    3. Protects LaTeX line breaks (\\\\ -> \\\\\\\\) so json.loads preserves.
    4. Preserves \\b, \\f, \\n, \\r, \\t when followed by alpha characters.
    5. Post-sanitizes parsed dict to repair any mangled control sequences.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    pre_escaped = _pre_escape_backslashes(text)

    try:
        parsed = json.loads(pre_escaped)
        if isinstance(parsed, dict):
            return _post_sanitize(parsed)
        return {"data": _post_sanitize(parsed)}
    except json.JSONDecodeError as err:
        log.debug(
            "safe_extract_json: json.loads failed (%s), searching for object",
            err,
        )
        match = re.search(r"\{.*\}", pre_escaped, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return _post_sanitize(parsed)
                return {"data": _post_sanitize(parsed)}
            except json.JSONDecodeError as err2:
                log.error("safe_extract_json: regex extract failed - %s", err2)
                raise
        log.error("safe_extract_json: no JSON object found in text - %s", err)
        raise

