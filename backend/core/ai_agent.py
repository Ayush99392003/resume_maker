"""Resume agent — zone-aware edits via the multi-provider LLM router."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple  # Any used by ensure_zone_document

from pydantic import BaseModel, Field

try:
    from llm_router import ChatMessage, llm_router
    from core.zones import zone_engine, ZoneError
    from core.zone_agents import zone_agent_router
    from core.chat_router import classify_route, direct_reply
    from core.orchestrator import orchestrator
    from core.latex_to_zones import latex_to_zones
    from core.zone_document import (
        ZoneDocument,
        document_from_session,
        sync_session_from_document,
    )
    from core.logging_setup import get_logger
    from core import config  # noqa: F401
except ImportError:
    from ..llm_router import ChatMessage, llm_router
    from .zones import zone_engine, ZoneError
    from .zone_agents import zone_agent_router
    from .chat_router import classify_route, direct_reply
    from .orchestrator import orchestrator
    from .latex_to_zones import latex_to_zones
    from .zone_document import (
        ZoneDocument,
        document_from_session,
        sync_session_from_document,
    )
    from .logging_setup import get_logger
    from . import config  # noqa: F401

log = get_logger("ai_agent")


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
    route: str = ""
    zone_document: Optional[Dict[str, Any]] = None


def _extract_json(text: str) -> dict:
    """Parse JSON from model output, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e2:
                log.error("agent.error: json extract failed - %s", e2)
                raise
        log.error("agent.error: no json in model output - %s", e)
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
        log.info(
            "agent.step: generate_initial bio_chars=%s template_chars=%s",
            len(bio or ""),
            len(template_latex or ""),
        )
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
        log.info(
            "agent.step: fix_latex_error zones=%s log_chars=%s",
            zones,
            len(error_logs or ""),
        )
        user = f"Zones: {zones}\n\nLogs:\n{error_logs}\n\nBroken LaTeX:\n{broken_latex}"
        try:
            data, _, _ = self._chat_json(
                system,
                user,
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.1,
            )
        except Exception as e:
            log.exception("agent.error: fix_latex_error llm failed - %s", e)
            raise
        if data.get("zones"):
            latex = zone_engine.replace_zones(broken_latex, data["zones"])
            log.info(
                "agent.step: fix via zones %s", list(data["zones"].keys())
            )
            return ResumeUpdate(
                latex_code=latex,
                summary_of_changes=data.get(
                    "summary_of_changes", "Fixed compile errors"
                ),
                is_complete_document=True,
                zones_changed=list(data["zones"].keys()),
            )
        log.info("agent.step: fix via full document rewrite")
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

    def ensure_zone_document(
        self,
        *,
        session: Any = None,
        latex_code: str = "",
        template_latex: str = "",
        source_url: Optional[str] = None,
    ) -> ZoneDocument:
        """Build or load ZoneDocument for a session / latex blob."""
        if session is not None:
            doc = document_from_session(session)
            if doc is not None and doc.zones:
                return doc
        source = latex_code or template_latex
        return latex_to_zones(source, source_url=source_url)

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
        session: Any = None,
        zone_document: Optional[ZoneDocument] = None,
    ) -> AgentTurnResult:
        """Top-level router → direct reply or orchestrator zone agents."""
        working = latex_code or template_latex
        used_provider = provider or self.router.default_provider()
        used_model = model or self.router.default_model()
        log.info(
            "agent.step: run_chat_turn first_fill=%s msg_chars=%s latex_chars=%s",
            is_first_fill,
            len(user_message or ""),
            len(working or ""),
        )

        try:
            doc = zone_document or self.ensure_zone_document(
                session=session,
                latex_code=working,
                template_latex=template_latex,
                source_url=(
                    getattr(session, "source_url", None) if session else None
                ),
            )
        except Exception as e:
            log.exception("agent.error: ensure_zone_document failed - %s", e)
            raise
        catalog = doc.catalog()
        log.info(
            "agent.step: zone doc ready zones=%s catalog_n=%s",
            doc.zone_order,
            len(catalog),
        )

        decision = classify_route(
            user_message,
            catalog=catalog,
            provider=provider,
            model=model,
            api_key=api_key,
            use_llm=not is_first_fill,
        )
        # First bio fill always goes to orchestrator unless pure greeting
        if is_first_fill and decision.route == "direct_reply":
            lower = user_message.strip().lower().rstrip("!.")
            if lower not in {"hi", "hello", "hey", "thanks", "thank you", "thx"}:
                decision.route = "orchestrator"
                decision.reason = "first_fill_override"
                log.info("agent.step: first_fill_override → orchestrator")

        log.info(
            "agent.step: route=%s reason=%s",
            decision.route,
            decision.reason,
        )

        if decision.route == "direct_reply":
            reply = direct_reply(
                user_message, decision, catalog=catalog
            )
            log.info("agent.step: direct_reply chars=%s", len(reply or ""))
            return AgentTurnResult(
                reply=reply,
                latex_code=doc.assemble() if doc.zones else working,
                provider=used_provider,
                model=used_model,
                tool_trace=[
                    {
                        "tool": "chat_router",
                        "route": "direct_reply",
                        "reason": decision.reason,
                    }
                ],
                route="direct_reply",
                zone_document=doc.model_dump(),
            )

        try:
            result = orchestrator.run(
                user_message=user_message,
                document=doc,
                is_first_fill=is_first_fill,
                provider=provider,
                model=model,
                api_key=api_key,
            )
        except Exception as e:
            log.exception("agent.error: orchestrator failed - %s", e)
            raise
        if session is not None:
            sync_session_from_document(session, result.document)

        log.info(
            "agent.step: orchestrator done changed=%s",
            result.zones_changed,
        )
        return AgentTurnResult(
            reply=result.reply,
            latex_code=result.document.assemble(),
            zones_changed=result.zones_changed,
            provider=result.provider or used_provider,
            model=result.model or used_model,
            tool_trace=[
                {
                    "tool": "chat_router",
                    "route": "orchestrator",
                    "reason": decision.reason,
                },
                *result.tool_trace,
            ],
            route="orchestrator",
            zone_document=result.document.model_dump(),
        )


ai_agent = AIAgent()
