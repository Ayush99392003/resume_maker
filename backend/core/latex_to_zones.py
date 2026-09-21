"""Convert already-built LaTeX into numbered ZoneDocument JSON."""

from __future__ import annotations

import re

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
    # Academic paper zones
    "TITLE_AUTHORS": "predefined_title_authors",
    "ABSTRACT": "predefined_abstract",
    "KEYWORDS": "predefined_keywords",
    "IEEEKEYWORDS": "predefined_keywords",
    "INTRODUCTION": "predefined_introduction",
    "RELATED_WORK": "predefined_related_work",
    "METHODOLOGY": "predefined_methodology",
    "EXPERIMENTS": "predefined_experiments",
    "DISCUSSION": "predefined_discussion",
    "CONCLUSION": "predefined_conclusion",
    "REFERENCES": "predefined_references",
    "BIBLIOGRAPHY": "predefined_references",
    "APPENDIX": "predefined_appendix",
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
    # Academic paper zones
    "TITLE_AUTHORS": "Title and authors",
    "ABSTRACT": "Abstract",
    "KEYWORDS": "Keywords / Index terms",
    "IEEEKEYWORDS": "Keywords / Index terms",
    "INTRODUCTION": "Introduction",
    "RELATED_WORK": "Related work",
    "METHODOLOGY": "Methodology",
    "EXPERIMENTS": "Experiments and results",
    "DISCUSSION": "Discussion",
    "CONCLUSION": "Conclusion",
    "REFERENCES": "References",
    "BIBLIOGRAPHY": "Bibliography",
    "APPENDIX": "Appendix",
}

_ZONE_START = re.compile(
    r"^%\s*ZONE:(?P<name>[A-Za-z0-9_]+):START\s*$", re.MULTILINE
)
_BEGIN_DOC = re.compile(r"\\begin\{document\}", re.IGNORECASE)
_END_DOC = re.compile(r"\\end\{document\}", re.IGNORECASE)

from typing import Any

_HEADING_PAT = re.compile(
    r"^[ \t]*("
    r"\\(?:section|subsection|subsubsection|paragraph|cvsection)\*?\{"
    r"|\\begin\{(?:abstract|IEEEkeywords|keywords|thebibliography|rSection)\}"
    r"|\\appendix\b"
    r"|\\bibliography\{"
    r"|\\title\{"
    r"|\\name\{"
    r")",
    re.MULTILINE,
)


def _extract_balanced_braces(
    text: str, start_pos: int = 0
) -> tuple[str, int] | None:
    """Extract content inside balanced {...} starting at or after start_pos.

    Returns (inner_content, end_pos) or None.
    """
    brace_idx = text.find("{", start_pos)
    if brace_idx == -1:
        return None
    depth = 0
    i = brace_idx
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[brace_idx + 1 : i], i + 1
        i += 1
    return None


def _clean_latex_title(raw_title: str) -> str:
    """Remove LaTeX formatting commands from section title string."""
    clean = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", raw_title)
    clean = re.sub(r"\\[a-zA-Z]+", "", clean)
    clean = clean.replace("&", "and").strip()
    return clean


def _split_shell(latex: str) -> tuple[str, str, str]:
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


