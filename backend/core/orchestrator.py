"""Orchestrator: plan intents and dispatch zone agents."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

try:
    from llm_router import ChatMessage, llm_router
    from core.logging_setup import get_logger
    from core.zone_agents import (
        zone_agent_router,
        _extract_delimited,
        _pre_escape_backslashes,
        _clean_backslash_typos,
        _escape_raw_latex_chars,
    )
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from .logging_setup import get_logger
    from .zone_agents import (
        zone_agent_router,
        _extract_delimited,
        _pre_escape_backslashes,
        _clean_backslash_typos,
        _escape_raw_latex_chars,
    )

from .zone_document import ZoneDocument

log = get_logger("orchestrator")


def _sanitize_tex_json(obj: Any) -> Any:
    """De-duplicate double backslashes left by over-eager LLMs."""
    if isinstance(obj, str):
        obj = re.sub(r"\r([a-zA-Z])", r"\\r\1", obj)
        obj = re.sub(r"\\{2,}([a-zA-Z])", r"\\\1", obj)
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
    text = _pre_escape_backslashes(text)
    try:
        return _sanitize_tex_json(json.loads(text))
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return _sanitize_tex_json(json.loads(match.group(0)))
        raise


class OrchStep(BaseModel):
    intent: str
    zone_nos: List[int] = Field(default_factory=list)
    description: str = ""
    after_zone_no: Optional[int] = None
    at_start: bool = False
    new_order: List[int] = Field(default_factory=list)
    swap: List[int] = Field(default_factory=list)


class OrchPlan(BaseModel):
    steps: List[OrchStep] = Field(default_factory=list)
    clarify: Optional[str] = None
    reason: str = ""


class OrchResult(BaseModel):
    reply: str
    document: ZoneDocument
    zones_changed: List[str] = Field(default_factory=list)
    resolved_zones: List[str] = Field(default_factory=list)
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)
    provider: str = ""
    model: str = ""


def _llm_json(
    system: str,
    user: str,
    *,
    provider: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
    temperature: float = 0.3,
) -> Tuple[dict, str, str]:
    resp = llm_router.chat(
        [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ],
        provider=provider,
        model=model,
        api_key=api_key,
        temperature=temperature,
        response_format="json",
    )
    return _extract_json(resp.content), resp.provider, resp.model


def _match_zone_by_text(doc: ZoneDocument, text: str) -> Optional[int]:
    lower = text.lower()
    m = re.search(r"zone\s*(\d+)", lower)
    if m:
        n = int(m.group(1))
        if n in doc.zone_map():
            return n
    for z in doc.zones:
        desc = (z.description or "").lower()
        kind = (z.kind or "").lower()
        if desc and desc in lower:
            return z.zone_no
        tokens = [t for t in re.split(r"[^a-z0-9]+", desc) if len(t) > 3]
        if tokens and any(t in lower for t in tokens):
            return z.zone_no
        if "experience" in lower and "experience" in (desc + kind):
            return z.zone_no
        if "education" in lower and "education" in (desc + kind):
            return z.zone_no
        if "skill" in lower and "skill" in (desc + kind):
            return z.zone_no
        if "summary" in lower and "summary" in (desc + kind):
            return z.zone_no
        if ("header" in lower or "contact" in lower) and "header" in (
            desc + kind
        ):
            return z.zone_no
        if "project" in lower and "project" in (desc + kind):
            return z.zone_no
        if "language" in lower and "language" in (desc + kind):
            return z.zone_no
    return None


def plan_intents(
    message: str,
    doc: ZoneDocument,
    *,
    is_first_fill: bool,
    target_zone: Optional[str] = None,
    provider: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
) -> OrchPlan:
    catalog = doc.catalog()

    # Fast-path 1: Explicit user chip selection
    if target_zone and target_zone.strip().lower() not in ("auto", "none", ""):
        tz_clean = target_zone.strip().lower()
        if tz_clean in ("full_rewrite", "full rewrite", "all", "rewrite"):
            return OrchPlan(
                steps=[
                    OrchStep(intent="fill", zone_nos=list(doc.zone_order)),
                    OrchStep(intent="describe", zone_nos=list(doc.zone_order)),
                ],
                reason="user_target_full_rewrite",
            )
        matched_zone = None
        if target_zone.strip().isdigit():
            z_no = int(target_zone.strip())
            if z_no in doc.zone_map():
                matched_zone = z_no
        if matched_zone is None:
            matched_zone = _match_zone_by_text(doc, target_zone)
        if matched_zone is not None:
            log.info(
                "orch.step: fast_path explicit target_zone=%s -> zone=%s",
                target_zone,
                matched_zone,
            )
            return OrchPlan(
                steps=[OrchStep(intent="edit", zone_nos=[matched_zone])],
                reason=f"user_target_{target_zone}",
            )

    def _looks_unfilled() -> bool:
        if not doc.zones:
            return True
        for z in doc.zones:
            inner = doc.zone_inner(z.zone_no)
            if "[[" in inner or inner.strip() in {"", "% empty zone", "% TODO"}:
                return True
            if inner.strip().startswith("%") and len(inner.strip()) < 40:
                return True
        return False

    if is_first_fill or (len(message) >= 180 and _looks_unfilled()):
        return OrchPlan(
            steps=[
                OrchStep(
                    intent="fill",
                    zone_nos=list(doc.zone_order),
                ),
                OrchStep(intent="describe", zone_nos=list(doc.zone_order)),
            ],
            reason="first_fill",
        )

    # Keyword structural ops before LLM
    lower = message.lower()
    if re.search(r"\b(add zone|add a |add an |new zone|insert zone)\b", lower):
        desc_m = re.search(
            r"add (?:a |an |zone )?(?:for )?([a-zA-Z][a-zA-Z0-9 /|-]{2,40})",
            message,
            re.I,
        )
        description = (desc_m.group(1).strip() if desc_m else "Custom section")
        description = re.sub(
            r"\b(under|above|after|before|the|header)\b.*",
            "",
            description,
            flags=re.I,
        ).strip() or "Custom section"
        after = None
        at_start = bool(re.search(r"\b(at top|as header|first)\b", lower))
        if "under the header" in lower or "after header" in lower:
            # first zone often header
            after = doc.zone_order[0] if doc.zone_order else None
        return OrchPlan(
            steps=[
                OrchStep(
                    intent="add_zone",
                    description=description,
                    after_zone_no=after,
                    at_start=at_start,
                )
            ],
            reason="keyword_add",
        )

    # Only treat as zone removal if user explicitly targets a zone/section
    # as a whole. "remove X from Y" = content edit, not zone removal.
    _ZONE_REMOVE_RE = re.compile(
        r"\b(remove zone|delete zone|drop zone"
        r"|remove the .{0,30}(zone|section)"
        r"|delete the .{0,30}(zone|section)"
        r"|drop the .{0,30}(zone|section))\b",
        re.IGNORECASE,
    )
    if _ZONE_REMOVE_RE.search(lower):
        target = _match_zone_by_text(doc, message)
        m = re.search(r"zone\s*(\d+)", lower)
        if m:
            target = int(m.group(1))
        if target is None:
            return OrchPlan(
                clarify=(
                    "Which zone should I remove? "
                    "Give a zone number or name."
                ),
                reason="remove_unclear",
            )
        return OrchPlan(
            steps=[OrchStep(intent="remove_zone", zone_nos=[target])],
            reason="keyword_remove",
        )

    swap_m = re.search(r"swap\s+zone\s*(\d+)\s+(?:and|with)\s+zone\s*(\d+)", lower)
    if swap_m:
        a, b = int(swap_m.group(1)), int(swap_m.group(2))
        return OrchPlan(
            steps=[OrchStep(intent="reorder", swap=[a, b])],
            reason="keyword_swap",
        )

    # Fast-path 2: Unambiguous single-zone keyword match (not a zone structure change)
    target = _match_zone_by_text(doc, message)
    structural_kws = [
        "reorder",
        "swap zone",
        "add zone",
        "add a zone",
        "new zone",
        "insert zone",
        "remove zone",
        "delete zone",
        "drop zone",
        "move zone",
    ]
    if target is not None and not any(kw in lower for kw in structural_kws):
        log.info(
            "orch.step: fast_path unambiguous keyword match -> zone=%s", target
        )
        return OrchPlan(
            steps=[OrchStep(intent="edit", zone_nos=[target])],
            reason="rule_single_zone",
        )

    system = (
        "You are the resume zone orchestrator planner. "
        "Zones are numbered sections of a resume (e.g. Education, "
        "Experience, Projects, Skills).\n"
        "Zones in catalog: use zone_no from the catalog.\n"
        "\n"
        "INTENT RULES — choose carefully:\n"
        "- 'edit': user wants to change, add, remove, or rewrite CONTENT "
        "INSIDE a zone (e.g. 'remove the Legal Knowledge Graph project', "
        "'add TypeScript to skills', 'change my GPA'). "
        "This is the most common intent. When in doubt, use edit.\n"
        "- 'remove_zone': ONLY when the user explicitly says to delete or "
        "remove an entire SECTION/ZONE, using phrases like 'remove the "
        "projects section', 'delete zone 5', 'drop the certifications "
        "section'. NEVER use remove_zone when the user says 'remove X from "
        "Y' — that is an edit.\n"
        "- 'add_zone': user wants a brand-new section added.\n"
        "- 'reorder': user wants to swap or move sections.\n"
        "- 'fill': initial population from bio data.\n"
        "- 'clarify': request is genuinely ambiguous.\n"
        "\n"
        "Return JSON: "
        "{\"steps\":[{\"intent\":\"edit\",\"zone_nos\":[2]}],"
        "\"clarify\":null,\"reason\":\"...\"}\n"
        "If unclear which zone, set clarify and empty steps."
    )
    catalog_lines = [
        f"- Zone {c['zone_no']}: {c['description']} ({c['kind']})"
        for c in catalog
    ]
    user = (
        f"Zones:\n" + "\n".join(catalog_lines) + "\n\n"
        f"Current order: {doc.zone_order}\n\n"
        f"User message:\n{message}"
    )
    try:
        data, _, _ = _llm_json(
            system,
            user,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.1,
        )
        clarify = data.get("clarify")
        steps_raw = data.get("steps") or []
        steps = []
        for s in steps_raw:
            steps.append(
                OrchStep(
                    intent=str(s.get("intent") or "edit"),
                    zone_nos=[int(x) for x in (s.get("zone_nos") or [])],
                    description=str(s.get("description") or ""),
                    after_zone_no=s.get("after_zone_no"),
                    at_start=bool(s.get("at_start")),
                    new_order=[int(x) for x in (s.get("new_order") or [])],
                    swap=[int(x) for x in (s.get("swap") or [])],
                )
            )
        if clarify and not steps:
            return OrchPlan(clarify=str(clarify), reason=str(data.get("reason") or ""))
        if not steps:
            # default: edit matched zone or fill
            target = _match_zone_by_text(doc, message)
            if target is not None:
                steps = [OrchStep(intent="edit", zone_nos=[target])]
            else:
                steps = [
                    OrchStep(intent="fill", zone_nos=list(doc.zone_order)),
                    OrchStep(intent="describe", zone_nos=list(doc.zone_order)),
                ]
        return OrchPlan(
            steps=steps,
            reason=str(data.get("reason") or "llm_plan"),
        )
    except Exception as e:
        log.exception("orch.error: plan_intents llm failed - %s", e)
        target = _match_zone_by_text(doc, message)
        if target is not None:
            log.info("orch.step: fallback_edit zone=%s", target)
            return OrchPlan(
                steps=[OrchStep(intent="edit", zone_nos=[target])],
                reason="fallback_edit",
            )
        log.info("orch.step: fallback_fill zones=%s", doc.zone_order)
        return OrchPlan(
            steps=[
                OrchStep(intent="fill", zone_nos=list(doc.zone_order)),
                OrchStep(intent="describe", zone_nos=list(doc.zone_order)),
            ],
            reason="fallback_fill",
        )


def _edit_zone_latex(
    *,
    zone_no: int,
    description: str,
    current: str,
    digest: str,
    user_message: str,
    is_fill: bool,
    provider: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
) -> Tuple[str, str, str, str]:
    mode = "initial fill from biodata" if is_fill else "targeted edit"
    system = (
        f"You are editing Zone {zone_no} of a LaTeX resume "
        f"({description or 'general'}).\n"
        "\n"
        "OUTPUT FORMAT — follow exactly:\n"
        "<CONTENT>\n"
        "...your raw LaTeX here...\n"
        "</CONTENT>\n"
        "<SUMMARY>one sentence describing what changed</SUMMARY>\n"
        "\n"
        "RULES:\n"
        "1. Single backslash before every LaTeX command: "
        "\\section, \\resumeSubheading, \\textbf — "
        "never double backslashes (\\\\cmd is WRONG).\n"
        "2. Return the complete zone, preserving all \\section{} "
        "headings and wrapper macros "
        "(\\resumeSubHeadingListStart, \\resumeItemListStart, etc.). "
        "Never drop headings or swap custom macros for "
        "\\begin{itemize}.\n"
        "3. Only change what the user asked. Do not invent content.\n"
        "4. No \\documentclass, \\begin{document}, or ZONE markers.\n"
    )
    user = (
        f"Mode: {mode}\n"
        f"Current zone content (preserve all macros verbatim):\n"
        f"{current or '(empty)'}\n\n"
        f"Other zones (read-only context):\n{digest}\n\n"
        f"User request: {user_message}"
    )
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]
    for attempt in range(3):
        resp = llm_router.chat(
            messages,
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.25,
        )
        content, summary = _extract_delimited(resp.content)
        if content:
            if not summary:
                summary = f"Updated zone {zone_no}."
            prov = provider or ""
            mod = model or ""
            return content, summary, prov, mod
        log.warning(
            "_edit_zone_latex attempt %d: no <CONTENT> tag",
            attempt + 1,
        )
        messages.append(
            ChatMessage(role="assistant", content=resp.content)
        )
        messages.append(ChatMessage(
            role="user",
            content=(
                "Missing <CONTENT> block. Wrap your LaTeX in "
                "<CONTENT>...</CONTENT> and add "
                "<SUMMARY>...</SUMMARY>."
            ),
        ))
    raise ValueError(f"Empty content for zone {zone_no}")


def _describe_zones(
    doc: ZoneDocument,
    zone_nos: List[int],
    *,
    provider: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
) -> Tuple[Dict[int, str], str, str]:
    payload = []
    for n in zone_nos:
        try:
            payload.append(
                {"zone_no": n, "latex": doc.zone_inner(n)[:1200]}
            )
        except KeyError:
            continue
    system = (
        "Write one-line descriptions for resume zones. "
        'Return JSON: {"descriptions": {"1": "Contact header", "2": "..."}}.'
    )
    data, prov, mod = _llm_json(
        system,
        json.dumps(payload),
        provider=provider,
        model=model,
        api_key=api_key,
        temperature=0.1,
    )
    raw = data.get("descriptions") or {}
    out: Dict[int, str] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v).strip()
        except (TypeError, ValueError):
            continue
    # heuristic fallback
    for n in zone_nos:
        if n not in out:
            try:
                inner = doc.zone_inner(n)
            except KeyError:
                continue
            m = re.search(
                r"\\(?:section|section\*|cvsection)\*?\{([^}]+)\}", inner
            )
            if m:
                title = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", m.group(1))
                title = re.sub(r"\\[a-zA-Z]+", "", title).strip()
                out[n] = title or f"Zone {n}"
            else:
                out[n] = doc.get_zone(n).description or f"Zone {n}"
    return out, prov, mod


class Orchestrator:
    """Dispatch fill/edit/add/remove/reorder/describe agents."""

    def run(
        self,
        *,
        user_message: str,
        document: ZoneDocument,
        is_first_fill: bool = False,
        target_zone: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> OrchResult:
        doc = document.model_copy(deep=True)
        log.info(
            "orch.step: plan start first_fill=%s target_zone=%s zones=%s msg_chars=%s",
            is_first_fill,
            target_zone,
            doc.zone_order,
            len(user_message or ""),
        )
        try:
            plan = plan_intents(
                user_message,
                doc,
                is_first_fill=is_first_fill,
                target_zone=target_zone,
                provider=provider,
                model=model,
                api_key=api_key,
            )
        except Exception as e:
            log.exception("orch.error: plan_intents failed - %s", e)
            raise
        log.info(
            "orch.step: plan ready reason=%s steps=%s clarify=%s",
            plan.reason,
            [s.intent for s in plan.steps],
            bool(plan.clarify),
        )
        trace: List[Dict[str, Any]] = [
            {"tool": "orchestrator.plan", "plan": plan.model_dump()}
        ]
        used_provider = provider or ""
        used_model = model or ""
        changed: List[str] = []
        summaries: List[str] = []

        if plan.clarify and not plan.steps:
            log.info("orch.step: clarify only — %s", plan.clarify[:120])
            return OrchResult(
                reply=plan.clarify,
                document=doc,
                zones_changed=[],
                resolved_zones=[],
                tool_trace=trace,
                provider=used_provider or "groq",
                model=used_model or "",
            )

        for step in plan.steps:
            intent = step.intent
            log.info(
                "orch.step: run intent=%s zones=%s",
                intent,
                step.zone_nos or step.swap or step.new_order or [],
            )
            if intent == "clarify":
                continue

            if intent == "add_zone":
                rec = doc.add_zone(
                    description=step.description or "Custom section",
                    latex_inner=(
                        f"\\section*{{{step.description or 'Section'}}}\n"
                        "% TODO"
                    ),
                    kind="custom",
                    after_zone_no=step.after_zone_no,
                    at_start=step.at_start,
                )
                changed.append(str(rec.zone_no))
                summaries.append(f"Added zone {rec.zone_no} ({rec.description})")
                trace.append(
                    {
                        "tool": "agent.add_zone",
                        "zone_no": rec.zone_no,
                        "description": rec.description,
                    }
                )
                continue

            if intent == "remove_zone":
                for n in step.zone_nos:
                    try:
                        removed = doc.remove_zone(n)
                        changed.append(str(n))
                        summaries.append(
                            f"Removed zone {n} ({removed.description})"
                        )
                        trace.append(
                            {"tool": "agent.remove_zone", "zone_no": n}
                        )
                    except KeyError:
                        log.warning("orch.error: remove unknown zone %s", n)
                        summaries.append(f"Zone {n} not found")
                continue

            if intent == "reorder":
                try:
                    if len(step.swap) == 2:
                        doc.swap(step.swap[0], step.swap[1])
                        summaries.append(
                            f"Swapped zone {step.swap[0]} and {step.swap[1]}"
                        )
                    elif step.new_order:
                        doc.reorder(step.new_order)
                        summaries.append(
                            f"Reordered zones: {doc.zone_order}"
                        )
                    else:
                        summaries.append("No reorder applied")
                    changed.extend(str(n) for n in doc.zone_order)
                    trace.append(
                        {
                            "tool": "agent.reorder",
                            "order": list(doc.zone_order),
                        }
                    )
                except (KeyError, ValueError) as e:
                    log.error("orch.error: reorder failed - %s", e)
                    summaries.append(f"Reorder failed: {e}")
                continue

            if intent == "describe":
                targets = step.zone_nos or list(doc.zone_order)
                try:
                    descs, prov, mod = _describe_zones(
                        doc,
                        targets,
                        provider=provider,
                        model=model,
                        api_key=api_key,
                    )
                except Exception as e:
                    log.exception("orch.error: describe failed - %s", e)
                    summaries.append(f"Describe failed: {e}")
                    continue
                used_provider, used_model = prov, mod
                for n, d in descs.items():
                    try:
                        doc.get_zone(n).description = d
                    except KeyError:
                        log.warning("orch.error: describe unknown zone %s", n)
                        continue
                summaries.append("Updated zone descriptions")
                trace.append(
                    {"tool": "agent.describe", "descriptions": descs}
                )
                continue

            if intent in ("fill", "edit"):
                targets = step.zone_nos or list(doc.zone_order)
                for n in targets:
                    try:
                        current = doc.zone_inner(n)
                        z = doc.get_zone(n)
                    except KeyError:
                        log.warning(
                            "orch.error: %s unknown zone %s", intent, n
                        )
                        continue

                    # Compact 1-line context for other zones to minimize prompt tokens
                    compact_digest = doc.compact_digest(active_zone_no=n)
                    try:
                        # Primary path: validated ZoneAgent (Pydantic + retry)
                        content, summary = zone_agent_router.run_zone(
                            zone_no=n,
                            zone_description=z.description,
                            zone_kind=z.kind,
                            current_zone=current,
                            full_digest=compact_digest,
                            user_message=user_message,
                            is_initial=(intent == "fill"),
                            provider=provider,
                            model=model,
                            api_key=api_key,
                        )
                        prov = provider or ""
                        mod = model or ""
                    except Exception as agent_err:
                        log.warning(
                            "orch.warning: zone_agent failed zone=%s, "
                            "falling back to _edit_zone_latex - %s",
                            n,
                            agent_err,
                        )
                        try:
                            content, summary, prov, mod = _edit_zone_latex(
                                zone_no=n,
                                description=z.description,
                                current=current,
                                digest=compact_digest,
                                user_message=user_message,
                                is_fill=(intent == "fill"),
                                provider=provider,
                                model=model,
                                api_key=api_key,
                            )
                        except Exception as e:
                            log.exception(
                                "orch.error: %s zone %s fallback failed - %s",
                                intent,
                                n,
                                e,
                            )
                            summaries.append(
                                f"Zone {n} {intent} failed: {e}"
                            )
                            continue
                    used_provider, used_model = prov, mod
                    doc.set_zone_inner(n, content)
                    changed.append(str(n))
                    summaries.append(summary)
                    log.info(
                        "orch.step: %s zone=%s summary=%s",
                        intent,
                        n,
                        summary[:80],
                    )
                    trace.append(
                        {
                            "tool": f"agent.{intent}",
                            "zone_no": n,
                            "summary": summary,
                        }
                    )
                continue

            log.warning("orch.error: unknown intent %s", intent)
            trace.append({"tool": "orchestrator.unknown_intent", "intent": intent})

        reply = " ".join(summaries).strip() or "Done."
        log.info(
            "orch.step: done changed=%s reply_chars=%s",
            changed,
            len(reply),
        )

        resolved_names: List[str] = []
        zmap = doc.zone_map()
        for zid in changed:
            if zid.isdigit() and int(zid) in zmap:
                resolved_names.append(zmap[int(zid)].description or f"Zone {zid}")
            else:
                resolved_names.append(str(zid))

        return OrchResult(
            reply=reply,
            document=doc,
            zones_changed=changed,
            resolved_zones=resolved_names,
            tool_trace=trace,
            provider=used_provider or provider or "groq",
            model=used_model or model or "",
        )


orchestrator = Orchestrator()
