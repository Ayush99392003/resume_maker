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
    from core.line_indexer import build_debug_payload
    from core.delta_patcher import patch_latex, apply_zone_delta
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
    from .line_indexer import build_debug_payload
    from .delta_patcher import patch_latex, apply_zone_delta
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
    resolved_zones: List[str] = Field(default_factory=list)
    proposals: Optional[List[ProposalVariant]] = None
    provider: str
    model: str
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)
    route: str = ""
    zone_document: Optional[Dict[str, Any]] = None


def _sanitize_tex_json(obj: Any) -> Any:
    """Restore TeX control sequences mangled by JSON decode.

    JSON decoding converts ``\r`` to a carriage-return character, which
    strips the ``r`` from macros like ``\resumeItem``.  We only repair
    the specific known patterns rather than blindly escaping all control
    characters, which would break ``\textbf``, ``\textit``, ``\texttt`` etc.

    Specifically fixed:
    - ``\r`` (CR) followed by a letter  → ``\\r`` (restores ``\resume*``)
    - ``\\\\`` (double-double-backslash) → ``\\`` (de-duplicates over-escaped)
    """
    if isinstance(obj, str):
        # Fix CR + letter → \r + letter  (restores \resumeItem etc.)
        obj = re.sub(r"\r([a-zA-Z])", r"\\r\1", obj)
        # De-duplicate \\\\cmd → \\cmd (over-escaped by some LLMs)
        obj = re.sub(r"\\\\\\\\([a-zA-Z])", r"\\\\\1", obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_tex_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_tex_json(x) for x in obj]
    return obj


