"""Per-zone resume specialists and a router that dispatches to them."""

from __future__ import annotations

import re
from typing import Any

try:
    from core.latex_sanitizer import (
        _clean_backslash_typos,
        safe_escape_latex_text,
        safe_extract_json,
    )
    from core.logging_setup import get_logger
    from core.zones import zone_engine
    from llm_router import ChatMessage, llm_router
except ImportError:
    from ..latex_sanitizer import (
        _clean_backslash_typos,
        safe_escape_latex_text,
        safe_extract_json,
    )
    from ..llm_router import ChatMessage, llm_router  # type: ignore
    from ..logging_setup import get_logger
    from ..zones import zone_engine

log = get_logger("zone_agents")

# Aliases for backward compatibility
_extract_json = safe_extract_json
_escape_raw_latex_chars = safe_escape_latex_text


def _sanitize_tex_json(obj: Any) -> Any:
    """Restore TeX control sequences via safe_extract_json logic."""
    if isinstance(obj, str):
        obj = re.sub(r"\r([a-zA-Z])", r"\\r\1", obj)
        obj = re.sub(r"\\{2,}([a-zA-Z])", r"\\\1", obj)
        obj = _clean_backslash_typos(obj)
        obj = safe_escape_latex_text(obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _sanitize_tex_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_tex_json(x) for x in obj]
    return obj


