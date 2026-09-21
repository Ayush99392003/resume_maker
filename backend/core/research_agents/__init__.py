"""Academic research paper zone specialists and router."""

from __future__ import annotations

try:
    from core.logging_setup import get_logger
    from core.zone_agents import (
        ZoneAgent,
        ZoneAgentRouter,
        zone_agent_router,
    )
except ImportError:
    from ..logging_setup import get_logger
    from ..zone_agents import (
        ZoneAgent,
        ZoneAgentRouter,
        zone_agent_router,
    )

log = get_logger("research_agents")


class TitleAuthorsAgent(ZoneAgent):
    zone_id = "TITLE_AUTHORS"
    role = (
        "Academic paper title, authors, affiliations, and metadata specialist"
    )
    latex_hints = (
        "Preserve \\title{...}, \\author{...}, \\affiliation{...} or "
        "\\institute{...} or \\IEEEauthorblockN / \\email and \\maketitle. "
        "Format multi-author structures, affiliations, and correspondence "
        "emails properly according to the paper class. Never drop \\maketitle."
    )


class AbstractKeywordsAgent(ZoneAgent):
    zone_id = "ABSTRACT"
    role = "Academic paper abstract and keywords specialist"
    latex_hints = (
        "Format abstract in \\begin{abstract} ... \\end{abstract}. "
        "If keywords/index terms are present, include "
        "\\begin{IEEEkeywords} ... \\end{IEEEkeywords} or "
        "\\keywords{...}. Keep abstract between 150-250 words, concise, "
        "rigorous, stating the problem, contribution, and key results."
    )


class IntroductionAgent(ZoneAgent):
    zone_id = "INTRODUCTION"
    role = "Academic paper introduction specialist"
    latex_hints = (
        "Preserve \\section{Introduction} (and \\label{sec:...}). Maintain "
        "academic rigor with proper problem motivation, contextualization of "
        "prior art, clear bullet-pointed contributions (\\begin{itemize} ... "
        "\\item), and paper organization roadmap. Comprehensively incorporate "
        "all user-supplied motivations and hypotheses, replacing template "
        "placeholder text."
    )


class RelatedWorkAgent(ZoneAgent):
    zone_id = "RELATED_WORK"
    role = "Academic paper related work and literature review specialist"
    latex_hints = (
        "Preserve \\section{Related Work} or \\section{Literature Review} "
        "(and \\label{sec:...}). Comprehensively incorporate all literature "
        "categories and citations. Group related literature thematically into "
        "subsections or bold paragraphs. Ensure all cited works use standard "
        "\\cite{key} syntax and draw clear contrasts with the proposed "
        "method. Replace template placeholder text completely."
    )


class MethodologyAgent(ZoneAgent):
    zone_id = "METHODOLOGY"
    role = "Academic paper methodology and technical formulation specialist"
    latex_hints = (
        "Preserve \\section{Methodology} or \\section{Proposed Method} (and "
        "\\label{sec:...}). Comprehensively incorporate all user-supplied "
        "mathematical formulations, definitions, and algorithms. Use "
        "equation environments (\\begin{equation}, \\begin{align}), clean "
        "notation, and organize into logical subsections (e.g., "
        "\\subsection{Problem Formulation}, \\subsection{Architecture}). "
        "Completely replace template placeholder text with the user's actual "
        "methodology."
    )


class ExperimentsAgent(ZoneAgent):
    zone_id = "EXPERIMENTS"
    role = "Academic paper experiments, evaluation, and results specialist"
    latex_hints = (
        "Preserve \\section{Experiments} or \\section{Evaluation} or "
        "\\section{Experimental Evaluation} (and \\label{sec:...}). "
        "Comprehensively incorporate ALL user-supplied experimental details, "
        "hyperparameters, training protocols, and evaluation metrics without "
        "omission. "
        "If the user mentions or describes tables (e.g., Table II with "
        "benchmark results), generate a complete, publication-grade LaTeX "
        "table environment (\\begin{table}[ht] or \\begin{table*}[t]) using "
        "booktabs (\\toprule, \\midrule, \\bottomrule) with proper columns, "
        "headers, metric values, and bold/underline formatting for best/"
        "second-best. "
        "Organize the content into clear subsections (e.g., "
        "\\subsection{Experimental Setup}, \\subsection{Main Benchmark "
        "Results}, \\subsection{Evaluation of Hypotheses}, "
        "\\subsection{Heterophily and Robustness Analysis}). "
        "Completely replace any outdated starter template placeholder text "
        "and placeholder tables with the user's actual content."
    )


