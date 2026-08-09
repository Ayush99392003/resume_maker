"""Convert already-built LaTeX into numbered ZoneDocument JSON."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .logging_setup import get_logger
from .zone_document import ZoneDocument, ZoneRecord

log = get_logger("latex_to_zones")

KIND_HINTS = {
    "HEADER": "predefined_header",
    "SUMMARY": "predefined_summary",
    "EXPERIENCE": "predefined_experience",
    "EDUCATION": "predefined_education",
    "SKILLS": "predefined_skills",
    "PROJECTS": "predefined_projects",
    "CERTIFICATIONS": "predefined_certifications",
    "PUBLICATIONS": "predefined_publications",
    "AWARDS": "predefined_awards",
    "EXTRACURRICULAR": "predefined_extracurricular",
    "LANGUAGES": "predefined_languages",
    "INTERESTS": "predefined_interests",
    "LINKS": "predefined_links",
}

DESC_FROM_NAME = {
    "HEADER": "Name, contact, links",
    "SUMMARY": "Professional summary",
    "EXPERIENCE": "Work experience",
    "EDUCATION": "Education",
    "SKILLS": "Skills",
    "PROJECTS": "Projects",
    "CERTIFICATIONS": "Certifications",
    "PUBLICATIONS": "Publications",
    "AWARDS": "Awards",
    "EXTRACURRICULAR": "Extracurricular activities",
    "LANGUAGES": "Languages",
    "INTERESTS": "Interests",
    "LINKS": "Links",
}

_ZONE_START = re.compile(
    r"^%\s*ZONE:(?P<name>[A-Za-z0-9_]+):START\s*$", re.MULTILINE
)
_BEGIN_DOC = re.compile(r"\\begin\{document\}", re.IGNORECASE)
_END_DOC = re.compile(r"\\end\{document\}", re.IGNORECASE)
_SECTION = re.compile(
    r"^\\(?:section|section\*|subsection|subsection\*|cvsection|section\*?)"
    r"\*?\s*(\{.*)$",
    re.MULTILINE,
)


def _split_shell(latex: str) -> Tuple[str, str, str]:
    begin = _BEGIN_DOC.search(latex)
    end = _END_DOC.search(latex)
    if not begin:
        return "", latex, ""
    header = latex[: begin.end()]
    if end:
        body = latex[begin.end() : end.start()]
        footer = latex[end.start() :]
    else:
        body = latex[begin.end() :]
        footer = "\\end{document}\n"
    return header, body, footer


def _description_for(name: str, body: str) -> str:
    key = name.upper()
    if key in DESC_FROM_NAME:
        return DESC_FROM_NAME[key]
    if key.isdigit():
        # Prefer section title inside body
        m = re.search(
            r"\\(?:section|section\*|cvsection)\*?\{([^}]+)\}", body
        )
        if m:
            title = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", m.group(1))
            title = re.sub(r"\\[a-zA-Z]+", "", title).strip()
            if title:
                return title
        return f"Zone {key}"
    return name.replace("_", " ").title()


def _kind_for(name: str) -> str:
    return KIND_HINTS.get(name.upper(), "custom")


def _segments_from_markers(body: str) -> List[Tuple[str, str, str]]:
    """Return list of (name, leading_prefix, inner_body)."""
    starts = list(_ZONE_START.finditer(body))
    if not starts:
        return []

    segments: List[Tuple[str, str, str]] = []
    for i, start_m in enumerate(starts):
        name = start_m.group("name")
        end_pat = re.compile(
            rf"^%\s*ZONE:{re.escape(name)}:END\s*$", re.MULTILINE
        )
        end_m = end_pat.search(body, start_m.end())
        if not end_m:
            continue
        prefix_start = starts[i - 1].end() if i else 0
        # Include material between previous end and this start (e.g. \section)
        # Actually prefix should be between previous END and this START
        if i == 0:
            leading = body[: start_m.start()]
        else:
            prev_name = starts[i - 1].group("name")
            prev_end = re.compile(
                rf"^%\s*ZONE:{re.escape(prev_name)}:END\s*$", re.MULTILINE
            )
            prev_end_m = prev_end.search(body, starts[i - 1].end())
            lead_from = prev_end_m.end() if prev_end_m else starts[i - 1].end()
            leading = body[lead_from : start_m.start()]
        inner = body[start_m.end() : end_m.start()]
        if inner.startswith("\n"):
            inner = inner[1:]
        if inner.endswith("\n"):
            inner = inner[:-1]
        segments.append((name, leading, inner))
    return segments


def _segments_from_sections(body: str) -> List[Tuple[str, str, str]]:
    matches = list(
        re.finditer(
            r"^(\\(?:section|subsection|cvsection)\*?\{[^\n]+)",
            body,
            re.MULTILINE,
        )
    )
    if not matches:
        text = body.strip()
        if not text:
            return []
        return [("1", "", text)]

    # Content before first section → zone 1 (often header/contact)
    segments: List[Tuple[str, str, str]] = []
    pre = body[: matches[0].start()].strip()
    if pre:
        segments.append(("HEADER", "", pre))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        block = body[start:end].strip()
        title_m = re.search(r"\{([^}]+)\}", m.group(1))
        raw_title = title_m.group(1) if title_m else f"Section{i+1}"
        clean = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", raw_title)
        clean = re.sub(r"\\[a-zA-Z]+", "", clean)
        clean = re.sub(r"[^A-Za-z0-9]+", "_", clean).strip("_").upper() or f"SECTION_{i+1}"
        segments.append((clean[:40], "", block))
    return segments


def latex_to_zones(
    latex: str,
    *,
    source_url: Optional[str] = None,
) -> ZoneDocument:
    """Split built LaTeX into fixed header/footer + numbered zones."""
    log.info(
        "zones.step: latex_to_zones start chars=%s source_url=%s",
        len(latex or ""),
        bool(source_url),
    )
    header, body, footer = _split_shell(latex)
    if not header and not body:
        log.warning("zones.step: no document shell — wrapping as article")
        header = "\\documentclass{article}\n\\begin{document}\n"
        body = latex
        footer = "\\end{document}\n"

    marked = _segments_from_markers(body)
    if marked:
        segments = marked
        mode = "markers"
    else:
        segments = _segments_from_sections(body)
        mode = "sections"

    if not segments:
        log.warning("zones.step: no segments — single fallback zone")
        segments = [("1", "", body.strip() or "% empty body")]
        mode = "fallback"

    zones: List[ZoneRecord] = []
    order: List[int] = []
    for idx, (name, leading, inner) in enumerate(segments, start=1):
        combined = (leading.strip("\n") + "\n" + inner.strip("\n")).strip(
            "\n"
        )
        if not combined:
            combined = "% empty zone"
        desc = _description_for(name, combined)
        kind = _kind_for(name)
        latex_block = (
            f"% ZONE:{idx}:START\n{combined}\n% ZONE:{idx}:END\n"
        )
        zones.append(
            ZoneRecord(
                zone_no=idx,
                description=desc,
                latex=latex_block,
                kind=kind,
            )
        )
        order.append(idx)

    # Drop trailing whitespace-only material after last zone from being lost:
    # already handled by segmenting full body for section path; for markers,
    # trailing after last END is ignored (usually blank).

    log.info(
        "zones.step: done mode=%s zones=%s descs=%s",
        mode,
        order,
        [z.description for z in zones],
    )
    return ZoneDocument(
        header=header if header.endswith("\n") else header + "\n",
        footer=footer if footer.endswith("\n") else footer + "\n",
        zones=zones,
        zone_order=order,
        next_zone_no=len(zones) + 1,
        source_url=source_url,
    )