def _extract_delimited(raw: str) -> tuple[str, str]:
    """Extract zone content and summary from delimiter tags.

    Expects the LLM to return raw LaTeX (no JSON escaping) wrapped in
    XML-style tags::

        <CONTENT>
        ...verbatim LaTeX...
        </CONTENT>
        <SUMMARY>one-sentence description</SUMMARY>

    Returns:
        Tuple of (content, summary). Either may be empty string if the
        corresponding tag is missing.
    """
    content_m = re.search(
        r"<CONTENT>\s*(.*?)\s*</CONTENT>",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    summary_m = re.search(
        r"<SUMMARY>\s*(.*?)\s*</SUMMARY>",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    content = content_m.group(1).strip() if content_m else ""
    summary = summary_m.group(1).strip() if summary_m else ""
    return content, summary


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
        document_mode: str = "resume",
        provider: str | None,
        model: str | None,
        api_key: str | None,
        max_retries: int = 3,
    ) -> tuple[str, str]:
        """Return (new_zone_latex, short_summary)."""
        mode = "initial fill" if is_initial else "content update"

        # Build the verbatim snapshot of macros used in the current zone
        # so the LLM sees the exact names, not a description.
        macro_list = ", ".join(
            m
            for m in re.findall(r"\\([a-zA-Z]+)", current_zone)
            if m not in {
                "begin", "end", "item", "vspace", "hspace",
                "textbf", "textit", "texttt", "small", "large",
                "newline", "noindent", "centering",
            }
        )
        macros_hint = (
            f"Macros found in current zone: {macro_list}\n"
            if macro_list else ""
        )

        if document_mode == "research_paper":
            system = (
                f"You are the {self.role} for a LaTeX academic research "
                "paper.\n\n"
                "OUTPUT FORMAT — follow exactly:\n"
                "<CONTENT>\n"
                "...your LaTeX here...\n"
                "</CONTENT>\n"
                "<SUMMARY>one sentence describing what changed</SUMMARY>\n\n"
                "LATEX OUTPUT RULES (non-negotiable):\n"
                "1. Write raw LaTeX. Single backslash before every command: "
                "\\section, \\subsection, \\textbf, \\begin, \\cite, \\ref "
                "— never double backslashes (\\\\cmd is WRONG).\n"
                "2. Comprehensively incorporate ALL text, findings, data, "
                "models, metrics, and hypothesis evaluations provided in "
                "the user request. NEVER truncate, omit, summarize away, "
                "or drop any part of the user's provided content.\n"
                "3. Completely replace any starter template placeholder "
                "text, dummy numbers, and placeholder tables with the "
                "user's actual content. Do NOT keep unrelated template "
                "tables or text.\n"
                "4. When experimental results, benchmark numbers, or "
                "tables are described or provided (e.g. 'Table II presents"
                "...'): generate a complete, publication-grade LaTeX table "
                "environment (\\begin{table}[ht] or \\begin{table*}[t]) "
                "using booktabs (\\toprule, \\midrule, \\bottomrule) with "
                "proper columns, headers, metric values, and bold/underline "
                "formatting for best/second-best. In tabular rows, use & to "
                "separate columns and \\\\ to end rows (this is the ONE "
                "place double-backslash is correct: row-ending, not "
                "commands).\n"
                "5. Organize the section using appropriate \\subsection{...} "
                "and \\paragraph{...} headings (e.g., "
                "\\subsection{Experimental Setup}, "
                "\\subsection{Main Benchmark Results}, "
                "\\subsection{Evaluation of H1 (Graph Utility)}, "
                "\\subsection{Evaluation of H2 & H3 (Heterophily and "
                "Robustness)}).\n"
                "6. Keep \\section{...} and \\label{...} headings. Never "
                "drop them.\n"
                "7. Never include \\documentclass, \\begin{document}, or "
                "% ZONE markers.\n\n"
                f"{macros_hint}"
                f"Zone-specific guidance: {self.latex_hints}\n\n"
                "--- CORRECT EXAMPLE ---\n"
                "Request: Add experimental setup with PyTorch and benchmark "
                "results table comparing Model A and Model B\n"
                "<CONTENT>\n"
                "\\section{Experimental Evaluation}\n"
                "\\label{sec:exp}\n"
                "\\subsection{Experimental Setup}\n"
                "All models were implemented in PyTorch and trained for "
                "100 epochs...\n\n"
                "\\subsection{Main Results}\n"
                "Table~\\ref{tab:results} summarizes the performance across "
                "benchmarks.\n\n"
                "\\begin{table}[ht]\n"
                "\\centering\n"
                "\\caption{Benchmark results on test set.}\n"
                "\\label{tab:results}\n"
                "\\begin{tabular}{lcc}\n"
                "\\toprule\n"
                "\\textbf{Model} & \\textbf{PR-AUC} & \\textbf{F1-Score} \\\\\n"
                "\\midrule\n"
                "Model A & \\textbf{0.841} & \\textbf{0.812} \\\\\n"
                "Model B & \\underline{0.838} & \\underline{0.809} \\\\\n"
                "\\bottomrule\n"
                "\\end{tabular}\n"
                "\\end{table}\n"
                "</CONTENT>\n"
                "<SUMMARY>Added experimental setup and benchmark comparison "
                "table.</SUMMARY>\n"
            )
        else:
            system = (
                f"You are the {self.role} for a LaTeX resume.\n\n"
                "OUTPUT FORMAT — follow exactly:\n"
                "<CONTENT>\n"
                "...your LaTeX here...\n"
                "</CONTENT>\n"
                "<SUMMARY>one sentence describing what changed</SUMMARY>\n\n"
                "LATEX OUTPUT RULES (non-negotiable):\n"
                "1. Write raw LaTeX. Single backslash before every command: "
                "\\resumeSubheading, \\section, \\textbf, \\begin — never "
                "double backslashes (\\\\cmd is WRONG).\n"
                "2. Preserve the EXACT macros from the current zone. If the "
                "zone uses \\resumeSubHeadingListStart, keep it. If it uses "
                "\\resumeItemListStart, keep it. Never swap to plain "
                "\\begin{itemize}.\n"
                "3. Keep \\section{...} headings. Never drop them.\n"
                "4. When the user provides new experiences, projects, or "
                "content, incorporate ALL of it into the zone using the "
                "appropriate resume macros. For targeted edits, apply the "
                "requested change while preserving the rest.\n"
                "5. Never include \\documentclass, \\begin{document}, or "
                "% ZONE markers.\n"
                "6. In tabular/tabular* rows: use & to separate columns and "
                "\\\\ to end rows (this is the ONE place double-backslash is "
                "correct: row-ending, not commands).\n\n"
                f"{macros_hint}"
                f"Zone-specific guidance: {self.latex_hints}\n\n"
                "--- CORRECT EXAMPLE ---\n"
                "Request: Change GPA to 3.9\n"
                "<CONTENT>\n"
                "\\section{Education}\n"
                "  \\resumeSubHeadingListStart\n"
                "    \\resumeSubheading\n"
                "      {MIT}{Boston, MA}\n"
                "      {BS Computer Science; GPA: 3.9}{2020 -- 2024}\n"
                "  \\resumeSubHeadingListEnd\n"
                "</CONTENT>\n"
                "<SUMMARY>Updated GPA to 3.9 in Education.</SUMMARY>\n\n"
                "--- WRONG (never do this) ---\n"
                "\\\\section{Education}   <- double backslash = WRONG\n"
                "\\\\resumeSubheading    <- double backslash = WRONG\n"
                "\\begin{itemize}       <- wrong list env if zone uses "
                "\\resumeSubHeadingListStart\n"
            )

        doc_label = (
            "Academic Research Paper"
            if document_mode == "research_paper"
            else "Resume"
        )
        user = (
            f"Mode: {mode}\n"
            f"Document Type: {doc_label}\n"
            f"Zone: {self.zone_id}\n"
            f"Current zone content:\n"
            f"{current_zone or '(empty)'}\n\n"
            f"Other zones (read-only context):\n{full_digest}\n\n"
            f"User request: {user_message}"
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
                temperature=0.25,
            )
            raw_content = resp.content
            content, summary = _extract_delimited(raw_content)

            if not content:
                log.warning(
                    "Attempt %d: no <CONTENT> tag found in response",
                    attempt + 1,
                )
                retry_msg = (
                    "Your response did not contain a <CONTENT> block. "
                    "You MUST wrap the LaTeX in <CONTENT>...</CONTENT> "
                    "and add <SUMMARY>...</SUMMARY>. Try again."
                )
                messages.append(
                    ChatMessage(role="assistant", content=raw_content)
                )
                messages.append(
                    ChatMessage(role="user", content=retry_msg)
                )
                continue

            # Guard against full-document leakage
            for bad in (
                "\\documentclass",
                "\\begin{document}",
                "\\end{document}",
            ):
                if bad in content:
                    log.warning(
                        "Attempt %d: full-document command '%s' in content",
                        attempt + 1,
                        bad,
                    )
                    content = re.sub(
                        r"\\documentclass.*?\\begin\{document\}",
                        "",
                        content,
                        flags=re.DOTALL,
                    ).strip()

            if not summary:
                summary = f"Updated {self.zone_id.lower()} zone."

            log.info(
                "zone_agent.run: zone=%s attempt=%d ok",
                self.zone_id,
                attempt + 1,
            )
            return content, summary

        raise ValueError(
            f"ZoneAgent {self.zone_id} failed after "
            f"{max_retries} attempts: no valid <CONTENT> block."
        )


class HeaderAgent(ZoneAgent):
    zone_id = "HEADER"
    role = "Header / contact specialist"
    latex_hints = (
        "Preserve the tabular/tabular* structure exactly. "
        "Use bare & to separate columns and \\\\ to end rows "
        "(row-ending double-backslash is correct here). "
        "Do NOT escape & to \\&."
    )


class SummaryAgent(ZoneAgent):
    zone_id = "SUMMARY"
    role = "Professional summary specialist"
    latex_hints = (
        "Return 2-4 sentences of plain LaTeX text. "
        "No \\section heading — this zone has none. "
        "Professional and concise."
    )


class ExperienceAgent(ZoneAgent):
    zone_id = "EXPERIENCE"
    role = "Work experience specialist"
    latex_hints = (
        "Use \\resumeSubheading for each job entry. "
        "Wrap bullets in \\resumeItemListStart ... \\resumeItemListEnd. "
        "Use \\resumeItem{Title}{description} for each bullet. "
        "Preserve \\section{Experience} and "
        "\\resumeSubHeadingListStart ... \\resumeSubHeadingListEnd."
    )


class EducationAgent(ZoneAgent):
    zone_id = "EDUCATION"
    role = "Education specialist"
    latex_hints = (
        "Preserve \\section{Education}, "
        "\\resumeSubHeadingListStart, and \\resumeSubHeadingListEnd. "
        "Use \\resumeSubheading{Uni}{Location}{Degree; CGPA}{Dates} "
        "for each entry. Never use \\begin{itemize}."
    )


class SkillsAgent(ZoneAgent):
    zone_id = "SKILLS"
    role = "Skills specialist"
    latex_hints = (
        "Preserve \\section{...}, \\resumeSubHeadingListStart, "
        "\\resumeSubHeadingListEnd. "
        "Use \\resumeSubItem{Category}{values} for each row. "
        "Never use \\begin{itemize} in place of "
        "\\resumeSubHeadingListStart."
    )


class ProjectsAgent(ZoneAgent):
    zone_id = "PROJECTS"
    role = "Projects specialist"
    latex_hints = (
        "Preserve \\section{Projects} and "
        "\\resumeSubHeadingListStart ... \\resumeSubHeadingListEnd. "
        "Use \\resumeSubItem or \\resumeProjectHeading for project "
        "entries. Wrap bullet points in "
        "\\resumeItemListStart ... \\resumeItemListEnd."
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
    # Academic paper specific phrases first to prevent generic overlap
    (("related work", "literature", "prior work", "survey"), "RELATED_WORK"),
    (
        ("title", "author", "affiliation", "institute", "metadata"),
        "TITLE_AUTHORS",
    ),
    (("abstract", "keyword", "index term"), "ABSTRACT"),
    (("introduction", "intro", "background", "motivation"), "INTRODUCTION"),
    (
        ("method", "algorithm", "formulation", "model", "approach"),
        "METHODOLOGY",
    ),
    (
        ("experiment", "evaluation", "result", "benchmark", "ablation"),
        "EXPERIMENTS",
    ),
    (("discussion", "analysis", "limitation", "tradeoff"), "DISCUSSION"),
    (("conclusion", "future work"), "CONCLUSION"),
    (("reference", "bibliography", "citation", "bib"), "REFERENCES"),
    (("appendix", "supplementary", "proof"), "APPENDIX"),
    # Resume zones
    (
        (
            "work experience",
            "experience",
            "employment",
            "career",
            "job",
            "work",
        ),
        "EXPERIENCE",
    ),
    (("project", "portfolio", "work sample"), "PROJECTS"),
    (("education", "degree", "school", "university", "academic"), "EDUCATION"),
    (("skill", "stack", "technolog", "language", "tool"), "SKILLS"),
    (("summary", "about", "profile", "objective"), "SUMMARY"),
    (("header", "contact", "name", "heading", "personal"), "HEADER"),
]


def _description_to_agent_key(description: str, kind: str) -> str | None:
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
        self.agents: dict[str, ZoneAgent] = {
            zid: cls() for zid, cls in ZONE_AGENT_CLASSES.items()
        }

    def register_agent(self, zone_id: str, agent: ZoneAgent) -> None:
        """Register or override a specialist agent for a zone ID."""
        self.agents[zone_id.upper()] = agent

    def _resolve_agent(
        self,
        zone_id: str,
        zone_catalog: list[dict] | None = None,
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
        available: list[str],
        *,
        is_initial: bool,
        provider: str | None,
        model: str | None,
        api_key: str | None,
    ) -> list[str]:
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
        if not chosen and available:
            # fallback if model did not return a valid zone
            chosen = [available[0]]
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
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        zone_catalog: list[dict] | None = None,
    ) -> dict[str, Any]:
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

        updates: dict[str, str] = {}
        summaries: list[str] = []
        trace: list[dict[str, Any]] = [
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
                    "zone_agent.error: %s failed", zone_id
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


    def run_zone(
        self,
        *,
        zone_no: int,
        zone_description: str,
        zone_kind: str,
        current_zone: str,
        full_digest: str,
        user_message: str,
        is_initial: bool,
        document_mode: str = "resume",
        provider: str | None,
        model: str | None,
        api_key: str | None,
    ) -> tuple[str, str]:
        """Run the appropriate ZoneAgent for a numbered document zone.

        This is the unified entry point used by the orchestrator so that
        *all* fill/edit operations pass through Pydantic validation and the
        retry loop — eliminating the bypass path via ``_edit_zone_latex``.

        Args:
            zone_no: Numeric zone identifier in the ZoneDocument.
            zone_description: Human-readable description
                (e.g. 'Work experience').
            zone_kind: Kind string (e.g. 'predefined_experience').
            current_zone: Current inner LaTeX of this zone.
            full_digest: Digest of all zones for context.
            user_message: The user's edit/fill request.
            is_initial: True when this is an initial bio-fill.
            document_mode: Document mode ('resume' or 'research_paper').
            provider: LLM provider override.
            model: Model name override.
            api_key: API key override.

        Returns:
            ``(new_zone_latex, short_summary)`` tuple.
        """
        agent = self._resolve_agent(
            str(zone_no),
            zone_catalog=[
                {
                    "zone_no": zone_no,
                    "description": zone_description,
                    "kind": zone_kind,
                }
            ],
        )
        log.info(
            "zone_agent.run_zone: zone=%s agent=%s initial=%s mode=%s",
            zone_no,
            agent.zone_id,
            is_initial,
            document_mode,
        )
        content, summary = agent.run(
            user_message=user_message,
            current_zone=current_zone,
            full_digest=full_digest,
            is_initial=is_initial,
            document_mode=document_mode,
            provider=provider,
            model=model,
            api_key=api_key,
        )
        return content, summary


zone_agent_router = ZoneAgentRouter()