def _description_for(
    name: str,
    body: str,
    existing_desc: str | None = None,
) -> str:
    key = name.upper()
    if key in DESC_FROM_NAME:
        return DESC_FROM_NAME[key]

    if existing_desc and not re.match(
        r"^Zone\s*\d+$", existing_desc.strip(), re.IGNORECASE
    ):
        return existing_desc.strip()

    if key.isdigit():
        # Title, authors, maketitle in academic papers
        if (
            r"\title" in body
            or r"\maketitle" in body
            or (r"\author" in body and r"\begin{document}" not in body)
        ):
            return "Title and authors"

        # Resume name / contact header
        if r"\name{" in body or (
            r"\address{" in body and r"\title" not in body
        ):
            return "Name, contact, links"

        # Headings: section, subsection, subsubsection, paragraph, cvsection, rSection
        m = re.search(
            r"(?:\\(?:section|subsection|subsubsection|paragraph|cvsection)\*?\{|\\begin\{rSection\}\{)",
            body,
        )
        if m:
            res = _extract_balanced_braces(body, m.start())
            if res:
                clean = _clean_latex_title(res[0])
                if clean:
                    if (
                        "index term" in clean.lower()
                        or "keyword" in clean.lower()
                    ):
                        return "Index Terms"
                    return clean

        # Academic environments
        if r"\begin{abstract}" in body:
            return "Abstract"
        if (
            r"\begin{IEEEkeywords}" in body
            or r"\begin{keywords}" in body
            or "index term" in body.lower()
            or "keywords" in body.lower()
        ):
            return "Index Terms"
        if r"\begin{thebibliography}" in body or r"\bibliography{" in body:
            return "References"
        if r"\appendix" in body:
            return "Appendix"

        # Resume contact indicators
        if r"\href{mailto:" in body or "@" in body:
            return "Name, contact, links"

        # Fallback to bold heading if present near top of block
        m_bf = re.search(r"\\textbf\{", body)
        if m_bf and m_bf.start() < 120:
            res = _extract_balanced_braces(body, m_bf.start())
            if res:
                clean = _clean_latex_title(res[0])
                if clean and len(clean) < 40:
                    return clean

        return f"Zone {key}"

    return name.replace("_", " ").title()


def _kind_for(name: str, body: str = "", desc: str = "") -> str:
    key = name.upper()
    if key in KIND_HINTS:
        return KIND_HINTS[key]

    desc_lower = (desc or "").lower()
    body_lower = (body or "").lower()

    if "title" in desc_lower or r"\title" in body or r"\maketitle" in body:
        return "predefined_title_authors"
    if "abstract" in desc_lower or r"\begin{abstract}" in body:
        return "predefined_abstract"
    if (
        "index term" in desc_lower
        or "keyword" in desc_lower
        or r"\begin{ieeekeywords}" in body_lower
        or r"\begin{keywords}" in body_lower
    ):
        return "predefined_keywords"
    if (
        "reference" in desc_lower
        or "bibliography" in desc_lower
        or r"\begin{thebibliography}" in body
        or r"\bibliography{" in body
    ):
        return "predefined_references"
    if "introduction" in desc_lower:
        return "predefined_introduction"
    if "related work" in desc_lower:
        return "predefined_related_work"
    if "methodology" in desc_lower or "system architecture" in desc_lower:
        return "predefined_methodology"
    if "experiment" in desc_lower or "evaluation" in desc_lower:
        return "predefined_experiments"
    if "discussion" in desc_lower:
        return "predefined_discussion"
    if "conclusion" in desc_lower:
        return "predefined_conclusion"
    if "appendix" in desc_lower or r"\appendix" in body:
        return "predefined_appendix"

    # Resume kinds
    if "header" in desc_lower or "contact" in desc_lower or r"\name{" in body:
        return "predefined_header"
    if "summary" in desc_lower:
        return "predefined_summary"
    if "experience" in desc_lower:
        return "predefined_experience"
    if "education" in desc_lower:
        return "predefined_education"
    if "skill" in desc_lower:
        return "predefined_skills"
    if "project" in desc_lower:
        return "predefined_projects"
    if "certification" in desc_lower:
        return "predefined_certifications"
    if "publication" in desc_lower:
        return "predefined_publications"

    return "custom"


