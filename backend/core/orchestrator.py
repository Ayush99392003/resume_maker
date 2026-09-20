"""Orchestrator: plan intents and dispatch zone agents."""

from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any

# Regex to detect transient provider-level failures that make retrying
# pointless: rate limits, quota exhaustion, 503/overload, bad gateway.
_PROVIDER_DOWN_RE = re.compile(
    r"rate.?limit|quota|overload|503|502|service.unavailable|too.many.requests",
    re.IGNORECASE,
)

from pydantic import BaseModel, Field

try:
    import core.research_agents
    from core.latex_sanitizer import safe_extract_json
    from core.logging_setup import get_logger
    from core.style_agent import style_agent
    from core.tools import (
        CONTENT_TOOLS_DESCRIPTION,
        STRUCTURE_TOOLS_DESCRIPTION,
        STYLE_TOOLS_DESCRIPTION,
    )
    from core.zone_agents import (
        _clean_backslash_typos,
        _escape_raw_latex_chars,
        _extract_delimited,
        _pre_escape_backslashes,
        zone_agent_router,
    )
    from llm_router import ChatMessage, llm_router
except ImportError:
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from .latex_sanitizer import safe_extract_json
    from .logging_setup import get_logger
    from .style_agent import style_agent
    from .tools import (
        CONTENT_TOOLS_DESCRIPTION,
        STRUCTURE_TOOLS_DESCRIPTION,
        STYLE_TOOLS_DESCRIPTION,
    )
    from .zone_agents import (
        _extract_delimited,
        zone_agent_router,
    )

from .zone_document import ZoneDocument

log = get_logger("orchestrator")

_extract_json = safe_extract_json


class OrchStep(BaseModel):
    intent: str
    zone_nos: list[int] = Field(default_factory=list)
    description: str = ""
    after_zone_no: int | None = None
    at_start: bool = False
    new_order: list[int] = Field(default_factory=list)
    swap: list[int] = Field(default_factory=list)


class OrchPlan(BaseModel):
    steps: list[OrchStep] = Field(default_factory=list)
    clarify: str | None = None
    reason: str = ""


class OrchResult(BaseModel):
    reply: str
    document: ZoneDocument
    zones_changed: list[str] = Field(default_factory=list)
    resolved_zones: list[str] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    provider: str = ""
    model: str = ""


def _llm_json(
    system: str,
    user: str,
    *,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    temperature: float = 0.3,
) -> tuple[dict, str, str]:
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


