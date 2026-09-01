"""Comparative benchmark: Auto Mode vs Section Specified Mode on Ayush's LaTeX Resume.

Tests identical edit requests under:
1. Auto Mode (target_zone="auto")
2. Section Specified Mode (target_zone="1", target_zone="4", target_zone="3")

Logs token metrics, LLM call counts, latency, and compilation status.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from core.ai_agent import ai_agent
from core.compiler import CompilationError, compiler
from core.latex_to_zones import latex_to_zones
from core.session_store import session_store
from core.zone_document import ZoneDocument, ensure_full_document, sync_session_from_document
from llm_router import ChatMessage, llm_router
from rich.console import Console
from rich.table import Table

console = Console(highlight=False)

CUSTOM_TEMPLATE = r"""%------------------------
% Resume Template
% Author : Anubhav Singh
% Github : https://github.com/xprilion
% License : MIT
%------------------------

\documentclass[a4paper,20pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{fancyhdr}

\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\addtolength{\oddsidemargin}{-0.530in}
\addtolength{\evensidemargin}{-0.375in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.45in}
\addtolength{\textheight}{1in}

\urlstyle{rm}

\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\titleformat{\section}{
  \vspace{-10pt}\scshape\raggedright\large
}{}{0em}{}[\color{black}\titlerule \vspace{-6pt}]

\newcommand{\resumeItem}[2]{
  \item\small{
    \textbf{#1}{: #2 \vspace{-2pt}}
  }
}

\newcommand{\resumeSubheading}[4]{
  \vspace{-1pt}\item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{#3} & \textit{#4} \\
    \end{tabular*}\vspace{-5pt}
}

\newcommand{\resumeSubItem}[2]{\resumeItem{#1}{#2}\vspace{-3pt}}
\renewcommand{\labelitemii}{$\circ$}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=*]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}

\begin{document}

%----------HEADING-----------------
\begin{tabular*}{\textwidth}{l@{\extracolsep{\fill}}r}
  \textbf{{\LARGE Ayush Agarwal}} &
  Email: \href{mailto:ayush20039939@gmail.com}{ayush20039939@gmail.com}\\
  \href{https://github.com/Ayush99392003}{Github: github.com/Ayush99392003} &
  \href{https://www.linkedin.com/in/ayush20039939}{LinkedIn: linkedin.com/in/ayush20039939}\\
\end{tabular*}

%-----------EDUCATION-----------------
\section{Education}
  \resumeSubHeadingListStart
    \resumeSubheading
      {VIT Bhopal University}{Bhopal, India}
      {Bachelor of Technology - Computer Science and Engineering;  CGPA: 8.50/10}{Sep 2023 -- Ongoing}
      {\scriptsize \textit{ \footnotesize{\newline{}\textbf{Courses:} Data Structures, Algorithms, Machine Learning, Deep Learning, NLP, Databases, Cloud Computing}}}
  \resumeSubHeadingListEnd

\vspace{-5pt}
\section{Skills Summary}
\resumeSubHeadingListStart
\resumeSubItem{Programming}{~~~~Python, C++, SQL}
\resumeSubItem{Backend}{~~~~~~~~~~~~FastAPI, REST APIs, WebSockets, Async Programming, SQLAlchemy}
\resumeSubItem{AI/ML}{~~~~~~~~~~~~~~LLMs, RAG, NLP, Prompt Engineering, Multi-Agent Systems, LangChain, MCP, Tool Calling}
\resumeSubItem{Databases}{~~~~~~~~~SQLite (FTS5), PostgreSQL, Firestore, Azure Cosmos DB}
\resumeSubHeadingListEnd

\vspace{-5pt}
%-----------EXPERIENCE-----------------
\section{Experience}
\resumeSubHeadingListStart
\resumeSubheading
{Docu3C Technologies}{Remote (Seattle, Washington, USA)}
{AI Software Engineer Intern}{Aug 2025 -- July 2026}
\resumeItemListStart
\resumeItem{Backend Engineering}
{Developed asynchronous FastAPI services using REST APIs, Server-Sent Events (SSE), and WebSockets to support concurrent AI inference.}
\resumeItem{Agentic AI Systems}
{Designed and implemented multi-agent AI workflows using Model Context Protocol (MCP) with tool-calling capabilities.}
\resumeItemListEnd
\resumeSubHeadingListEnd

\end{document}
"""


def get_groq_key_and_model() -> tuple[str, str]:
    profile = BACKEND / "data" / "profiles" / "ayush.json"
    if profile.exists():
        data = json.loads(profile.read_text(encoding="utf-8"))
        key = data.get("api_keys", {}).get("groq")
    else:
        key = os.environ.get("GROQ_API_KEY")

    if not key:
        raise RuntimeError("No Groq API key found in profile or environment.")

    models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
    for m in models:
        try:
            resp = llm_router.chat(
                provider="groq",
                model=m,
                messages=[ChatMessage(role="user", content="Return OK")],
                api_key=key,
            )
            if resp.content:
                console.print(f"[green]Using model: {m}[/green]")
                return key, m
        except Exception as e:
            console.print(f"[yellow]Model {m} probe error: {e}[/yellow]")
    raise RuntimeError("No working model found on Groq")


def compile_with_retry(
    latex_code: str,
    max_retries: int = 2,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> tuple[bytes, str, float]:
    current_latex = ensure_full_document(latex_code or "")
    total_render_time = 0.0
    for attempt in range(max_retries + 1):
        t0 = time.time()
        try:
            pdf = compiler.compile(current_latex)
            total_render_time += time.time() - t0
            return (pdf, current_latex, round(total_render_time, 3))
        except CompilationError as e:
            total_render_time += time.time() - t0
            if attempt == max_retries:
                raise e
            console.print(
                f"[yellow]Compilation attempt {attempt + 1} failed. Auto-repairing LaTeX with AI Agent...[/yellow]"
            )
            fix_update = ai_agent.fix_latex_error(
                current_latex,
                e.logs,
                provider=provider,
                model=model,
                api_key=api_key,
            )
            current_latex = fix_update.latex_code
    raise Exception("Max retries exceeded in compilation loop.")


def run_benchmark():
    groq_key, groq_model = get_groq_key_and_model()
    out_dir = PROJECT_ROOT / "test_results" / "auto_vs_section_comparison"
    out_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        {
            "id": "test_1_header",
            "section_name": "Header",
            "target_zone": "1",
            "prompt": "Add phone +91-9939200303 and location Seattle, WA / Bhopal, India to contact info.",
        },
        {
            "id": "test_2_experience",
            "section_name": "Experience",
            "target_zone": "4",
            "prompt": "In Experience, add bullet: Built multi-agent MCP workflows with tool-calling, reducing review time by 60% and saving $45k/mo.",
        },
        {
            "id": "test_3_skills",
            "section_name": "Skills",
            "target_zone": "3",
            "prompt": "Update Skills: Add Redis, Docker, PyTorch and Instructor with special characters and symbols.",
        },
    ]

    results: List[Dict[str, Any]] = []

    for tc in test_cases:
        console.rule(f"[bold cyan]Benchmarking: {tc['section_name']} ({tc['id']})[/bold cyan]")
        console.print(f"Prompt: [italic]{tc['prompt']}[/italic]")

        # 1. Run in AUTO Mode
        console.print("\n[bold yellow]--- Running in AUTO Mode (target_zone='auto') ---[/bold yellow]")
        doc_auto = latex_to_zones(CUSTOM_TEMPLATE)
        sess_auto = session_store.create(
            template_name="custom_ayush",
            title=f"Auto Mode {tc['id']}",
            latex_code=doc_auto.assemble(),
            provider="groq",
            model=groq_model,
            header=doc_auto.header,
            footer=doc_auto.footer,
            zones=[z.model_dump() for z in doc_auto.zones],
            zone_order=list(doc_auto.zone_order),
            next_zone_no=doc_auto.next_zone_no,
            setup_complete=True,
        )
        llm_router.reset_metrics()
        t0 = time.time()
        res_auto = ai_agent.run_chat_turn(
            user_message=tc["prompt"],
            latex_code=sess_auto.latex_code,
            template_latex=CUSTOM_TEMPLATE,
            history=[],
            target_zone="auto",
            provider="groq",
            model=groq_model,
            api_key=groq_key,
            session=sess_auto,
        )
        latency_auto = round(time.time() - t0, 2)
        metrics_auto = llm_router.get_metrics()

        # Compile check Auto with retry
        pdf_bytes_auto, compiled_auto, _ = compile_with_retry(
            res_auto.latex_code,
            provider="groq",
            model=groq_model,
            api_key=groq_key,
        )
        assert len(pdf_bytes_auto) > 0, "Auto PDF compile failed"

        # 2. Run in SECTION SPECIFIED Mode
        console.print(f"[bold green]--- Running in SECTION SPECIFIED Mode (target_zone='{tc['target_zone']}') ---[/bold green]")
        doc_spec = latex_to_zones(CUSTOM_TEMPLATE)
        sess_spec = session_store.create(
            template_name="custom_ayush",
            title=f"Section Specified Mode {tc['id']}",
            latex_code=doc_spec.assemble(),
            provider="groq",
            model=groq_model,
            header=doc_spec.header,
            footer=doc_spec.footer,
            zones=[z.model_dump() for z in doc_spec.zones],
            zone_order=list(doc_spec.zone_order),
            next_zone_no=doc_spec.next_zone_no,
            setup_complete=True,
        )
        llm_router.reset_metrics()
        t0 = time.time()
        res_spec = ai_agent.run_chat_turn(
            user_message=tc["prompt"],
            latex_code=sess_spec.latex_code,
            template_latex=CUSTOM_TEMPLATE,
            history=[],
            target_zone=tc["target_zone"],
            provider="groq",
            model=groq_model,
            api_key=groq_key,
            session=sess_spec,
        )
        latency_spec = round(time.time() - t0, 2)
        metrics_spec = llm_router.get_metrics()

        # Compile check Spec with retry
        pdf_bytes_spec, compiled_spec, _ = compile_with_retry(
            res_spec.latex_code,
            provider="groq",
            model=groq_model,
            api_key=groq_key,
        )
        assert len(pdf_bytes_spec) > 0, "Section Specified PDF compile failed"

        # Token savings calculations
        token_saved = metrics_auto["total_tokens"] - metrics_spec["total_tokens"]
        pct_saved = round((token_saved / metrics_auto["total_tokens"] * 100) if metrics_auto["total_tokens"] > 0 else 0, 1)

        record = {
            "test_id": tc["id"],
            "section": tc["section_name"],
            "prompt": tc["prompt"],
            "auto_mode": {
                "llm_calls": metrics_auto["call_count"],
                "prompt_tokens": metrics_auto["prompt_tokens"],
                "completion_tokens": metrics_auto["completion_tokens"],
                "total_tokens": metrics_auto["total_tokens"],
                "latency_seconds": latency_auto,
                "resolved_zones": res_auto.resolved_zones,
                "pdf_size": len(pdf_bytes_auto),
            },
            "section_specified_mode": {
                "llm_calls": metrics_spec["call_count"],
                "prompt_tokens": metrics_spec["prompt_tokens"],
                "completion_tokens": metrics_spec["completion_tokens"],
                "total_tokens": metrics_spec["total_tokens"],
                "latency_seconds": latency_spec,
                "resolved_zones": res_spec.resolved_zones,
                "pdf_size": len(pdf_bytes_spec),
            },
            "savings": {
                "tokens_saved": token_saved,
                "percent_saved": pct_saved,
                "latency_delta_seconds": round(latency_auto - latency_spec, 2),
            },
        }
        results.append(record)

    # Output comparison table
    table = Table(title="Token & Routing Comparison: Auto Mode vs Section Specified Mode")
    table.add_column("Test Case", style="bold cyan")
    table.add_column("Mode", style="white")
    table.add_column("LLM Calls", style="bright_blue")
    table.add_column("Prompt Tokens", style="cyan")
    table.add_column("Total Tokens", style="magenta")
    table.add_column("Latency (s)", style="green")
    table.add_column("Resolved Zones", style="yellow")
    table.add_column("Tokens Saved", style="bold green")

    for r in results:
        table.add_row(
            r["section"],
            "Auto (Classifier/Rule)",
            str(r["auto_mode"]["llm_calls"]),
            str(r["auto_mode"]["prompt_tokens"]),
            str(r["auto_mode"]["total_tokens"]),
            f"{r['auto_mode']['latency_seconds']}s",
            str(r["auto_mode"]["resolved_zones"]),
            "-",
        )
        table.add_row(
            r["section"],
            "Section Specified (Fast-Path)",
            str(r["section_specified_mode"]["llm_calls"]),
            str(r["section_specified_mode"]["prompt_tokens"]),
            str(r["section_specified_mode"]["total_tokens"]),
            f"{r['section_specified_mode']['latency_seconds']}s",
            str(r["section_specified_mode"]["resolved_zones"]),
            f"[bold green]{r['savings']['tokens_saved']} ({r['savings']['percent_saved']}%) [/bold green]",
        )
        table.add_row("", "", "", "", "", "", "", "")

    console.print("\n")
    console.print(table)

    # Save master benchmark JSON
    json_path = out_dir / "comparison_results.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    console.print(f"\n[green]Saved benchmark JSON to {json_path}[/green]")


if __name__ == "__main__":
    run_benchmark()
