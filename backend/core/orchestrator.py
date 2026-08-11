"""Orchestrator: plan intents and dispatch zone agents."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

try:
    from llm_router import ChatMessage, llm_router
    from core.logging_setup import get_logger
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from .logging_setup import get_logger

from .zone_document import ZoneDocument

log = get_logger("orchestrator")


def _pre_escape_backslashes(raw: str) -> str:
    """Escape bare backslashes before JSON parse.

    Prevents ``\\section`` from losing its backslash when Python's
    ``json.loads`` treats ``\\s`` as an invalid escape and drops ``\\``.

    Only ``\\`` NOT already followed by a valid JSON escape character is
    doubled.
    """
    return re.sub(r'\\(?!["\\bfnrtu/])', r"\\\\", raw)


def _sanitize_tex_json(obj: Any) -> Any:
    """De-duplicate double-double backslashes left by over-eager LLMs."""
    if isinstance(obj, str):
        obj = re.sub(r"\\\\\\\\([a-zA-Z])", r"\\\\\\1", obj)
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
    provider: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
) -> OrchPlan:
    catalog = doc.catalog()

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

    if re.search(r"\b(remove zone|delete zone|drop zone|remove )\b", lower):
        target = _match_zone_by_text(doc, message)
        m = re.search(r"zone\s*(\d+)", lower)
        if m:
            target = int(m.group(1))
        if target is None:
            return OrchPlan(
                clarify="Which zone should I remove? Give a zone number or name.",
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

    if re.search(r"\b(reorder|move zone|move )\b", lower):
        # Fall through to LLM for complex move
        pass

    system = (
        "You are the resume zone orchestrator planner. "
        "Zones are numbered; use zone_no from the catalog.\n"
        "Intents: fill, edit, add_zone, remove_zone, reorder, describe, clarify.\n"
        "Return JSON:\n"
        '{"steps":[{"intent":"edit","zone_nos":[2],'
        '"description":"optional for add_zone",'
        '"after_zone_no":null,"at_start":false,'
        '"new_order":[],"swap":[]}],'
        '"clarify":null,"reason":"..."}\n'
        "For biodata dumps use fill on all zones then describe.\n"
        "For pure reorder use reorder with new_order or swap [a,b].\n"
        "If unclear which zone, set clarify and empty steps."
    )
    user = (
        f"Catalog:\n{json.dumps(catalog, indent=2)}\n\n"
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
        f"You edit Zone {zone_no} of a LaTeX resume. "
        f"Zone purpose: {description or 'unknown'}. "
        "Return ONLY this zone's inner LaTeX (no documentclass, no ZONE markers). "
        'JSON: {"content":"...","summary":"one short sentence"}.'
    )
    user = (
        f"Mode: {mode}\n"
        f"Current zone content:\n{current or '(empty)'}\n\n"
        f"Other zones (context only):\n{digest}\n\n"
        f"User request:\n{user_message}"
    )
    data, prov, mod = _llm_json(
        system,
        user,
        provider=provider,
        model=model,
        api_key=api_key,
        temperature=0.35,
    )
    content = (data.get("content") or data.get("latex_code") or "").strip()
    summary = (data.get("summary") or f"Updated zone {zone_no}").strip()
    if not content:
        raise ValueError(f"Empty content for zone {zone_no}")
    return content, summary, prov, mod


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
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> OrchResult:
        doc = document.model_copy(deep=True)
        log.info(
            "orch.step: plan start first_fill=%s zones=%s msg_chars=%s",
            is_first_fill,
            doc.zone_order,
            len(user_message or ""),
        )
        try:
            plan = plan_intents(
                user_message,
                doc,
                is_first_fill=is_first_fill,
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
                digest = doc.digest()
                for n in targets:
                    try:
                        current = doc.zone_inner(n)
                        z = doc.get_zone(n)
                    except KeyError:
                        log.warning("orch.error: %s unknown zone %s", intent, n)
                        continue
                    try:
                        content, summary, prov, mod = _edit_zone_latex(
                            zone_no=n,
                            description=z.description,
                            current=current,
                            digest=digest,
                            user_message=user_message,
                            is_fill=(intent == "fill"),
                            provider=provider,
                            model=model,
                            api_key=api_key,
                        )
                    except Exception as e:
                        log.exception(
                            "orch.error: %s zone %s failed - %s",
                            intent,
                            n,
                            e,
                        )
                        summaries.append(f"Zone {n} {intent} failed: {e}")
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
        return OrchResult(
            reply=reply,
            document=doc,
            zones_changed=changed,
            tool_trace=trace,
            provider=used_provider or provider or "groq",
            model=used_model or model or "",
        )


orchestrator = Orchestrator()
