"""Dynamic zone extract/replace for maintainable LaTeX resumes."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

ZONE_START = re.compile(
    r"%\s*ZONE:(?P<name>[A-Za-z0-9_]+):START\s*$", re.MULTILINE
)
ZONE_END_TMPL = r"%\s*ZONE:{name}:END\s*$"


class ZoneError(Exception):
    """Raised when zone markers are missing or malformed."""


class ZoneEngine:
    """Parse and surgically update % ZONE:NAME:START/END regions."""

    def list_zones(self, latex: str) -> List[str]:
        return [m.group("name") for m in ZONE_START.finditer(latex)]

    def extract_zones(self, latex: str) -> Dict[str, str]:
        zones: Dict[str, str] = {}
        for name, content, _, _ in self._iter_zones(latex):
            zones[name] = content
        return zones

    def get_zone(self, latex: str, zone_id: str) -> str:
        zones = self.extract_zones(latex)
        if zone_id not in zones:
            raise ZoneError(
                f"Unknown zone '{zone_id}'. "
                f"Available: {', '.join(zones.keys()) or '(none)'}"
            )
        return zones[zone_id]

    def replace_zone(self, latex: str, zone_id: str, content: str) -> str:
        for name, old, start, end in self._iter_zones(latex):
            if name != zone_id:
                continue
            # Keep markers; replace inner content
            # Find full span including markers
            start_line_end = latex.find("\n", start)
            if start_line_end == -1:
                start_line_end = start
            end_match = re.search(
                ZONE_END_TMPL.format(name=re.escape(zone_id)),
                latex[end:],
                re.MULTILINE,
            )
            if not end_match:
                raise ZoneError(f"Missing END marker for zone '{zone_id}'")
            # Re-find precise bounds
            start_m = ZONE_START.search(latex, start)
            if not start_m or start_m.group("name") != zone_id:
                raise ZoneError(f"Could not locate START for '{zone_id}'")
            end_m = re.search(
                ZONE_END_TMPL.format(name=re.escape(zone_id)),
                latex[start_m.end() :],
                re.MULTILINE,
            )
            if not end_m:
                raise ZoneError(f"Missing END marker for zone '{zone_id}'")
            abs_end = start_m.end() + end_m.start()
            inner = content
            if not inner.startswith("\n"):
                inner = "\n" + inner
            if not inner.endswith("\n"):
                inner = inner + "\n"
            return latex[: start_m.end()] + inner + latex[abs_end:]

        raise ZoneError(
            f"Unknown zone '{zone_id}'. "
            f"Available: {', '.join(self.list_zones(latex)) or '(none)'}"
        )

    def replace_zones(self, latex: str, updates: Dict[str, str]) -> str:
        result = latex
        for zone_id, content in updates.items():
            result = self.replace_zone(result, zone_id, content)
        return result

    def validate(self, latex: str) -> Tuple[bool, List[str]]:
        issues: List[str] = []
        names = self.list_zones(latex)
        seen = set()
        for name in names:
            if name in seen:
                issues.append(f"Duplicate zone START: {name}")
            seen.add(name)
            end_pat = re.compile(
                ZONE_END_TMPL.format(name=re.escape(name)), re.MULTILINE
            )
            if not end_pat.search(latex):
                issues.append(f"Missing END for zone: {name}")
        # Orphan ends
        for m in re.finditer(
            r"%\s*ZONE:([A-Za-z0-9_]+):END\s*$", latex, re.MULTILINE
        ):
            if m.group(1) not in seen:
                issues.append(f"Orphan END for zone: {m.group(1)}")
        return (len(issues) == 0, issues)

    def zone_digest(self, latex: str, max_chars: int = 400) -> str:
        parts = []
        for name, content in self.extract_zones(latex).items():
            snippet = content.strip().replace("\n", " ")
            if len(snippet) > max_chars:
                snippet = snippet[: max_chars - 3] + "..."
            parts.append(f"[{name}] {snippet}")
        return "\n".join(parts) if parts else "(no zones)"

    def _iter_zones(self, latex: str):
        for start_m in ZONE_START.finditer(latex):
            name = start_m.group("name")
            end_m = re.search(
                ZONE_END_TMPL.format(name=re.escape(name)),
                latex[start_m.end() :],
                re.MULTILINE,
            )
            if not end_m:
                continue
            content_start = start_m.end()
            content_end = start_m.end() + end_m.start()
            content = latex[content_start:content_end]
            # Strip leading/trailing single newlines from marker lines
            if content.startswith("\n"):
                content = content[1:]
            if content.endswith("\n"):
                content = content[:-1]
            yield name, content, start_m.start(), content_end


zone_engine = ZoneEngine()