def _segments_from_markers(body: str) -> list[tuple[str, str, str]]:
    """Return list of (name, leading_prefix, inner_body)."""
    starts = list(_ZONE_START.finditer(body))
    if not starts:
        return []

    segments: list[tuple[str, str, str]] = []
    for i, start_m in enumerate(starts):
        name = start_m.group("name")
        end_pat = re.compile(
            rf"^%\s*ZONE:{re.escape(name)}:END\s*$", re.MULTILINE
        )
        end_m = end_pat.search(body, start_m.end())
        if not end_m:
            continue
        if i == 0:
            leading = body[: start_m.start()]
        else:
            prev_name = starts[i - 1].group("name")
            prev_end = re.compile(
                rf"^%\s*ZONE:{re.escape(prev_name)}:END\s*$", re.MULTILINE
            )
            prev_end_m = prev_end.search(body, starts[i - 1].end())
            lead_from = (
                prev_end_m.end() if prev_end_m else starts[i - 1].end()
            )
            leading = body[lead_from : start_m.start()]
        inner = body[start_m.end() : end_m.start()]
        inner = inner.removeprefix("\n")
        inner = inner.removesuffix("\n")
        segments.append((name, leading, inner))
    return segments


def _segments_from_sections(body: str) -> list[tuple[str, str, str]]:
    matches = list(_HEADING_PAT.finditer(body))
    if not matches:
        text = body.strip()
        if not text:
            return []
        return [("1", "", text)]

    segments: list[tuple[str, str, str]] = []
    pre = body[: matches[0].start()].strip()
    if pre:
        if "\\title" in pre or "\\author" in pre or "\\maketitle" in pre:
            segments.append(("TITLE_AUTHORS", "", pre))
        else:
            segments.append(("HEADER", "", pre))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        block = body[start:end].strip()
        matched_str = m.group(1).strip()

        if "\\title{" in matched_str:
            clean = "TITLE_AUTHORS"
        elif "\\name{" in matched_str:
            clean = "HEADER"
        elif "\\begin{abstract}" in matched_str:
            clean = "ABSTRACT"
        elif (
            "\\begin{IEEEkeywords}" in matched_str
            or "\\begin{keywords}" in matched_str
        ):
            clean = "KEYWORDS"
        elif (
            "\\begin{thebibliography}" in matched_str
            or "\\bibliography{" in matched_str
        ):
            clean = "REFERENCES"
        elif "\\appendix" in matched_str:
            clean = "APPENDIX"
        else:
            res = _extract_balanced_braces(body, m.start())
            raw_title = res[0] if res else f"Section{i+1}"
            cleaned_title = _clean_latex_title(raw_title)
            slug = re.sub(r"[^A-Za-z0-9]+", "_", cleaned_title).strip("_")
            clean = slug.upper() or f"SECTION_{i+1}"

        segments.append((clean[:40], "", block))
    return segments


def latex_to_zones(
    latex: str,
    *,
    source_url: str | None = None,
    existing_zones: list[Any] | None = None,
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

    existing_descs: dict[int, str] = {}
    existing_kinds: dict[int, str] = {}
    if existing_zones:
        for z in existing_zones:
            if isinstance(z, dict):
                z_no = z.get("zone_no")
                z_desc = z.get("description")
                z_kind = z.get("kind")
            else:
                z_no = getattr(z, "zone_no", None)
                z_desc = getattr(z, "description", None)
                z_kind = getattr(z, "kind", None)
            if z_no is not None:
                if z_desc:
                    existing_descs[z_no] = str(z_desc)
                if z_kind:
                    existing_kinds[z_no] = str(z_kind)

    zones: list[ZoneRecord] = []
    order: list[int] = []
    for idx, (name, leading, inner) in enumerate(segments, start=1):
        combined = (leading.strip("\n") + "\n" + inner.strip("\n")).strip(
            "\n"
        )
        if not combined:
            combined = "% empty zone"

        target_no = int(name) if name.isdigit() else idx
        prev_desc = existing_descs.get(target_no)
        desc = _description_for(name, combined, existing_desc=prev_desc)
        kind = existing_kinds.get(target_no) or _kind_for(
            name, combined, desc=desc
        )
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

