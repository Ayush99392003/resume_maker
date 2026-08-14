"""Per-zone resume specialists and a router that dispatches to them."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

try:
    from llm_router import ChatMessage, llm_router
    from core.zones import zone_engine
    from core.logging_setup import get_logger
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from ..zones import zone_engine
    from ..logging_setup import get_logger

log = get_logger("zone_agents")


def _pre_escape_backslashes(raw: str) -> str:
    r"""Pre-process raw LLM text before JSON parse.

    Some LLMs emit single backslashes in JSON string values that are
    invalid JSON escape sequences (e.g. ``\s`` in ``\section``,
    ``\r`` in ``\resumeItem``).  Python's ``json.loads`` silently drops
    the backslash, turning ``\section`` into ``section``.

    We escape every bare backslash that is NOT already part of a valid
    two-character JSON escape sequence (``\n``, ``\t``, ``\r``, ``\\",
    ``\"``, ``\/``, ``\b``, ``\f``, ``\uXXXX``) so that JSON can parse
    it correctly.

    Args:
        raw: Raw text returned by the LLM (may or may not be JSON).

    Returns:
        Text with single backslashes escaped to double backslashes.
    """
    # Escape single backslashes that are:
    # 1. Not adjacent to another backslash
    # 2. Followed by a non-JSON escape character OR
    #    Followed by b/f/n/r/t and a letter (e.g. \begin, \name) OR
    #    Followed by u but not 4 hex digits (e.g. \user)
    pattern = (
        r'(?<!\\)\\(?!\\)(?:'
        r'(?!["\\/bfnrtu])|'
        r'(?=[bfnrt][a-zA-Z])|'
        r'(?=u(?![0-9a-fA-F]{4}))'
        r')'
    )
    return re.sub(pattern, r"\\\\", raw)


def _clean_backslash_typos(text: str) -> str:
    """Restore backslashes on commands merged with newlines (e.g. \\nitem)."""
    pattern = (
        r'\\n(item|begin|end|cventry|cvitem|section|'
        r'subsection|textbf|textit|href)\b'
    )
    return re.sub(pattern, r'\n\\\1', text)


def _escape_raw_latex_chars(text: str) -> str:
    """Escape raw %, _, and # characters not preceded by a backslash."""
    text = re.sub(r'(?<!\\)%', r'\%', text)
    text = re.sub(r'(?<!\\)_', r'\_', text)
    text = re.sub(r'(?<!\\)#', r'\#', text)
    return text


def _sanitize_tex_json(obj: Any) -> Any:
    """Restore TeX control sequences mangled by JSON decode.

    De-duplicates double-double backslashes introduced by some LLMs
    (``\\\\cmd`` → ``\\cmd``).
    """
    if isinstance(obj, str):
        # De-duplicate \\\\cmd → \\cmd (over-escaped by some LLMs)
        obj = re.sub(r"\\\\\\\\([a-zA-Z])", r"\\\\\1", obj)
        obj = _clean_backslash_typos(obj)
        obj = _escape_raw_latex_chars(obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_tex_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_tex_json(x) for x in obj]
    return obj


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Pre-escape invalid bare backslashes before parsing
    text = _pre_escape_backslashes(text)
    try:
        return _sanitize_tex_json(json.loads(text))
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return _sanitize_tex_json(json.loads(match.group(0)))
        raise



class ZoneAgentResponse(BaseModel):
    content: str = Field(
        ...,
        description=(
            "The updated LaTeX code fragment for this zone only. "
            "Never return a full document or zone markers."
        )
    )
    summary: str = Field(
        ...,
        description="A short, one-sentence summary of the changes made."
    )

    @field_validator("content")
    @classmethod
    def check_no_full_document(cls, v: str) -> str:
        bad_commands = [
            "\\documentclass",
            "\\begin{document}",
            "\\end{document}",
        ]
        for cmd in bad_commands:
            if cmd in v:
                raise ValueError(
                    f"Do not include full document commands like '{cmd}'. "
                    "Only return the LaTeX fragment for this specific zone."
                )
        return v

    @field_validator("content")
    @classmethod
    def check_no_zone_markers(cls, v: str) -> str:
        if "% ZONE:" in v or "ZONE:" in v:
            raise ValueError(
                "Do not include zone markers like '% ZONE:NAME:START' or "
                "'% ZONE:NAME:END' in the content."
            )
        return v

    @field_validator("content")
    @classmethod
    def check_valid_item_list(cls, v: str) -> str:
        if "\\item" in v:
            if "\\begin{" not in v or "\\end{" not in v:
                raise ValueError(
                    "Bare \\item bullets are forbidden. Enclose them in a "
                    "list environment like \\begin{itemize} ... \\end{itemize}."
                )
        return v


class ZoneAgent:
    """Specialist that owns a single resume zone."""

    zone_id: str = ""
    role: str = ""
    latex_hints: str = ""

    def run(
        self,
        *,
        user_message: str,
        current_zone: str,
        full_digest: str,
        is_initial: bool,
        provider: Optional[str],
        model: Optional[str],
        api_key: Optional[str],
        max_retries: int = 3,
    ) -> Tuple[str, str]:
        """Return (new_zone_latex, short_summary)."""
        mode = "initial fill from bio" if is_initial else "targeted edit"
        system = (
            f"You are the {self.role} for a LaTeX resume.\n"
            f"You ONLY edit the {self.zone_id} zone. Never return a full "
            f"document, preamble, or zone markers.\n"
            f"CRITICAL: If using \\item bullets, you MUST enclose them within "
            f"a valid list environment like \\begin{{itemize}} ... "
            f"\\end{{itemize}} (or the template's designated list macro). "
            f"Never return bare \\item lines outside a list environment.\n"
            f"Preserve all custom command styles, alignment, spacing, and "
            f"formatting structure present in the original zone.\n"
            f"Return your answer as a JSON object containing 'content' "
            f"and 'summary' fields.\n\n"
            f"--- EXAMPLES ---\n"
            f"Example 1: Adding a skills item\n"
            f"Request: Add Python, Java to Skills\n"
            f"Response JSON: {{\n"
            f"  \"content\": \"Python, Java\",\n"
            f"  \"summary\": \"Added Python and Java to skills.\"\n"
            f"}}\n\n"
            f"Example 2: Adding experience bullets\n"
            f"Request: Add bullet about database design\n"
            f"Response JSON: {{\n"
            f"  \"content\": \"\\\\begin{{itemize}}\\n"
            f"\\\\item Designed database schema.\\\\end{{itemize}}\",\n"
            f"  \"summary\": \"Added bullet point for database design.\"\n"
            f"}}\n\n"
            f"LaTeX guidance:\n{self.latex_hints}"
        )
        user = (
            f"Mode: {mode}\n"
            f"Zone: {self.zone_id}\n"
            f"Current zone content:\n{current_zone or '(empty)'}\n\n"
            f"Other zones (context only, do not rewrite):\n{full_digest}\n\n"
            f"User request:\n{user_message}"
        )

        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ]

        for attempt in range(max_retries):
            resp = llm_router.chat(
                messages,
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.35,
                response_format="json",
            )
            raw_content = resp.content
            try:
                # Pre-escape invalid backslashes
                sanitized = _pre_escape_backslashes(raw_content)
                data = _extract_json(sanitized)
            except Exception as e:
                err_msg = (
                    f"JSON parsing failed: {e}. Please ensure you return "
                    "a valid JSON object matching the schema."
                )
                log.warning(
                    "Attempt %d JSON parse failed: %s", attempt + 1, e
                )
                messages.append(
                    ChatMessage(role="assistant", content=raw_content)
                )
                messages.append(ChatMessage(role="user", content=err_msg))
                continue

            try:
                validated = ZoneAgentResponse.model_validate(data)
                content = validated.content.strip()
                content = _clean_backslash_typos(content)
                summary = validated.summary.strip()
                if not content:
                    raise ValueError("content field is empty")
                return content, summary
            except Exception as e:
                err_msg = (
                    f"Validation failed:\n{e}\n"
                    "Please fix these errors and return a valid JSON object."
                )
                log.warning(
                    "Attempt %d validation failed: %s", attempt + 1, e
                )
                messages.append(
                    ChatMessage(role="assistant", content=raw_content)
                )
                messages.append(ChatMessage(role="user", content=err_msg))

        raise ValueError(
            f"ZoneAgent {self.zone_id} failed after {max_retries} attempts."
        )


