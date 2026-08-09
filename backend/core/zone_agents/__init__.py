"""Per-zone resume specialists and a router that dispatches to them."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from llm_router import ChatMessage, llm_router
    from core.zones import zone_engine
    from core.logging_setup import get_logger
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from ..zones import zone_engine
    from ..logging_setup import get_logger

log = get_logger("zone_agents")


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


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
    ) -> Tuple[str, str]:
        """Return (new_zone_latex, short_summary)."""
        mode = "initial fill from bio" if is_initial else "targeted edit"
        system = (
            f"You are the {self.role} for a LaTeX resume. "
            f"You ONLY edit the {self.zone_id} zone. "
            f"Never return a full document or zone markers. "
            f"Return JSON: {{\"content\": \"latex fragment for this zone only\", "
            f"\"summary\": \"one short sentence\"}}.\n\n"
            f"LaTeX guidance:\n{self.latex_hints}"
        )
        user = (
            f"Mode: {mode}\n"
            f"Zone: {self.zone_id}\n"
            f"Current zone content:\n{current_zone or '(empty)'}\n\n"
            f"Other zones (context only, do not rewrite):\n{full_digest}\n\n"
            f"User request:\n{user_message}"
        )
        resp = llm_router.chat(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.35,
            response_format="json",
        )
        data = _extract_json(resp.content)
        content = (data.get("content") or data.get("latex_code") or "").strip()
        summary = (data.get("summary") or f"Updated {self.zone_id}").strip()
        if not content:
            raise ValueError(f"{self.zone_id} agent returned empty content")
        return content, summary


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


ZONE_AGENT_CLASSES = {
    "HEADER": HeaderAgent,
    "SUMMARY": SummaryAgent,
    "EXPERIENCE": ExperienceAgent,
    "EDUCATION": EducationAgent,
    "SKILLS": SkillsAgent,
}


class ZoneAgentRouter:
    """Classifies which zones to touch, then calls the matching zone agents."""

    def __init__(self):
        self.agents: Dict[str, ZoneAgent] = {
            zid: cls() for zid, cls in ZONE_AGENT_CLASSES.items()
        }

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
            agent = self.agents.get(zone_id.upper()) or self.agents.get(zone_id)
            if not agent:
                # Generic fallback for unknown custom zones
                agent = ZoneAgent()
                agent.zone_id = zone_id
                agent.role = f"{zone_id} specialist"
                agent.latex_hints = "Return valid LaTeX for this zone only."

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