def _match_zone_by_text(doc: ZoneDocument, text: str) -> int | None:
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
    target_zone: str | None = None,
    category: str | None = None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
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
        empty_count = 0
        for z in doc.zones:
            inner = doc.zone_inner(z.zone_no)
            if "[[" in inner or inner.strip() in {
                "",
                "% empty zone",
                "% TODO",
            } or (
                inner.strip().startswith("%") and len(inner.strip()) < 40
            ):
                empty_count += 1
        threshold = max(1, round(len(doc.zones) * 0.6))
        return empty_count >= threshold

    if is_first_fill or (len(message) >= 250 and _looks_unfilled()):
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

    # --- Tool-Based Tree Routing (Zero Regex Scraping) ---
    catalog_lines = [
        f"- Zone {c['zone_no']}: {c['description']} ({c['kind']})"
        for c in catalog
    ]
    catalog_txt = "\n".join(catalog_lines)

    try:
        if category == "structure":
            # Structure Branch: Only load structure tools and minimal catalog
            system = (
                "You are the resume structure planner. Select the structural "
                "tool matching the user's layout request.\n\n"
                f"{STRUCTURE_TOOLS_DESCRIPTION}"
            )
            user_prompt = (
                f"Current Zones:\n{catalog_txt}\n"
                f"Current Order: {doc.zone_order}\n\n"
                f"User request:\n{message}"
            )
            data, _, _ = _llm_json(
                system,
                user_prompt,
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.1,
            )
            tool = (
                str(data.get("tool") or "")
                .replace(r"\_", "_")
                .strip()
                .lower()
            )
            raw_args = data.get("args") or {}
            args = (
                {
                    str(k).replace(r"\_", "_"): v
                    for k, v in raw_args.items()
                }
                if isinstance(raw_args, dict)
                else {}
            )
            reason = str(data.get("reason") or "structure_tool")

            if tool == "add_zone":
                title = str(args.get("title") or "Custom section")
                after = args.get("after_zone_no")
                at_start = bool(args.get("at_start"))
                return OrchPlan(
                    steps=[
                        OrchStep(
                            intent="add_zone",
                            description=title,
                            after_zone_no=after,
                            at_start=at_start,
                        )
                    ],
                    reason=reason,
                )
            elif tool == "remove_zone":
                zone_nos = [int(x) for x in (args.get("zone_nos") or [])]
                if not zone_nos:
                    return OrchPlan(
                        clarify="Which zone should I remove?",
                        reason="remove_unclear",
                    )
                return OrchPlan(
                    steps=[OrchStep(intent="remove_zone", zone_nos=zone_nos)],
                    reason=reason,
                )
            elif tool == "reorder_zones":
                swap = [int(x) for x in (args.get("swap") or [])]
                new_order = [int(x) for x in (args.get("new_order") or [])]
                return OrchPlan(
                    steps=[
                        OrchStep(intent="reorder", swap=swap, new_order=new_order)
                    ],
                    reason=reason,
                )

        elif category == "content":
            # Content Branch: Target specific zone content or bio fill
            system = (
                "You are the resume content planner. Select the content tool "
                "and target zone matching the user's request.\n\n"
                f"{CONTENT_TOOLS_DESCRIPTION}"
            )
            user_prompt = (
                f"Current Zones:\n{catalog_txt}\n\n"
                f"User request:\n{message}"
            )
            data, _, _ = _llm_json(
                system,
                user_prompt,
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.1,
            )
            tool = (
                str(data.get("tool") or "")
                .replace(r"\_", "_")
                .strip()
                .lower()
            )
            raw_args = data.get("args") or {}
            args = (
                {
                    str(k).replace(r"\_", "_"): v
                    for k, v in raw_args.items()
                }
                if isinstance(raw_args, dict)
                else {}
            )
            reason = str(data.get("reason") or "content_tool")

            if tool == "edit_zone_content":
                z_no = args.get("zone_no")
                if z_no is not None and int(z_no) in doc.zone_map():
                    return OrchPlan(
                        steps=[OrchStep(intent="edit", zone_nos=[int(z_no)])],
                        reason="content_tool",
                    )
            elif tool == "fill_resume":
                z_nos = [
                    int(x) for x in (args.get("zone_nos") or doc.zone_order)
                ]
                return OrchPlan(
                    steps=[
                        OrchStep(intent="fill", zone_nos=z_nos),
                        OrchStep(intent="describe", zone_nos=z_nos),
                    ],
                    reason="content_tool",
                )

        elif category == "style":
            return OrchPlan(
                steps=[OrchStep(intent="style")],
                reason="style_branch",
            )

        else:
            # Combined tool schema fallback
            system = (
                "You are the resume orchestrator planner. Select the "
                "appropriate tool for the user's request:\n\n"
                f"{STRUCTURE_TOOLS_DESCRIPTION}\n\n"
                f"{CONTENT_TOOLS_DESCRIPTION}\n\n"
                f"{STYLE_TOOLS_DESCRIPTION}"
            )
            user_prompt = (
                f"Current Zones:\n{catalog_txt}\n"
                f"Current Order: {doc.zone_order}\n\n"
                f"User request:\n{message}"
            )
            data, _, _ = _llm_json(
                system,
                user_prompt,
                provider=provider,
                model=model,
                api_key=api_key,
                temperature=0.1,
            )
            tool = (
                str(data.get("tool") or "")
                .replace(r"\_", "_")
                .strip()
                .lower()
            )
            raw_args = data.get("args") or {}
            args = (
                {
                    str(k).replace(r"\_", "_"): v
                    for k, v in raw_args.items()
                }
                if isinstance(raw_args, dict)
                else {}
            )

            if tool == "add_zone":
                return OrchPlan(
                    steps=[
                        OrchStep(
                            intent="add_zone",
                            description=str(
                                args.get("title") or "Custom section"
                            ),
                            after_zone_no=args.get("after_zone_no"),
                            at_start=bool(args.get("at_start")),
                        )
                    ],
                    reason="structure_tool",
                )
            elif tool == "remove_zone":
                zone_nos = [int(x) for x in (args.get("zone_nos") or [])]
                if not zone_nos:
                    return OrchPlan(
                        clarify="Which zone should I remove?",
                        reason="remove_unclear",
                    )
                return OrchPlan(
                    steps=[OrchStep(intent="remove_zone", zone_nos=zone_nos)],
                    reason="structure_tool",
                )
            elif tool == "reorder_zones":
                return OrchPlan(
                    steps=[
                        OrchStep(
                            intent="reorder",
                            swap=[int(x) for x in (args.get("swap") or [])],
                            new_order=[
                                int(x) for x in (args.get("new_order") or [])
                            ],
                        )
                    ],
                    reason="structure_tool",
                )
            elif tool == "edit_zone_content":
                z_no = args.get("zone_no")
                if z_no is not None and int(z_no) in doc.zone_map():
                    return OrchPlan(
                        steps=[OrchStep(intent="edit", zone_nos=[int(z_no)])],
                        reason="content_tool",
                    )
            elif tool == "fill_resume":
                z_nos = [
                    int(x) for x in (args.get("zone_nos") or doc.zone_order)
                ]
                return OrchPlan(
                    steps=[
                        OrchStep(intent="fill", zone_nos=z_nos),
                        OrchStep(intent="describe", zone_nos=z_nos),
                    ],
                    reason="content_tool",
                )
            elif tool == "update_document_style":
                return OrchPlan(
                    steps=[OrchStep(intent="style")],
                    reason="style_branch",
                )
    except Exception:
        log.exception("orch.error: plan_intents tool router failed")

    # Heuristic style matching
    style_keywords = (
        "font", "margins", "margin", "color", "theme", "twocolumn",
        "two column", "onecolumn", "one column", "10pt", "11pt", "12pt",
        "palatino", "helvetica", "times new roman", "lmodern"
    )
    if any(k in message.lower() for k in style_keywords) and not any(
        z in message.lower()
        for z in ("experience", "education", "skill", "summary", "project")
    ):
        return OrchPlan(
            steps=[OrchStep(intent="style")],
            reason="heuristic_style",
        )

    # Fallback to text match if tool call failed or was unrecognized
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
    provider: str | None,
    model: str | None,
    api_key: str | None,
) -> tuple[str, str, str, str]:
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
    zone_nos: list[int],
    *,
    provider: str | None,
    model: str | None,
    api_key: str | None,
) -> tuple[dict[int, str], str, str]:
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
    out: dict[int, str] = {}
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
        target_zone: str | None = None,
        category: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> OrchResult:
        doc = document.model_copy(deep=True)
        log.info(
            "orch.step: plan start first_fill=%s target_zone=%s category=%s zones=%s msg_chars=%s",
            is_first_fill,
            target_zone,
            category,
            doc.zone_order,
            len(user_message or ""),
        )
        try:
            plan = plan_intents(
                user_message,
                doc,
                is_first_fill=is_first_fill,
                target_zone=target_zone,
                category=category,
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
        trace: list[dict[str, Any]] = [
            {"tool": "orchestrator.plan", "plan": plan.model_dump()}
        ]
        used_provider = provider or ""
        used_model = model or ""
        changed: list[str] = []
        summaries: list[str] = []

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

            if intent == "style":
                try:
                    doc, summary = style_agent.run_style(
                        doc,
                        user_message,
                        provider=provider,
                        model=model,
                        api_key=api_key,
                    )
                    changed.append("header")
                    summaries.append(summary)
                    trace.append({"tool": "agent.style", "summary": summary})
                except Exception as e:
                    log.exception("orch.error: style agent failed - %s", e)
                    summaries.append(f"Style update failed: {e}")
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
                cur_intent = intent

                def _process_one_zone(
                    n: int,
                    op_intent: str = cur_intent,
                ) -> tuple[
                    int,
                    str | None,
                    str | None,
                    str | None,
                    str | None,
                    str | None,
                ]:
                    try:
                        curr = doc.zone_inner(n)
                        z = doc.get_zone(n)
                    except KeyError:
                        log.warning(
                            "orch.error: %s unknown zone %s", op_intent, n
                        )
                        return (
                            n,
                            None,
                            None,
                            None,
                            None,
                            f"Unknown zone {n}",
                        )

                    compact_digest = doc.compact_digest(active_zone_no=n)
                    try:
                        c, s = zone_agent_router.run_zone(
                            zone_no=n,
                            zone_description=z.description,
                            zone_kind=z.kind,
                            current_zone=curr,
                            full_digest=compact_digest,
                            user_message=user_message,
                            is_initial=(op_intent == "fill"),
                            provider=provider,
                            model=model,
                            api_key=api_key,
                        )
                        return (
                            n,
                            c,
                            s,
                            provider or "",
                            model or "",
                            None,
                        )
                    except Exception as agent_err:
                        log.warning(
                            "orch.warning: zone_agent failed zone=%s - %s",
                            n,
                            agent_err,
                        )
                        # Fix 4: If the provider is down / rate-limited,
                        # skip the fallback entirely.  Running _edit_zone_latex
                        # would waste up to 3 more LLM calls (×7 zones = 21
                        # wasted calls) with 100% probability of failure.
                        if _PROVIDER_DOWN_RE.search(str(agent_err)):
                            log.warning(
                                "orch.warning: provider-down detected, "
                                "skipping fallback for zone=%s",
                                n,
                            )
                            return (
                                n,
                                None,
                                None,
                                None,
                                None,
                                f"Provider unavailable: {agent_err}",
                            )
                        try:
                            c, s, p, m = _edit_zone_latex(
                                zone_no=n,
                                description=z.description,
                                current=curr,
                                digest=compact_digest,
                                user_message=user_message,
                                is_fill=(op_intent == "fill"),
                                provider=provider,
                                model=model,
                                api_key=api_key,
                            )
                            return n, c, s, p, m, None
                        except Exception as e:
                            log.exception(
                                "orch.error: %s zone %s fallback failed",
                                op_intent,
                                n,
                            )
                            return n, None, None, None, None, str(e)

                if len(targets) > 1:
                    max_w = min(len(targets), 8)
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_w
                    ) as pool:
                        results = list(pool.map(_process_one_zone, targets))
                else:
                    results = (
                        [_process_one_zone(targets[0])] if targets else []
                    )

                for n, content, summary, prov, mod, err in results:
                    if err or content is None:
                        summaries.append(f"Zone {n} {intent} failed: {err}")
                        continue
                    if prov:
                        used_provider = prov
                    if mod:
                        used_model = mod
                    doc.set_zone_inner(n, content)
                    changed.append(str(n))
                    summaries.append(summary or f"Updated zone {n}")
                    log.info(
                        "orch.step: %s zone=%s summary=%s",
                        intent,
                        n,
                        (summary or "")[:80],
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

        resolved_names: list[str] = []
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