class HeaderAgent(ZoneAgent):
    zone_id = "HEADER"
    role = "Header / contact specialist"
    latex_hints = (
        "For moderncv: keep \\name{}, \\title{}, \\address{}, \\phone, "
        "\\email, \\homepage. Replace placeholders with real data. "
        "For article templates: keep the existing center/flushleft structure."
    )


class SummaryAgent(ZoneAgent):
    zone_id = "SUMMARY"
    role = "Professional summary specialist"
    latex_hints = (
        "Write 2-4 concise sentences of plain LaTeX text (no \\section). "
        "Professional tone; highlight impact and focus."
    )


class ExperienceAgent(ZoneAgent):
    zone_id = "EXPERIENCE"
    role = "Work experience specialist"
    latex_hints = (
        "Use moderncv \\cventry{years}{title}{company}{city}{}{bullets} when "
        "the template is moderncv, otherwise use itemize with bold roles. "
        "Prefer quantified bullets. No \\section commands."
    )


class EducationAgent(ZoneAgent):
    zone_id = "EDUCATION"
    role = "Education specialist"
    latex_hints = (
        "Use \\cventry or compact degree lines. Include school, degree, years. "
        "No \\section commands."
    )


class SkillsAgent(ZoneAgent):
    zone_id = "SKILLS"
    role = "Skills specialist"
    latex_hints = (
        "Use \\cvitem{Category}{items} for moderncv, or a compact comma/"
        "itemize list otherwise. Group by category when possible."
    )


