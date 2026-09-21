"""Document style agent — modifies fonts, sizes, colors, margins, layout."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

try:
    from core.latex_sanitizer import safe_extract_json
    from core.logging_setup import get_logger
    from core.zone_document import ZoneDocument
    from llm_router import ChatMessage, llm_router
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from .latex_sanitizer import safe_extract_json
    from .logging_setup import get_logger
    from .zone_document import ZoneDocument

log = get_logger("style_agent")

_FONT_FAMILIES = {
    "times": "\\usepackage{newtxtext,newtxmath}",
    "helvetica": (
        "\\usepackage{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}"
    ),
    "sans": (
        "\\usepackage{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}"
    ),
    "lmodern": "\\usepackage{lmodern}",
    "latin modern": "\\usepackage{lmodern}",
    "palatino": "\\usepackage{newpxtext,newpxmath}",
    "default": "",
}

_COLOR_THEMES = {
    "blue": {"primary": "1E40AF", "accent": "3B82F6", "text": "1F2937"},
    "royal_blue": {"primary": "2563EB", "accent": "60A5FA", "text": "1F2937"},
    "green": {"primary": "065F46", "accent": "10B981", "text": "1F2937"},
    "emerald": {"primary": "047857", "accent": "34D399", "text": "1F2937"},
    "red": {"primary": "991B1B", "accent": "EF4444", "text": "1F2937"},
    "burgundy": {"primary": "831843", "accent": "DB2777", "text": "1F2937"},
    "purple": {"primary": "581C87", "accent": "8B5CF6", "text": "1F2937"},
    "slate": {"primary": "1E293B", "accent": "64748B", "text": "0F172A"},
    "gray": {"primary": "374151", "accent": "9CA3AF", "text": "111827"},
    "black": {"primary": "000000", "accent": "4B5563", "text": "111827"},
}


class StyleRequest(BaseModel):
    font_family: str | None = Field(
        None,
        description=(
            "Font family: 'times', 'helvetica', 'lmodern', "
            "'palatino', 'default'"
        ),
    )
    font_size: str | None = Field(
        None, description="Font size: '10pt', '11pt', '12pt'"
    )
    color_theme: str | None = Field(
        None,
        description=(
            "Preset theme: 'blue', 'green', 'burgundy', 'slate', 'black', etc."
        ),
    )
    primary_color: str | None = Field(
        None, description="Hex color for primary accents e.g. '#2563EB'"
    )
    accent_color: str | None = Field(
        None, description="Hex color for secondary accents e.g. '#60A5FA'"
    )
    text_color: str | None = Field(
        None, description="Hex color for body text e.g. '#1F2937'"
    )
    margins: str | None = Field(
        None,
        description=(
            "Margin specification e.g. '0.5in', '0.75in', '1in', 'compact'"
        ),
    )
    column_layout: str | None = Field(
        None, description="Column layout: 'onecolumn' or 'twocolumn'"
    )


def _ensure_xcolor(header: str) -> str:
    """Ensure xcolor with dvipsnames is available in preamble."""
    if "PassOptionsToPackage" not in header or "{xcolor}" not in header:
        doc_m = re.search(r"^[ \t]*\\documentclass", header, re.MULTILINE)
        if doc_m:
            opt = (
                "\\PassOptionsToPackage"
                "{dvipsnames,svgnames,x11names}{xcolor}\n"
            )
            header = header[: doc_m.start()] + opt + header[doc_m.start() :]
    if not re.search(r"\\usepackage(?:\[[^\]]*\])?\{xcolor\}", header):
        # Insert right after documentclass
        doc_m = re.search(r"^[ \t]*\\documentclass.*$", header, re.MULTILINE)
        if doc_m:
            xc = "\n\\usepackage[dvipsnames,svgnames,x11names]{xcolor}"
            header = header[: doc_m.end()] + xc + header[doc_m.end() :]
    return header


def apply_font_family(header: str, font_family: str) -> tuple[str, str]:
    """Switch font family in preamble."""
    norm = font_family.lower().strip()
    if norm not in _FONT_FAMILIES:
        return header, ""

    # Remove existing font packages
    cleaned = header
    for pkg in _FONT_FAMILIES.values():
        if not pkg:
            continue
        for line in pkg.split("\n"):
            cleaned = cleaned.replace(line, "")

    pkg_to_add = _FONT_FAMILIES[norm]
    if not pkg_to_add:
        return cleaned, "Reset font family to default"

    # Insert before \begin{document} or at end of header
    doc_match = re.search(r"\\begin\{document\}", cleaned)
    if doc_match:
        idx = doc_match.start()
        new_header = cleaned[:idx] + f"{pkg_to_add}\n" + cleaned[idx:]
    else:
        new_header = cleaned + f"\n{pkg_to_add}\n"

    return new_header, f"Changed font family to {norm.title()}"


def apply_font_size(header: str, font_size: str) -> tuple[str, str]:
    """Adjust documentclass font size (10pt, 11pt, 12pt)."""
    norm = font_size.lower().strip()
    if norm not in ("10pt", "11pt", "12pt"):
        return header, ""

    # Check for existing \documentclass[...]{...}
    m = re.search(r"\\documentclass\s*(\[[^\]]*\])?\s*\{([^}]+)\}", header)
    if not m:
        return header, ""

    opts = m.group(1)
    cls_name = m.group(2)

    if opts:
        # Replace existing pt size if present
        opt_str = opts[1:-1]
        if re.search(r"\b\d+pt\b", opt_str):
            new_opts = re.sub(r"\b\d+pt\b", norm, opt_str)
        else:
            new_opts = f"{norm},{opt_str}"
        repl = f"\\documentclass[{new_opts}]{{{cls_name}}}"
    else:
        repl = f"\\documentclass[{norm}]{{{cls_name}}}"

    new_header = header[: m.start()] + repl + header[m.end() :]
    return new_header, f"Changed font size to {norm}"


def apply_color_theme(
    header: str,
    *,
    theme: str | None = None,
    primary: str | None = None,
    accent: str | None = None,
    text: str | None = None,
) -> tuple[str, str]:
    """Define or update primary, accent, and text colors."""
    header = _ensure_xcolor(header)

    colors: dict[str, str] = {}
    if theme and theme.lower() in _COLOR_THEMES:
        colors.update(_COLOR_THEMES[theme.lower()])

    if primary:
        colors["primary"] = primary.lstrip("#").strip()
    if accent:
        colors["accent"] = accent.lstrip("#").strip()
    if text:
        colors["text"] = text.lstrip("#").strip()

    if not colors:
        return header, ""

    new_header = header
    changes: list[str] = []

    for cname, chex in colors.items():
        if len(chex) != 6 and len(chex) != 3:
            continue
        # Check if color is already defined
        pat = re.compile(
            rf"\\(?:definecolor|providecolor)\{{{cname}\}}"
            r"\{HTML\}\{[^}]+\}"
        )
        def_stmt = f"\\definecolor{{{cname}}}{{HTML}}{{{chex.upper()}}}"
        if pat.search(new_header):
            new_header = pat.sub(def_stmt, new_header)
        else:
            # Insert before \begin{document}
            doc_m = re.search(r"\\begin\{document\}", new_header)
            if doc_m:
                idx = doc_m.start()
                new_header = (
                    new_header[:idx] + f"{def_stmt}\n" + new_header[idx:]
                )
            else:
                new_header += f"\n{def_stmt}\n"
        changes.append(f"{cname}=#{chex.upper()}")

    return new_header, f"Updated colors: {', '.join(changes)}"


def apply_margins(header: str, margin_spec: str) -> tuple[str, str]:
    """Set document margins via geometry package."""
    spec = margin_spec.strip()
    if spec.lower() == "compact":
        geom_opts = "left=0.5in,top=0.4in,right=0.5in,bottom=0.4in"
    elif spec.lower() == "normal":
        geom_opts = "left=0.75in,top=0.6in,right=0.75in,bottom=0.6in"
    elif spec.lower() == "wide":
        geom_opts = "left=1in,top=1in,right=1in,bottom=1in"
    elif re.match(r"^\d+(?:\.\d+)?(?:in|cm|mm|pt)$", spec):
        geom_opts = f"margin={spec}"
    else:
        geom_opts = spec

    pat = re.compile(r"\\usepackage\s*(\[[^\]]*\])?\s*\{geometry\}")
    m = pat.search(header)
    if m:
        repl = f"\\usepackage[{geom_opts}]{{geometry}}"
        new_header = header[: m.start()] + repl + header[m.end() :]
    else:
        stmt = f"\\usepackage[{geom_opts}]{{geometry}}\n"
        doc_m = re.search(r"\\begin\{document\}", header)
        if doc_m:
            idx = doc_m.start()
            new_header = header[:idx] + stmt + header[idx:]
        else:
            new_header += f"\n{stmt}"

    return new_header, f"Updated margins to [{geom_opts}]"


def apply_column_layout(header: str, layout: str) -> tuple[str, str]:
    """Toggle onecolumn vs twocolumn layout."""
    norm = layout.lower().strip()
    if norm not in ("onecolumn", "twocolumn"):
        return header, ""

    m = re.search(r"\\documentclass\s*(\[[^\]]*\])?\s*\{([^}]+)\}", header)
    if not m:
        return header, ""

    opts = m.group(1)
    cls_name = m.group(2)

    other = "onecolumn" if norm == "twocolumn" else "twocolumn"
    if opts:
        opt_str = opts[1:-1]
        if other in opt_str:
            new_opts = opt_str.replace(other, norm)
        elif norm not in opt_str:
            new_opts = f"{opt_str},{norm}"
        else:
            new_opts = opt_str
        repl = f"\\documentclass[{new_opts}]{{{cls_name}}}"
    else:
        repl = f"\\documentclass[{norm}]{{{cls_name}}}"

    new_header = header[: m.start()] + repl + header[m.end() :]
    return new_header, f"Set layout to {norm}"


class DocumentStyleAgent:
    """Specialist agent for modifying preamble styling and layout."""

    def run_style(
        self,
        doc: ZoneDocument,
        user_message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> tuple[ZoneDocument, str]:
        """Parse style request from message and apply modifications."""
        system_prompt = (
            "You are the LaTeX Document Style specialist. Analyze the user's "
            "styling request and extract target styling parameters.\n\n"
            "Supported properties:\n"
            "- font_family: 'times', 'helvetica', 'lmodern', "
            "'palatino', 'default'\n"
            "- font_size: '10pt', '11pt', '12pt'\n"
            "- color_theme: 'blue', 'royal_blue', 'green', 'emerald', "
            "'red', 'burgundy', 'slate', 'black'\n"
            "- primary_color: '#RRGGBB'\n"
            "- accent_color: '#RRGGBB'\n"
            "- text_color: '#RRGGBB'\n"
            "- margins: 'compact', 'normal', 'wide', '0.5in', "
            "'0.75in', '1in'\n"
            "- column_layout: 'onecolumn', 'twocolumn'\n\n"
            "Return JSON object matching this schema:\n"
            "{\n"
            '  "font_family": null,\n'
            '  "font_size": null,\n'
            '  "color_theme": null,\n'
            '  "primary_color": null,\n'
            '  "accent_color": null,\n'
            '  "text_color": null,\n'
            '  "margins": null,\n'
            '  "column_layout": null\n'
            "}"
        )

        try:
            resp = llm_router.chat(
                [
                    ChatMessage(role="system", content=system_prompt),
                    ChatMessage(role="user", content=user_message),
                ],
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.1,
                response_format="json",
            )
            data = safe_extract_json(resp.content)
            req = StyleRequest(**data)
        except Exception as e:
            log.warning(
                "style_agent: LLM parsing failed (%s), using heuristics", e
            )
            req = self._heuristic_parse(user_message)

        header = doc.header
        applied_notes: list[str] = []

        if req.font_family:
            header, note = apply_font_family(header, req.font_family)
            if note:
                applied_notes.append(note)

        if req.font_size:
            header, note = apply_font_size(header, req.font_size)
            if note:
                applied_notes.append(note)

        if (
            req.color_theme
            or req.primary_color
            or req.accent_color
            or req.text_color
        ):
            header, note = apply_color_theme(
                header,
                theme=req.color_theme,
                primary=req.primary_color,
                accent=req.accent_color,
                text=req.text_color,
            )
            if note:
                applied_notes.append(note)

        if req.margins:
            header, note = apply_margins(header, req.margins)
            if note:
                applied_notes.append(note)

        if req.column_layout:
            header, note = apply_column_layout(header, req.column_layout)
            if note:
                applied_notes.append(note)

        doc.header = header
        summary = (
            "; ".join(applied_notes)
            if applied_notes
            else "Updated document styling."
        )
        log.info("style_agent.step: applied %s", summary)
        return doc, summary

    def _heuristic_parse(self, msg: str) -> StyleRequest:
        """Fallback regex extraction when LLM is unavailable."""
        low = msg.lower()
        req = StyleRequest()

        # Font
        if "times" in low:
            req.font_family = "times"
        elif "helvetica" in low or "sans" in low:
            req.font_family = "helvetica"
        elif "palatino" in low:
            req.font_family = "palatino"
        elif "latin modern" in low or "lmodern" in low:
            req.font_family = "lmodern"

        # Size
        m_size = re.search(r"\b(10|11|12)\s*pt\b", low)
        if m_size:
            req.font_size = f"{m_size.group(1)}pt"

        # Theme / Colors
        for t in _COLOR_THEMES:
            if t in low:
                req.color_theme = t
                break

        m_hex = re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", msg)
        if m_hex:
            req.primary_color = m_hex[0]

        # Layout
        if "two col" in low or "2 col" in low or "twocolumn" in low:
            req.column_layout = "twocolumn"
        elif "one col" in low or "1 col" in low or "onecolumn" in low:
            req.column_layout = "onecolumn"

        # Margins
        if "compact" in low or "tight" in low:
            req.margins = "compact"
        elif "wide" in low:
            req.margins = "wide"
        elif "normal" in low:
            req.margins = "normal"

        m_mar = re.search(
            r"(\d+(?:\.\d+)?\s*(?:in|cm|mm|pt))\s*(?:margin|margins)?", low
        )
        if m_mar and not req.margins:
            req.margins = m_mar.group(1).replace(" ", "")

        return req


style_agent = DocumentStyleAgent()
