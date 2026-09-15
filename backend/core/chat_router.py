"""Top-level context-aware chat router: direct_reply, structure, or content."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

try:
    from core.logging_setup import get_logger
    from core.zone_agents import _pre_escape_backslashes
    from llm_router import ChatMessage, llm_router
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from .logging_setup import get_logger
    from .zone_agents import _pre_escape_backslashes

log = get_logger("chat_router")

RouteName = Literal["direct_reply", "orchestrator", "structure", "content"]


class RouteDecision(BaseModel):
    route: RouteName
    reason: str = ""
    reply: str | None = None


def _extract_json(text: str) -> dict:
    """Extract and parse JSON object from LLM response string."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = _pre_escape_backslashes(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return {}


def classify_route(
    message: str,
    *,
    catalog: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
    target_zone: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    use_llm: bool = True,
) -> RouteDecision:
    """Classify user request using context history without regex scraping."""
    text = (message or "").strip()

    # Fast-path: Explicit UI zone chip selection bypasses classification
    if target_zone and target_zone.strip().lower() not in (
        "auto",
        "none",
        "",
    ):
        return RouteDecision(
            route="orchestrator",
            reason=f"target_zone_{target_zone.strip()}",
        )

    if not text:
        return RouteDecision(
            route="direct_reply",
            reason="empty",
            reply="Send a greeting, ask a question, or paste biodata to edit.",
        )

    if not use_llm:
        log.info("route.step: no-llm fallback -> direct_reply")
        return RouteDecision(
            route="direct_reply",
            reason="fallback_direct",
            reply=(
                "Tell me what to change on the resume, or paste your biodata "
                "to fill the zones."
            ),
        )

    catalog_txt = ""
    if catalog:
        catalog_txt = "Current Resume Sections:\n" + "\n".join(
            f"- Zone {c.get('zone_no')}: {c.get('description')} "
            f"({c.get('kind', 'section')})"
            for c in catalog
        )

    system = (
        "You are the conversational assistant and intent classifier for a "
        "LaTeX resume editor.\n"
        "You have access to the conversation history and the active resume "
        "sections.\n\n"
        "CLASSIFICATION CATEGORIES:\n"
        "1. 'direct_reply': For normal conversational messages (greetings, "
        "thanks, questions about the resume, asking for advice, explanations, "
        "asking what sections exist, general help, chitchat). When selecting "
        "'direct_reply', you MUST provide a friendly, helpful, and "
        "context-aware answer in the 'reply' field using the chat history.\n"
        "2. 'structure': The user explicitly wants to change the layout "
        "structure: adding a new section, deleting/removing an entire section, "
        "or rearranging/reordering/swapping sections.\n"
        "3. 'content': The user wants to edit, update, add, or delete text or "
        "bullet points INSIDE an existing section, or paste biography/work "
        "history to fill the sections.\n\n"
        "Return JSON format:\n"
        "{\n"
        '  "route": "direct_reply" | "structure" | "content",\n'
        '  "reason": "brief explanation",\n'
        '  "reply": "contextual reply if direct_reply, otherwise null"\n'
        "}"
    )

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=f"{system}\n\n{catalog_txt}".strip())
    ]

    # Include recent chat history for context-awareness (up to 10 turns)
    if history:
        for turn in history[-10:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append(ChatMessage(role=role, content=content))

    messages.append(ChatMessage(role="user", content=message))

    try:
        resp = llm_router.chat(
            messages,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.2,
            response_format="json",
        )
        data = _extract_json(resp.content)
        route = (
            str(data.get("route") or "direct_reply")
            .replace(r"\_", "_")
            .lower()
            .strip()
        )
        if route not in ("direct_reply", "structure", "content"):
            route = "direct_reply"

        decision = RouteDecision(
            route=route,  # type: ignore[arg-type]
            reason=str(data.get("reason") or "llm_decision"),
            reply=data.get("reply"),
        )
        log.info(
            "route.step: llm -> %s reason=%s reply_chars=%s",
            decision.route,
            decision.reason,
            len(decision.reply or ""),
        )
        return decision
    except Exception:
        log.exception("route.error: classify failed")
        return RouteDecision(
            route="direct_reply",
            reason="classify_error",
            reply=(
                "I can help you update your resume. Ask a question, paste "
                "biodata, or tell me which section to update."
            ),
        )


def direct_reply(
    message: str,
    decision: RouteDecision,
    *,
    catalog: list[dict[str, Any]] | None = None,
) -> str:
    """Generate or retrieve direct reply for conversational interactions."""
    if decision.reply:
        return decision.reply
    if catalog:
        lines = ", ".join(
            f"Zone {c['zone_no']} ({c.get('description') or '...'})"
            for c in catalog
        )
        return f"Current sections: {lines}. What would you like to do?"
    return "Paste your biodata or tell me which section to update."
