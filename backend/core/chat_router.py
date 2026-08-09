"""Top-level chat router: direct_reply vs orchestrator."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

try:
    from llm_router import ChatMessage, llm_router
    from core.logging_setup import get_logger
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from .logging_setup import get_logger

log = get_logger("chat_router")

RouteName = Literal["direct_reply", "orchestrator"]


class RouteDecision(BaseModel):
    route: RouteName
    reason: str = ""
    reply: Optional[str] = None


_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hi there",
    "hello there",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks",
    "thank you",
    "thx",
    "ty",
}

_HELP_PAT = re.compile(
    r"\b(how (does|do) (this|it) work|what can you do|help|commands?)\b",
    re.I,
)

_RESUME_HINTS = re.compile(
    r"\b(zone\s*\d+|experience|education|skills?|summary|projects?|"
    r"certificat|language|award|publication|extracurricular|bio|"
    r"resume|cv|reorder|swap|add zone|remove zone|delete zone|"
    r"move|section|compile|latex|bullet|job|company|university)\b",
    re.I,
)


def _rule_route(message: str, *, zones_empty: bool) -> Optional[RouteDecision]:
    text = (message or "").strip()
    if not text:
        return RouteDecision(
            route="direct_reply",
            reason="empty",
            reply="Send a greeting, paste your biodata, or ask to change a zone.",
        )

    lower = text.lower().strip().rstrip("!.")
    if lower in _GREETINGS:
        return RouteDecision(
            route="direct_reply",
            reason="greeting",
            reply=(
                "Hi — paste your biodata to fill the resume, or tell me which "
                "zone to change (e.g. “make zone 2 shorter” / “add projects”)."
            ),
        )

    if _HELP_PAT.search(text) and not _RESUME_HINTS.search(text):
        return RouteDecision(
            route="direct_reply",
            reason="help",
            reply=(
                "I edit numbered resume zones. Paste biodata to fill them, "
                "or ask to add/remove/reorder/edit a zone. Header and footer "
                "of the LaTeX stay fixed."
            ),
        )

    # Long paste / biodata → orchestrator
    if len(text) >= 220 or text.count("\n") >= 4:
        return RouteDecision(route="orchestrator", reason="long_biodata")

    if _RESUME_HINTS.search(text):
        return RouteDecision(route="orchestrator", reason="resume_keywords")

    if zones_empty and len(text) >= 40:
        return RouteDecision(route="orchestrator", reason="fill_sparse")

    return None


def classify_route(
    message: str,
    *,
    catalog: Optional[List[Dict[str, Any]]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    use_llm: bool = True,
) -> RouteDecision:
    """Decide direct_reply vs orchestrator."""
    zones_empty = not catalog or all(
        not (c.get("description") or "").strip() for c in (catalog or [])
    )
    ruled = _rule_route(message, zones_empty=zones_empty)
    if ruled is not None:
        log.info(
            "route.step: rule → %s reason=%s msg_chars=%s",
            ruled.route,
            ruled.reason,
            len(message or ""),
        )
        return ruled

    if not use_llm:
        log.info("route.step: no-llm fallback → direct_reply")
        return RouteDecision(
            route="direct_reply",
            reason="fallback_direct",
            reply=(
                "Tell me what to change on the resume, or paste your biodata "
                "to fill the zones."
            ),
        )

    system = (
        "You classify chat messages for a LaTeX resume editor.\n"
        "Return JSON: {\"route\": \"direct_reply\"|\"orchestrator\", "
        "\"reason\": \"...\", \"reply\": \"optional short reply if direct\"}.\n"
        "- direct_reply: greetings, thanks, meta/help, chitchat, no resume change\n"
        "- orchestrator: biodata, zone edits, add/remove/reorder sections, "
        "compile fixes, content changes\n"
        "If direct_reply, include a brief helpful reply."
    )
    catalog_txt = ""
    if catalog:
        catalog_txt = "Zones: " + "; ".join(
            f"{c.get('zone_no')}:{c.get('description')}" for c in catalog
        )
    try:
        import json

        resp = llm_router.chat(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(
                    role="user",
                    content=f"{catalog_txt}\n\nMessage:\n{message}",
                ),
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.0,
            response_format="json",
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            log.warning("route.step: json repair after decode error - %s", e)
            m = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        if not isinstance(data, dict):
            log.error("route.error: classify response not a dict")
            raise ValueError("not a dict")
        route = data.get("route", "direct_reply")
        if route not in ("direct_reply", "orchestrator"):
            route = "direct_reply"
        decision = RouteDecision(
            route=route,
            reason=str(data.get("reason") or "llm"),
            reply=data.get("reply"),
        )
        log.info(
            "route.step: llm → %s reason=%s",
            decision.route,
            decision.reason,
        )
        return decision
    except Exception as e:
        log.exception("route.error: classify failed - %s", e)
        return RouteDecision(
            route="direct_reply",
            reason="classify_error",
            reply=(
                "I can fill or edit resume zones. Paste biodata or say what "
                "to change."
            ),
        )


def direct_reply(
    message: str,
    decision: RouteDecision,
    *,
    catalog: Optional[List[Dict[str, Any]]] = None,
) -> str:
    if decision.reply:
        return decision.reply
    if catalog:
        lines = ", ".join(
            f"Zone {c['zone_no']} ({c.get('description') or '…'})"
            for c in catalog
        )
        return f"Current zones: {lines}. What should I change?"
    return "Paste your biodata or tell me which zone to update."
