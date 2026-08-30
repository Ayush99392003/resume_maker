"""Numbered zone document model: fixed header/footer + Zone 1..N bodies."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ZoneRecord(BaseModel):
    zone_no: int
    description: str = ""
    latex: str = ""
    kind: str = "custom"


class ZoneDocument(BaseModel):
    """Canonical resume structure for the orchestrator."""

    header: str = ""
    footer: str = ""
    zones: List[ZoneRecord] = Field(default_factory=list)
    zone_order: List[int] = Field(default_factory=list)
    next_zone_no: int = 1
    source_url: Optional[str] = None

    def zone_map(self) -> Dict[int, ZoneRecord]:
        return {z.zone_no: z for z in self.zones}

    def get_zone(self, zone_no: int) -> ZoneRecord:
        zmap = self.zone_map()
        if zone_no not in zmap:
            raise KeyError(f"Unknown zone_no {zone_no}")
        return zmap[zone_no]

    def catalog(self) -> List[Dict[str, Any]]:
        zmap = self.zone_map()
        rows = []
        for n in self.zone_order:
            z = zmap.get(n)
            if not z:
                continue
            rows.append(
                {
                    "zone_no": z.zone_no,
                    "description": z.description,
                    "kind": z.kind,
                }
            )
        return rows

    def wrap_zone_body(self, zone_no: int, inner: str) -> str:
        body = (inner or "").strip("\n")
        return f"% ZONE:{zone_no}:START\n{body}\n% ZONE:{zone_no}:END\n"

    def set_zone_inner(self, zone_no: int, inner: str) -> None:
        z = self.get_zone(zone_no)
        z.latex = self.wrap_zone_body(zone_no, inner)

    def zone_inner(self, zone_no: int) -> str:
        z = self.get_zone(zone_no)
        return strip_zone_markers(z.latex, zone_no)

    def assemble(self) -> str:
        header = self.header or ""
        if "\\begin{document}" not in header:
            if "\\documentclass" not in header:
                header = (
                    "\\documentclass[11pt,a4paper]{article}\n"
                    "\\usepackage[utf8]{inputenc}\n"
                    "\\usepackage[T1]{fontenc}\n"
                    "\\usepackage[margin=1in]{geometry}\n"
                    "\\begin{document}\n"
                )
            else:
                header = header.rstrip() + "\n\\begin{document}\n"
        footer = self.footer or ""
        if "\\end{document}" not in footer:
            footer = "\\end{document}\n"

        zmap = self.zone_map()
        parts: List[str] = [header.rstrip() + "\n"]
        for n in self.zone_order:
            z = zmap.get(n)
            if not z:
                continue
            block = z.latex.strip()
            if f"ZONE:{n}:START" not in block:
                block = self.wrap_zone_body(n, block).strip()
            parts.append(block + "\n")
        if not footer.startswith("\n"):
            footer = "\n" + footer
        parts.append(footer)
        text = "".join(parts)
        if not text.endswith("\n"):
            text += "\n"
        return text

    def add_zone(
        self,
        *,
        description: str = "",
        latex_inner: str = "",
        kind: str = "custom",
        after_zone_no: Optional[int] = None,
        at_start: bool = False,
    ) -> ZoneRecord:
        zone_no = self.next_zone_no
        self.next_zone_no = zone_no + 1
        record = ZoneRecord(
            zone_no=zone_no,
            description=description or f"Zone {zone_no}",
            latex=self.wrap_zone_body(zone_no, latex_inner or "% empty zone"),
            kind=kind,
        )
        self.zones.append(record)
        if at_start:
            self.zone_order.insert(0, zone_no)
        elif after_zone_no is not None and after_zone_no in self.zone_order:
            idx = self.zone_order.index(after_zone_no)
            self.zone_order.insert(idx + 1, zone_no)
        else:
            self.zone_order.append(zone_no)
        return record

    def remove_zone(self, zone_no: int) -> ZoneRecord:
        zmap = self.zone_map()
        if zone_no not in zmap:
            raise KeyError(f"Unknown zone_no {zone_no}")
        removed = zmap[zone_no]
        self.zones = [z for z in self.zones if z.zone_no != zone_no]
        self.zone_order = [n for n in self.zone_order if n != zone_no]
        return removed

    def reorder(self, new_order: List[int]) -> None:
        existing = set(self.zone_order)
        if set(new_order) != existing:
            missing = existing - set(new_order)
            extra = set(new_order) - existing
            raise ValueError(
                f"Invalid zone_order. missing={sorted(missing)} "
                f"extra={sorted(extra)}"
            )
        self.zone_order = list(new_order)

    def swap(self, a: int, b: int) -> None:
        if a not in self.zone_order or b not in self.zone_order:
            raise KeyError("swap targets must be in zone_order")
        order = list(self.zone_order)
        i, j = order.index(a), order.index(b)
        order[i], order[j] = order[j], order[i]
        self.zone_order = order

    def move(
        self,
        zone_no: int,
        *,
        before: Optional[int] = None,
        after: Optional[int] = None,
    ) -> None:
        if zone_no not in self.zone_order:
            raise KeyError(f"Unknown zone_no {zone_no}")
        order = [n for n in self.zone_order if n != zone_no]
        if before is not None:
            if before not in order:
                raise KeyError(f"Unknown before zone_no {before}")
            order.insert(order.index(before), zone_no)
        elif after is not None:
            if after not in order:
                raise KeyError(f"Unknown after zone_no {after}")
            order.insert(order.index(after) + 1, zone_no)
        else:
            order.insert(0, zone_no)
        self.zone_order = order

    def digest(self, max_chars: int = 280) -> str:
        parts = []
        for n in self.zone_order:
            try:
                inner = self.zone_inner(n).strip().replace("\n", " ")
            except KeyError:
                continue
            if len(inner) > max_chars:
                inner = inner[: max_chars - 3] + "..."
            z = self.get_zone(n)
            desc = z.description or f"Zone {n}"
            parts.append(f"[Zone {n} — {desc}] {inner}")
        return "\n".join(parts) if parts else "(no zones)"

    def compact_digest(self, active_zone_no: Optional[int] = None) -> str:
        """Generate ultra-lightweight (1-line per zone) structural context (~50-80 tokens total)."""
        lines = []
        for n in self.zone_order:
            if active_zone_no is not None and n == active_zone_no:
                continue
            try:
                z = self.get_zone(n)
                inner = self.zone_inner(n).strip()
                first_line = ""
                for line in inner.split("\n"):
                    line_s = line.strip()
                    if line_s and not line_s.startswith("%") and not line_s.startswith("\\begin"):
                        clean = re.sub(r"\\[a-zA-Z]+(\{[^}]*\})?", " ", line_s)
                        clean = re.sub(r"[{}\\]", "", clean).strip()
                        if clean:
                            first_line = clean[:60]
                            break
                desc = z.description or z.kind or f"Zone {n}"
                snippet = f" — {first_line}" if first_line else ""
                lines.append(f"- Zone {n} [{desc}]{snippet}")
            except KeyError:
                continue
        return "\n".join(lines) if lines else "(no other zones)"


def ensure_full_document(latex: str) -> str:
    """Guarantee a compilable shell around zone-only fragments."""
    try:
        from .latex_soften import soften_latex_for_tectonic
    except ImportError:
        from latex_soften import soften_latex_for_tectonic  # type: ignore

    text, _notes = soften_latex_for_tectonic((latex or "").strip())
    if not text:
        return (
            "\\documentclass[11pt,a4paper]{article}\n"
            "\\begin{document}\n"
            "(empty)\n"
            "\\end{document}\n"
        )
    if "\\begin{document}" in text and "\\end{document}" in text:
        return text if text.endswith("\n") else text + "\n"
    if "\\documentclass" in text and "\\begin{document}" not in text:
        return text.rstrip() + "\n\\begin{document}\n\\end{document}\n"
    return (
        "\\documentclass[11pt,a4paper]{article}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\begin{document}\n"
        f"{text}\n"
        "\\end{document}\n"
    )


def strip_zone_markers(latex: str, zone_no: int) -> str:
    text = latex or ""
    start = re.compile(rf"%\s*ZONE:{zone_no}:START\s*\n?", re.MULTILINE)
    end = re.compile(rf"\n?\s*%\s*ZONE:{zone_no}:END\s*", re.MULTILINE)
    text = start.sub("", text)
    text = end.sub("", text)
    return text.strip("\n")


def sync_session_from_document(session: Any, doc: ZoneDocument) -> None:
    """Write ZoneDocument fields + assembled latex onto a ChatSession."""
    assembled = doc.assemble()
    if "\\begin{document}" not in (doc.header or ""):
        begin = assembled.find("\\begin{document}")
        if begin != -1:
            end_begin = assembled.find("\n", begin)
            doc.header = assembled[: end_begin + 1] if end_begin != -1 else assembled[: begin + len("\\begin{document}")] + "\n"
    if "\\end{document}" not in (doc.footer or ""):
        doc.footer = "\\end{document}\n"
    session.header = doc.header
    session.footer = doc.footer
    session.zones = [z.model_dump() for z in doc.zones]
    session.zone_order = list(doc.zone_order)
    session.next_zone_no = doc.next_zone_no
    session.source_url = doc.source_url
    session.latex_code = assembled
    session.setup_complete = True


def document_from_session(session: Any) -> Optional[ZoneDocument]:
    """Rebuild ZoneDocument from session fields, or None if not set up."""
    zones_raw = getattr(session, "zones", None) or []
    header = getattr(session, "header", None) or ""
    footer = getattr(session, "footer", None) or ""
    order = getattr(session, "zone_order", None) or []
    if not header and not zones_raw:
        return None
    if zones_raw and "\\begin{document}" not in header:
        latex = getattr(session, "latex_code", None) or ""
        begin_idx = latex.find("\\begin{document}")
        if begin_idx != -1:
            eol = latex.find("\n", begin_idx)
            repaired_header = (
                latex[: eol + 1] if eol != -1
                else latex[: begin_idx + len("\\begin{document}")] + "\n"
            )
            header = repaired_header
        elif "\\begin{document}" in latex:
            if not zones_raw:
                try:
                    from .latex_to_zones import latex_to_zones

                    return latex_to_zones(
                        latex,
                        source_url=getattr(session, "source_url", None),
                    )
                except Exception:
                    pass
    zones = [
        ZoneRecord(**z) if isinstance(z, dict) else z
        for z in zones_raw
    ]
    return ZoneDocument(
        header=header,
        footer=footer,
        zones=zones,
        zone_order=(
            list(order) if order else [z.zone_no for z in zones]
        ),
        next_zone_no=(
            getattr(session, "next_zone_no", None)
            or (max([z.zone_no for z in zones], default=0) + 1)
        ),
        source_url=getattr(session, "source_url", None),
    )
