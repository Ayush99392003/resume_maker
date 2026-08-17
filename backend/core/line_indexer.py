"""Line-index utilities for LaTeX zone debug and repair payloads.

This module converts LaTeX source into line-numbered JSON payloads so the
AI repair agent works with a minimal, pin-pointed context instead of the
full document text.

Public API
----------
build_line_index(latex)          -> dict[int, str]
zone_line_range(latex, zone_id)  -> tuple[int, int] | None
build_debug_payload(latex, error_log, zone_id=None) -> dict
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

try:
    from core.logging_setup import get_logger
except ImportError:
    from ..logging_setup import get_logger  # type: ignore

log = get_logger("line_indexer")

# Patterns for zone markers (numeric or named)
_ZONE_START = re.compile(
    r"^%\s*ZONE:(?P<id>[A-Za-z0-9_]+):START\s*$", re.MULTILINE
)
_ZONE_END = re.compile(
    r"^%\s*ZONE:(?P<id>[A-Za-z0-9_]+):END\s*$", re.MULTILINE
)

# Parse a tectonic/pdflatex error line reference
_REAL_ERROR_LINE_RE = re.compile(
    r"(?:error|fatal error|!)\s*.*\.tex:(\d+):", re.IGNORECASE
)
_ERR_LINE_RE = re.compile(r"\.tex:(\d+):")


def build_line_index(latex: str) -> Dict[int, str]:
    """Return a 1-indexed mapping of line numbers to LaTeX lines.

    Args:
        latex: Full LaTeX source string.

    Returns:
        Mapping ``{1: "first line", 2: "second line", ...}``.
    """
    lines = latex.splitlines()
    return {i + 1: line for i, line in enumerate(lines)}


def zone_line_range(
    latex: str, zone_id: str
) -> Optional[Tuple[int, int]]:
    """Find the 1-indexed start/end line numbers of a zone block.

    Searches for ``% ZONE:<zone_id>:START`` and ``% ZONE:<zone_id>:END``
    markers.  The returned range includes both marker lines.

    Args:
        latex: Full LaTeX source string.
        zone_id: Zone identifier (numeric string or name like ``EXPERIENCE``).

    Returns:
        ``(start_line, end_line)`` if found, else ``None``.
    """
    lines = latex.splitlines()
    start_pat = re.compile(
        rf"^%\s*ZONE:{re.escape(zone_id)}:START\s*$"
    )
    end_pat = re.compile(
        rf"^%\s*ZONE:{re.escape(zone_id)}:END\s*$"
    )
    start_ln: Optional[int] = None
    for i, line in enumerate(lines, start=1):
        if start_ln is None and start_pat.match(line):
            start_ln = i
        elif start_ln is not None and end_pat.match(line):
            return (start_ln, i)
    return None


def _error_line_numbers(error_log: str) -> List[int]:
    """Extract all referenced line numbers from a Tectonic error log."""
    return [int(m.group(1)) for m in _ERR_LINE_RE.finditer(error_log)]


def _zone_containing_line(
    latex: str, lineno: int
) -> Optional[str]:
    """Return the zone_id whose block contains *lineno*, or None."""
    for m in _ZONE_START.finditer(latex):
        zone_id = m.group("id")
        rng = zone_line_range(latex, zone_id)
        if rng and rng[0] <= lineno <= rng[1]:
            return zone_id
    return None


def _context_window(
    line_index: Dict[int, str],
    line_numbers: List[int],
    padding: int = 6,
) -> Dict[int, str]:
    """Return line dict sliced to [min_err - padding, max_err + padding]."""
    if not line_numbers or not line_index:
        return {}
    all_lines = sorted(line_index.keys())
    min_avail = all_lines[0]
    max_avail = all_lines[-1]
    start = max(min_avail, min(line_numbers) - padding)
    end = min(max_avail, max(line_numbers) + padding)
    return {ln: line_index[ln] for ln in range(start, end + 1) if ln in line_index}


def build_debug_payload(
    latex: str,
    error_log: str,
    zone_id: Optional[str] = None,
    context_padding: int = 6,
) -> dict:
    """Produce a JSON-serialisable debug payload for the fixer agent.

    The payload contains:
    - ``error_log``: the raw Tectonic log (last 800 chars)
    - ``target_zone``: inferred or explicitly supplied zone id
    - ``line_range``: ``[start, end]`` of the target zone (or context window)
    - ``lines``: ``{"164": "\\\\item Bullet text"}`` — the minimal context

    Args:
        latex: Full LaTeX source.
        error_log: Raw Tectonic compilation error log.
        zone_id: Override zone to focus on; auto-inferred from error if None.
        context_padding: Extra lines above/below error line numbers.

    Returns:
        Dict payload ready to be serialised and sent to the fixer agent.
    """
    line_index = build_line_index(latex)
    err_lines = _error_line_numbers(error_log)

    # Infer zone if not supplied: check error lines from last to first
    # because fatal errors that halted TeX appear at the bottom of the log.
    if zone_id is None and err_lines:
        for ln in reversed(err_lines):
            found = _zone_containing_line(latex, ln)
            if found:
                zone_id = found
                break

    # Get zone range
    zone_rng: Optional[Tuple[int, int]] = None
    if zone_id:
        zone_rng = zone_line_range(latex, zone_id)

    # Build the minimal context window
    if zone_rng:
        start_ln, end_ln = zone_rng
        zone_lines = {
            ln: content
            for ln, content in line_index.items()
            if start_ln <= ln <= end_ln
        }
        context_lines = zone_lines
    elif err_lines:
        context_lines = _context_window(line_index, err_lines, context_padding)
        start_ln = min(context_lines) if context_lines else 0
        end_ln = max(context_lines) if context_lines else 0
    else:
        context_lines = line_index
        start_ln = 1
        end_ln = len(line_index)

    line_range = [start_ln, end_ln]

    log.info(
        "line_indexer.build_debug_payload: zone=%s err_lines=%s "
        "context_lines=%s",
        zone_id,
        err_lines,
        len(context_lines),
    )

    return {
        "error_log": (error_log or "")[-800:],
        "target_zone": zone_id,
        "line_range": line_range,
        "lines": {str(ln): content for ln, content in context_lines.items()},
    }
