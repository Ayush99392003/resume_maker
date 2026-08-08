"""Resume agent — zone-aware edits via the multi-provider LLM router."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

try:
    from llm_router import ChatMessage, llm_router
    from core.zones import zone_engine, ZoneError
    from core.zone_agents import zone_agent_router
    from core import config  # noqa: F401
except ImportError:
    from ..llm_router import ChatMessage, llm_router
    from .zones import zone_engine, ZoneError
    from .zone_agents import zone_agent_router
    from . import config  # noqa: F401


class ResumeUpdate(BaseModel):
    latex_code: str = Field(..., description="Full LaTeX document.")
    summary_of_changes: str = Field(..., description="Brief explanation.")
    is_complete_document: bool = Field(True, description="True if full doc.")
    zones_changed: List[str] = Field(default_factory=list)


class ProposalVariant(BaseModel):
    id: str
    intent: str
    latex_code: str
    summary: str
    zone_id: Optional[str] = None


class RefinementProposal(BaseModel):
    original_context: str
    proposals: List[ProposalVariant]


class AgentTurnResult(BaseModel):
    reply: str
    latex_code: str
    zones_changed: List[str] = Field(default_factory=list)
    proposals: Optional[List[ProposalVariant]] = None
    provider: str
    model: str
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)


def _extract_json(text: str) -> dict:
    """Parse JSON from model output, tolerating markdown fences."""
    text = text.strip()
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


class AIAgent:
    """Zone-scoped resume agent backed by LLMRouter."""

    HISTORY_WINDOW = 20

    def __init__(self):
        self.router = llm_router

    def _chat_json(
        self,
        system: str,
        user: str,
        *,
        provider: Optional[str],
        model: Optional[str],
        api_key: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.3,
    ) -> Tuple[dict, str, str]:
        messages: List[ChatMessage] = [ChatMessage(role="system", content=system)]
        if history:
            for h in history[-self.HISTORY_WINDOW :]:
                role = h.get("role", "user")
                if role not in ("user", "assistant"):
                    continue
                messages.append(
                    ChatMessage(role=role, content=h.get("content", ""))
                )
        messages.append(ChatMessage(role="user", content=user))
        resp = self.router.chat(
            messages,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=temperature,
            response_format="json",
        )
        data = _extract_json(resp.content)
        return data, resp.provider, resp.model

    def generate_initial_resume(
        self,
        bio: str,
        template_latex: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> ResumeUpdate:
        """Fill resume by routing the bio to every zone specialist."""
        result = zone_agent_router.run(
            user_message=bio,
            latex_code=template_latex,
            is_initial=True,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        return ResumeUpdate(
            latex_code=result["latex_code"],
            summary_of_changes=result["reply"],
            is_complete_document=True,
            zones_changed=result["zones_changed"],
        )

    def generate_edit_proposals(
        self,
        current_latex: str,
        command: str,
        section_name: Optional[str] = None,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> RefinementProposal:
        zones = zone_engine.list_zones(current_latex)
        target = section_name
        if target and target.upper() in [z.upper() for z in zones]:
            for z in zones:
                if z.upper() == target.upper():
                    target = z
                    break
        elif target and target not in zones:
            # Map section title to zone if possible
            for z in zones:
                if z.lower() == target.lower().replace(" ", "_"):
                    target = z
                    break

        system = (
            "Generate 3 distinct zone-level LaTeX variations for the edit. "
            "Return JSON: {\"original_context\": \"...\", \"proposals\": ["
            "{\"id\": \"1\", \"intent\": \"Standard\", \"zone_id\": \"NAME\", "
            "\"latex_code\": \"zone fragment only\", \"summary\": \"...\"}, "
            "...]} Intents: Standard, Creative, Concise. "
            "Do not return a full document — only the zone fragment."
        )
        zone_blob = ""
        if target and target in zone_engine.extract_zones(current_latex):
            zone_blob = zone_engine.get_zone(current_latex, target)
        else:
            zone_blob = zone_engine.zone_digest(current_latex)

        user = (
            f"Target zone/section: {target or 'infer best zone'}\n"
            f"Available zones: {zones}\n"
            f"Current zone content:\n{zone_blob}\n"
            f"Command: {command}"
        )
        data, _, _ = self._chat_json(
            system,
            user,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.5,
        )
        proposals = []
        for p in data.get("proposals", []):
            proposals.append(
                ProposalVariant(
                    id=str(p.get("id") or uuid.uuid4()),
                    intent=p.get("intent", "Variant"),
                    latex_code=p.get("latex_code", ""),
                    summary=p.get("summary", ""),
                    zone_id=p.get("zone_id") or target,
                )
            )
        return RefinementProposal(
            original_context=data.get("original_context", command),
            proposals=proposals,
        )

    def fix_latex_error(
        self,
        broken_latex: str,
        error_logs: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> ResumeUpdate:
        zones = zone_engine.list_zones(broken_latex)
        system = (
            "Repair broken LaTeX. Prefer fixing only the affected zone(s). "
            "Return JSON either "
            '{"zones": {"ZONE": "fixed fragment"}, "summary_of_changes": "..."} '
            'or {"latex_code": "FULL fixed document", "summary_of_changes": "..."}. '
            "Preserve all ZONE markers exactly."
        )
        user = f"Zones: {zones}\n\nLogs:\n{error_logs}\n\nBroken LaTeX:\n{broken_latex}"
        data, _, _ = self._chat_json(
            system,
            user,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.1,
        )
        if data.get("zones"):
            latex = zone_engine.replace_zones(broken_latex, data["zones"])
            return ResumeUpdate(
                latex_code=latex,
                summary_of_changes=data.get(
                    "summary_of_changes", "Fixed compile errors"
                ),
                is_complete_document=True,
                zones_changed=list(data["zones"].keys()),
            )
        return ResumeUpdate(
            latex_code=data.get("latex_code", broken_latex),
            summary_of_changes=data.get(
                "summary_of_changes", "Fixed compile errors"
            ),
            is_complete_document=True,
            zones_changed=[],
        )

    def squeeze_layout(
        self,
        latex_code: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> ResumeUpdate:
        system = (
            "Optimize LaTeX layout to fit more content (margins, spacing). "
            "Preserve ZONE markers and content meaning. Return JSON: "
            '{"latex_code": "FULL document", "summary_of_changes": "..."}.'
        )
        user = f"LaTeX Code:\n{latex_code}"
        data, _, _ = self._chat_json(
            system,
            user,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.2,
        )
        return ResumeUpdate(
            latex_code=data.get("latex_code", latex_code),
            summary_of_changes=data.get(
                "summary_of_changes", "Squeezed layout"
            ),
            is_complete_document=True,
        )

    def run_chat_turn(
        self,
        *,
        user_message: str,
        latex_code: str,
        template_latex: str,
        history: List[Dict[str, Any]],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        is_first_fill: bool = False,
    ) -> AgentTurnResult:
        """Route the user message to one or more zone specialists."""
        working = latex_code or template_latex
        used_provider = provider or self.router.default_provider()
        used_model = model or self.router.default_model()

        # Lightweight reply-only intents (no zone edit)
        lower = user_message.strip().lower()
        if not is_first_fill and lower in {"hi", "hello", "hey", "thanks", "thank you"}:
            return AgentTurnResult(
                reply="Hi — tell me what to change (experience, skills, summary, …).",
                latex_code=working,
                provider=used_provider,
                model=used_model,
                tool_trace=[{"tool": "zone_router.skip", "reason": "greeting"}],
            )

        result = zone_agent_router.run(
            user_message=user_message,
            latex_code=working if not is_first_fill else template_latex,
            is_initial=is_first_fill or not (latex_code or "").strip(),
            provider=provider,
            model=model,
            api_key=api_key,
        )
        return AgentTurnResult(
            reply=result["reply"],
            latex_code=result["latex_code"],
            zones_changed=result["zones_changed"],
            provider=used_provider,
            model=used_model,
            tool_trace=result.get("tool_trace") or [],
        )


ai_agent = AIAgent()