class ProjectsAgent(ZoneAgent):
    zone_id = "PROJECTS"
    role = "Projects specialist"
    latex_hints = (
        "Check the preamble for custom macros. "
        "If \\resumeProjectHeading is defined: use "
        "\\resumeProjectHeading{{\\textbf{{Name}}}}{{Date}} then "
        "\\resumeItemListStart / \\resumeItem{{...}} / \\resumeItemListEnd. "
        "If \\resumeProjectHeading is NOT defined: use "
        "\\subsection*{{Name}} + \\begin{{itemize}} \\item bullets \\end{{itemize}}. "
        "Never invent macros that are not defined in the preamble. "
        "No \\section commands."
    )

ZONE_AGENT_CLASSES = {
    "HEADER": HeaderAgent,
    "SUMMARY": SummaryAgent,
    "EXPERIENCE": ExperienceAgent,
    "EDUCATION": EducationAgent,
    "SKILLS": SkillsAgent,
    "PROJECTS": ProjectsAgent,
}

# Maps lowercase words in zone descriptions/kinds to agent class keys
_DESC_TO_AGENT: list[tuple[tuple[str, ...], str]] = [
    (("experience", "work", "job", "employment", "career"), "EXPERIENCE"),
    (("project", "portfolio", "work sample"), "PROJECTS"),
    (("education", "degree", "school", "university", "academic"), "EDUCATION"),
    (("skill", "stack", "technolog", "language", "tool"), "SKILLS"),
    (("summary", "about", "profile", "objective"), "SUMMARY"),
    (("header", "contact", "name", "heading", "personal"), "HEADER"),
]


def _description_to_agent_key(description: str, kind: str) -> Optional[str]:
    """Map a zone description/kind string to a semantic agent class key.

    Args:
        description: Human-readable zone description (e.g. 'Work experience').
        kind: Zone kind string (e.g. 'predefined_experience').

    Returns:
        Agent class key like ``'EXPERIENCE'``, or ``None`` if no match.
    """
    text = (description + " " + kind).lower()
    for keywords, agent_key in _DESC_TO_AGENT:
        if any(kw in text for kw in keywords):
            return agent_key
    return None