class DiscussionAgent(ZoneAgent):
    zone_id = "DISCUSSION"
    role = "Academic paper discussion and analysis specialist"
    latex_hints = (
        "Preserve \\section{Discussion} (and \\label{sec:...}). Provide deep "
        "qualitative analysis, ablation study insights, edge case evaluations, "
        "runtime/memory trade-offs, and honest limitations of the proposed "
        "approach. Comprehensively incorporate all user points, replacing "
        "template placeholder text."
    )


class ConclusionAgent(ZoneAgent):
    zone_id = "CONCLUSION"
    role = "Academic paper conclusion and future work specialist"
    latex_hints = (
        "Preserve \\section{Conclusion} or \\section{Conclusion and "
        "Future Work}. Summarize the core findings and impact concisely, "
        "and outline promising future research directions."
    )


class ReferencesAgent(ZoneAgent):
    zone_id = "REFERENCES"
    role = "Academic paper bibliography and citation specialist"
    latex_hints = (
        "Preserve \\begin{thebibliography}{99} ... \\end{thebibliography} "
        "or \\bibliography{...}. Ensure each \\bibitem{key} contains "
        "complete bibliographic metadata (authors, title, journal/venue, "
        "year, volume, pages). Ensure keys match in-text \\cite{key}."
    )


class AppendixAgent(ZoneAgent):
    zone_id = "APPENDIX"
    role = "Academic paper appendix and supplementary material specialist"
    latex_hints = (
        "Preserve \\appendix or \\section*{Appendix}. Include formal proofs, "
        "extended hyperparameter configurations, additional ablation plots, "
        "and reproducibility details."
    )


RESEARCH_AGENT_CLASSES = {
    "TITLE_AUTHORS": TitleAuthorsAgent,
    "ABSTRACT": AbstractKeywordsAgent,
    "KEYWORDS": AbstractKeywordsAgent,
    "IEEEKEYWORDS": AbstractKeywordsAgent,
    "INTRODUCTION": IntroductionAgent,
    "RELATED_WORK": RelatedWorkAgent,
    "METHODOLOGY": MethodologyAgent,
    "EXPERIMENTS": ExperimentsAgent,
    "DISCUSSION": DiscussionAgent,
    "CONCLUSION": ConclusionAgent,
    "REFERENCES": ReferencesAgent,
    "BIBLIOGRAPHY": ReferencesAgent,
    "APPENDIX": AppendixAgent,
}

RESEARCH_DESC_TO_AGENT: list[tuple[tuple[str, ...], str]] = [
    (
        ("title", "author", "affiliation", "institute", "metadata"),
        "TITLE_AUTHORS",
    ),
    (("abstract", "keyword", "index term"), "ABSTRACT"),
    (("introduction", "intro", "background", "motivation"), "INTRODUCTION"),
    (("related work", "literature", "prior work", "survey"), "RELATED_WORK"),
    (
        ("method", "algorithm", "formulation", "model", "approach"),
        "METHODOLOGY",
    ),
    (
        ("experiment", "evaluation", "result", "benchmark", "ablation"),
        "EXPERIMENTS",
    ),
    (("discussion", "analysis", "limitation", "tradeoff"), "DISCUSSION"),
    (("conclusion", "future work", "summary"), "CONCLUSION"),
    (("reference", "bibliography", "citation", "bib"), "REFERENCES"),
    (("appendix", "supplementary", "proof"), "APPENDIX"),
]


class ResearchAgentRouter(ZoneAgentRouter):
    """Router specialized for academic research paper zones."""

    def __init__(self) -> None:
        super().__init__()
        for zid, cls in RESEARCH_AGENT_CLASSES.items():
            if zid not in self.agents:
                self.agents[zid] = cls()


research_agent_router = ResearchAgentRouter()

for _zid, _cls in RESEARCH_AGENT_CLASSES.items():
    zone_agent_router.register_agent(_zid, _cls())
