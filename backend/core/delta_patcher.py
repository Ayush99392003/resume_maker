"""Delta patcher — applies line-range patches from the fixer agent.

The fixer agent returns a compact JSON delta specifying only the lines that
changed.  This module applies that delta surgically to the original LaTeX
without touching any other content.

Delta format accepted
---------------------
The agent returns a dict with key ``fixed_lines``:

    {
        "fixed_zone_id": "EXPERIENCE",
        "fixed_lines": {
            "163": "\\\\begin{itemize}",
            "164-166": "\\\\item Built X\\n\\\\item Improved Y by 40%",
            "167": "\\\\end{itemize}"
        },
        "summary_of_changes": "Wrapped lonely \\\\item in itemize env"
    }

Keys in ``fixed_lines`` are either a single line number (``"164"``) or an
inclusive range (``"163-166"``).  The value is the replacement content for
that range.

Public API
----------
apply_line_delta(lines, delta)     -> list[str]
patch_latex(latex, delta)          -> str
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

try:
    from core.logging_setup import get_logger
    from core.zones import zone_engine
except ImportError:
    from ..logging_setup import get_logger  # type: ignore
    from ..zones import zone_engine  # type: ignore

log = get_logger("delta_patcher")

_RANGE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def _parse_key(key: str) -> Tuple[int, int]:
    """Parse a delta key like ``'164'`` or ``'163-166'`` into (start, end).

    Args:
        key: String key from the fixed_lines delta dict.

    Returns:
        ``(start_lineno, end_lineno)`` (1-indexed, inclusive).

    Raises:
        ValueError: If the key does not match the expected format.
    """
    m = _RANGE_RE.match(key.strip())
    if not m:
        raise ValueError(f"Invalid delta key format: {key!r}")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    return start, end


def apply_line_delta(
    lines: List[str], delta: Dict[str, str]
) -> List[str]:
    """Apply a fixer-agent line delta to a list of LaTeX source lines.

    Ranges are applied from bottom to top so that earlier replacements do not
    shift indices used by later ones.

    Args:
        lines: Original LaTeX lines (0-indexed list, but delta keys are
               1-indexed as per the line_indexer convention).
        delta: Mapping of ``"lineno"`` or ``"start-end"`` to replacement text.

    Returns:
        New list of lines with all delta patches applied.
    """
    # Parse all ranges first and sort descending so splicing is safe
    parsed: List[Tuple[int, int, str]] = []
    for key, replacement in delta.items():
        try:
            start, end = _parse_key(key)
        except ValueError:
            log.warning("delta_patcher: skipping invalid key %r", key)
            continue
        parsed.append((start, end, replacement))
    parsed.sort(key=lambda t: t[0], reverse=True)

    result = list(lines)
    total = len(result)
    applied = 0

    for start, end, replacement in parsed:
        # Convert to 0-indexed
        s0 = start - 1
        e0 = end  # slice end is exclusive, so end (1-indexed) == e0 (exclusive)
        if s0 < 0 or e0 > total or s0 >= total:
            log.warning(
                "delta_patcher: range %s-%s out of bounds (total=%s), skip",
                start, end, total,
            )
            continue
        replacement_lines = replacement.splitlines()
        result[s0:e0] = replacement_lines
        log.debug(
            "delta_patcher: patched lines %s-%s (%s replacement lines)",
            start, end, len(replacement_lines),
        )
        applied += 1

    log.info(
        "delta_patcher.apply_line_delta: applied %s/%s patch(es)",
        applied, len(parsed),
    )
    return result


def patch_latex(latex: str, delta: Dict[str, str]) -> str:
    """Apply a line delta to a full LaTeX source string.

    This is a convenience wrapper around :func:`apply_line_delta` that splits,
    patches, and re-joins the source.

    Args:
        latex: Full LaTeX source string.
        delta: Line delta dict as returned by the fixer agent.

    Returns:
        Patched LaTeX source string.
    """
    if not delta:
        return latex
    lines = latex.splitlines()
    patched_lines = apply_line_delta(lines, delta)
    result = "\n".join(patched_lines)
    if latex.endswith("\n"):
        result += "\n"
    return result


def apply_zone_delta(
    latex: str, zone_id: str, fixed_inner: str
) -> str:
    """Replace an entire zone's inner content with *fixed_inner*.

    This is a shortcut for whole-zone repairs (e.g. when the fixer agent
    returns a corrected zone fragment rather than individual line patches).

    Args:
        latex: Full LaTeX source string.
        zone_id: Zone identifier string (e.g. ``"EXPERIENCE"`` or ``"2"``).
        fixed_inner: Replacement inner content for the zone (without markers).

    Returns:
        Patched LaTeX string.
    """
    try:
        result = zone_engine.replace_zone(latex, zone_id, fixed_inner)
        log.info(
            "delta_patcher.apply_zone_delta: replaced zone %s (%s chars)",
            zone_id, len(fixed_inner),
        )
        return result
    except Exception as exc:
        log.warning(
            "delta_patcher.apply_zone_delta: zone_engine failed "
            "zone=%s - %s; falling back to patch_latex",
            zone_id, exc,
        )
        return latex