class ZoneAgentRouter:
    """Classifies which zones to touch, then calls the matching zone agents."""

    def __init__(self):
        self.agents: Dict[str, ZoneAgent] = {
            zid: cls() for zid, cls in ZONE_AGENT_CLASSES.items()
        }

    def _resolve_agent(
        self,
        zone_id: str,
        zone_catalog: Optional[List[Dict]] = None,
    ) -> ZoneAgent:
        """Return the best specialist for *zone_id*.

        For named zone IDs (e.g. ``EXPERIENCE``) we do a direct lookup.
        For numeric zone IDs (e.g. ``'2'``) we inspect *zone_catalog* to
        map the zone's description/kind to a semantic agent key.

        Args:
            zone_id: Zone identifier string from the zone engine.
            zone_catalog: List of ``{zone_no, description, kind}`` dicts
                from :meth:`ZoneDocument.catalog`.

        Returns:
            Best matching :class:`ZoneAgent` instance.
        """
        # Direct named-key lookup
        agent = self.agents.get(zone_id.upper()) or self.agents.get(zone_id)
        if agent:
            return agent

        # Try resolving numeric ID via zone catalog
        if zone_catalog:
            for entry in zone_catalog:
                if str(entry.get("zone_no")) == str(zone_id):
                    desc = entry.get("description", "")
                    kind = entry.get("kind", "")
                    agent_key = _description_to_agent_key(desc, kind)
                    if agent_key and agent_key in self.agents:
                        resolved = self.agents[agent_key]
                        log.info(
                            "zone_agent.resolve: zone=%s desc=%r "
                            "-> agent=%s",
                            zone_id, desc, agent_key,
                        )
                        return resolved

        # Generic fallback
        fallback = ZoneAgent()
        fallback.zone_id = zone_id
        fallback.role = f"{zone_id} specialist"
        fallback.latex_hints = "Return valid LaTeX for this zone only."
        log.warning(
            "zone_agent.resolve: no specialist for zone=%s, using generic",
            zone_id,
        )
        return fallback

    def _classify(
        self,
        user_message: str,
        available: List[str],
        *,
        is_initial: bool,
        provider: Optional[str],
        model: Optional[str],
        api_key: Optional[str],
    ) -> List[str]:
        if is_initial:
            # First bio fill: run every available specialist
            return [z for z in available if z in self.agents] or available

        system = (
            "You route resume edit requests to zone specialists. "
            "Available zones: " + ", ".join(available) + ". "
            "Return JSON: {\"zones\": [\"ZONE\", ...], \"reason\": \"...\"}. "
            "Pick only zones that need changes. If unclear, prefer the "
            "smallest relevant set. For a full rewrite/bio paste, include all."
        )
        resp = llm_router.chat(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user_message),
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.1,
            response_format="json",
        )
        data = _extract_json(resp.content)
        raw = data.get("zones") or []
        chosen = []
        available_upper = {z.upper(): z for z in available}
        for z in raw:
            key = str(z).strip().upper()
            if key in available_upper:
                chosen.append(available_upper[key])
            elif key in self.agents and key in available_upper:
                chosen.append(available_upper[key])
        if not chosen:
            # keyword fallback
            msg = user_message.lower()
            mapping = [
                (("experience", "job", "work", "role", "company"), "EXPERIENCE"),
                (("project", "portfolio", "github"), "PROJECTS"),
                (("education", "degree", "university", "college"), "EDUCATION"),
                (("skill", "stack", "technolog"), "SKILLS"),
                (("summary", "about", "profile", "objective"), "SUMMARY"),
                (("name", "email", "phone", "contact", "header", "address"), "HEADER"),
            ]
            for keys, zid in mapping:
                if any(k in msg for k in keys) and zid in available_upper:
                    chosen.append(available_upper[zid])
        if not chosen and available:
            # last resort: summary or first zone
            chosen = [
                available_upper.get("SUMMARY")
                or available_upper.get("EXPERIENCE")
                or available[0]
            ]
        # de-dupe preserve order
        seen = set()
        out = []
        for z in chosen:
            if z not in seen:
                seen.add(z)
                out.append(z)
        return out

    def run(
        self,
        *,
        user_message: str,
        latex_code: str,
        is_initial: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        zone_catalog: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        available = zone_engine.list_zones(latex_code)
        if not available:
            log.error("zone_agent.error: no ZONE markers in template")
            raise ValueError("No ZONE markers found in template")

        targets = self._classify(
            user_message,
            available,
            is_initial=is_initial,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        log.info(
            "zone_agent.step: targets=%s initial=%s available=%s",
            targets,
            is_initial,
            available,
        )
        digest = zone_engine.zone_digest(latex_code)
        current_map = zone_engine.extract_zones(latex_code)

        updates: Dict[str, str] = {}
        summaries: List[str] = []
        trace: List[Dict[str, Any]] = [
            {"tool": "zone_router.classify", "zones": targets}
        ]

        for zone_id in targets:
            agent = self._resolve_agent(zone_id, zone_catalog)

            try:
                content, summary = agent.run(
                    user_message=user_message,
                    current_zone=current_map.get(zone_id, ""),
                    full_digest=digest,
                    is_initial=is_initial,
                    provider=provider,
                    model=model,
                    api_key=api_key,
                )
                updates[zone_id] = content
                summaries.append(f"{zone_id}: {summary}")
                trace.append(
                    {
                        "tool": f"zone_agent.{zone_id}",
                        "status": "ok",
                        "summary": summary,
                    }
                )
            except Exception as e:
                log.exception(
                    "zone_agent.error: %s failed - %s", zone_id, e
                )
                trace.append(
                    {
                        "tool": f"zone_agent.{zone_id}",
                        "status": "error",
                        "error": str(e),
                    }
                )

        if not updates:
            log.error(
                "zone_agent.error: no updates targets=%s", targets
            )
            raise ValueError("No zone agents produced updates")

        new_latex = zone_engine.replace_zones(latex_code, updates)
        reply = (
            "Routed to " + ", ".join(targets) + ". "
            + " ".join(summaries)
        )
        return {
            "latex_code": new_latex,
            "zones_changed": list(updates.keys()),
            "reply": reply,
            "tool_trace": trace,
            "routed_zones": targets,
        }


zone_agent_router = ZoneAgentRouter()