def _extract_json(text: str) -> dict:
    """Parse JSON from model output, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return _sanitize_tex_json(json.loads(text))
    except json.JSONDecodeError as e:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return _sanitize_tex_json(json.loads(match.group(0)))
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
        """Repair a broken LaTeX document using a line-indexed delta patch.

        Strategy
        --------
        1. Build a minimal line-indexed JSON debug payload from the broken
           zone so the fixer agent sees only the relevant context lines.
        2. The agent returns a compact delta specifying only changed lines/
           ranges (``fixed_lines``) or a corrected zone fragment
           (``fixed_zone_id`` + ``fixed_zone_content``).
        3. Apply the delta surgically via :func:`patch_latex` or
           :func:`apply_zone_delta`, avoiding any full-document rewrites.
        4. Fall back to zone-level or full-document replacement if the agent
           returns the legacy response shape.

        Args:
            broken_latex: Full LaTeX source that failed to compile.
            error_logs: Raw Tectonic error log string.
            provider: LLM provider override.
            model: Model name override.
            api_key: API key override.

        Returns:
            :class:`ResumeUpdate` with the patched LaTeX and a summary.
        """
        zones = zone_engine.list_zones(broken_latex)
        debug_payload = build_debug_payload(broken_latex, error_logs or "")
        log.info(
            "agent.step: fix_latex_error zones=%s target_zone=%s "
            "context_lines=%s log_chars=%s",
            zones,
            debug_payload.get("target_zone"),
            len(debug_payload.get("lines", {})),
            len(error_logs or ""),
        )

        system = (
            "You are a LaTeX repair specialist.  You receive a JSON debug "
            "payload with:\n"
            "  - error_log: the Tectonic compilation error\n"
            "  - target_zone: zone id where the error occurred\n"
            "  - line_range: [start, end] of that zone\n"
            "  - lines: {\"lineno\": \"content\"} — ONLY the relevant lines\n"
            "\n"
            "Return JSON with EXACTLY one of these shapes:\n"
            "\n"
            "Shape A — line delta (preferred, most precise):\n"
            "{\n"
            "  \"fixed_zone_id\": \"EXPERIENCE\",\n"
            "  \"fixed_lines\": {\n"
            "    \"163-166\": \"\\\\begin{itemize}\\n"
            "\\\\item Bullet\\n\\\\end{itemize}\"\n"
            "  },\n"
            "  \"summary_of_changes\": \"brief description\"\n"
            "}\n"
            "\n"
            "Shape B — whole-zone content replacement:\n"
            "{\n"
            "  \"fixed_zone_id\": \"EXPERIENCE\",\n"
            "  \"fixed_zone_content\": \"corrected zone inner text\",\n"
            "  \"summary_of_changes\": \"brief description\"\n"
            "}\n"
            "\n"
            "Shape C — legacy zone map (fallback only):\n"
            "{\n"
            "  \"zones\": {\"ZONE_ID\": \"fixed fragment\"},\n"
            "  \"summary_of_changes\": \"...\"\n"
            "}\n"
            "\n"
            "Rules:\n"
            "- NEVER output a full LaTeX document unless absolutely necessary.\n"
            "- CRITICAL: enclose all \\item lines in "
            "\\begin{itemize}...\\end{itemize}.\n"
            "- Preserve all % ZONE:N:START / END markers exactly.\n"
            "- Only fix the lines shown; do not invent new content."
        )

        import json as _json
        user = _json.dumps(debug_payload, ensure_ascii=False)

        try:
            data, _, _ = self._chat_json(
                system,
                user,
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.05,
            )
        except Exception as exc:
            log.exception("agent.error: fix_latex_error llm failed - %s", exc)
            raise

        summary = data.get("summary_of_changes", "Fixed compile errors")

        # ── Shape A: line delta ───────────────────────────────────────────
        fixed_lines = data.get("fixed_lines")
        if fixed_lines and isinstance(fixed_lines, dict):
            patched = patch_latex(broken_latex, fixed_lines)
            changed_zone = data.get("fixed_zone_id", "")
            log.info(
                "agent.step: fix via line-delta zone=%s patches=%s",
                changed_zone,
                len(fixed_lines),
            )
            return ResumeUpdate(
                latex_code=patched,
                summary_of_changes=summary,
                is_complete_document=True,
                zones_changed=[changed_zone] if changed_zone else [],
            )

        # ── Shape B: whole-zone content replacement ───────────────────────
        fixed_zone_content = data.get("fixed_zone_content")
        fixed_zone_id = data.get("fixed_zone_id")
        if fixed_zone_content is not None and fixed_zone_id:
            patched = apply_zone_delta(
                broken_latex, fixed_zone_id, fixed_zone_content
            )
            log.info(
                "agent.step: fix via zone-content replacement zone=%s",
                fixed_zone_id,
            )
            return ResumeUpdate(
                latex_code=patched,
                summary_of_changes=summary,
                is_complete_document=True,
                zones_changed=[fixed_zone_id],
            )

        # ── Shape C: legacy zone map (backward compat) ────────────────────
        if data.get("zones"):
            latex = zone_engine.replace_zones(broken_latex, data["zones"])
            log.info(
                "agent.step: fix via legacy zone-map %s",
                list(data["zones"].keys()),
            )
            return ResumeUpdate(
                latex_code=latex,
                summary_of_changes=summary,
                is_complete_document=True,
                zones_changed=list(data["zones"].keys()),
            )

        # ── Last resort: full document rewrite ────────────────────────────
        log.info("agent.step: fix via full document rewrite (last resort)")
        return ResumeUpdate(
            latex_code=data.get("latex_code", broken_latex),
            summary_of_changes=summary,
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
        target_zone: Optional[str] = None,
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
            "agent.step: run_chat_turn first_fill=%s target_zone=%s msg_chars=%s latex_chars=%s",
            is_first_fill,
            target_zone,
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
            target_zone=target_zone,
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
                target_zone=target_zone,
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
            "agent.step: orchestrator done changed=%s resolved=%s",
            result.zones_changed,
            result.resolved_zones,
        )
        return AgentTurnResult(
            reply=result.reply,
            latex_code=result.document.assemble(),
            zones_changed=result.zones_changed,
            resolved_zones=result.resolved_zones,
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
