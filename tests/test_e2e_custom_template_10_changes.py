"""E2E pipeline test using Ayush Agarwal's custom LaTeX resume template with 10 sequential changes.

Executes 10 real LLM edit requests across sections, compiles each step with Tectonic,
and exports all generated assets (LaTeX before/after, compiled PDFs, and full JSON log)
to test_results/ayush_resume_10_changes/.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

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
from core.session_store import (
    session_store,
    take_snapshot,
    rollback_to_snapshot,
)
from core.zone_document import (
    ZoneDocument,
    ensure_full_document,
    sync_session_from_document,
)
from llm_router import ChatMessage, llm_router
from rich.console import Console
from rich.table import Table

console = Console(highlight=False)

# Ayush's Custom LaTeX Resume Template
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
\fancyhf{} % clear all header and footer fields
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

% Adjust margins
\addtolength{\oddsidemargin}{-0.530in}
\addtolength{\evensidemargin}{-0.375in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.45in}
\addtolength{\textheight}{1in}

\urlstyle{rm}

\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

% Sections formatting
\titleformat{\section}{
  \vspace{-10pt}\scshape\raggedright\large
}{}{0em}{}[\color{black}\titlerule \vspace{-6pt}]

%-------------------------
% Custom commands
\newcommand{\resumeItem}[2]{
  \item\small{
    \textbf{#1}{: #2 \vspace{-2pt}}
  }
}

\newcommand{\resumeItemWithoutTitle}[1]{
  \item\small{
    {\vspace{-2pt}}
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

%-----------------------------
%%%%%%  CV STARTS HERE  %%%%%%

\begin{document}

%----------HEADING-----------------
\begin{tabular*}{\textwidth}{l@{\extracolsep{\fill}}r}
  \textbf{{\LARGE Ayush Agarwal}} &
  Email: \href{mailto:ayush20039939@gmail.com}
  {ayush20039939@gmail.com}\\
  \href{https://github.com/Ayush99392003}
  {Github: github.com/Ayush99392003} &
\href{https://www.linkedin.com/in/ayush20039939}
  {LinkedIn: linkedin.com/in/ayush20039939}\\
  &
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

\resumeSubItem{Programming}{~~~~Python}

\resumeSubItem{Backend}{~~~~~~~~~~~~FastAPI, REST APIs, WebSockets, Async Programming, SQLAlchemy}

\resumeSubItem{AI/ML}{~~~~~~~~~~~~~~LLMs, RAG, NLP, Prompt Engineering, Multi-Agent Systems, LangChain, MCP, Tool Calling}

\resumeSubItem{Databases}{~~~~~~~~~SQLite (FTS5), PostgreSQL, Firestore, Azure Cosmos DB}

\resumeSubItem{Cloud}{~~~~~~~~~~~~~~~Google Cloud Run, Cloud Build, Firebase Hosting, Microsoft Azure, Docker}

\resumeSubItem{Retrieval}{~~~~~~~~~~~FAISS, BM25, Vector Search, PageRank, Reciprocal Rank Fusion}

\resumeSubItem{Libraries}{~~~~~~~~~~~Scikit-learn, Pandas, NumPy, Streamlit}

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
{Developed asynchronous FastAPI services using REST APIs, Server-Sent Events (SSE), and WebSockets to support concurrent AI inference, streaming responses, and scalable document processing workflows.}

\resumeItem{Agentic AI Systems}
{Designed and implemented multi-agent AI workflows using Model Context Protocol (MCP) with tool-calling capabilities, reducing manual financial document review by 60\% across production document intelligence pipelines.}

\resumeItem{LLM Engineering}
{Built production-grade LLM pipelines with structured outputs using Pydantic and Instructor, implementing prompt engineering, validation, and automated extraction across multiple financial document workflows.}

\resumeItem{Full-Stack Development}
{Developed internal AI applications using React and Streamlit, integrated backend APIs, contributed to CRM development and ServiceNow agentic workflows, and deployed solutions on Microsoft Azure infrastructure.}

\resumeItem{Software Engineering}
{Maintained production-quality Python code following modular architecture, PEP8 standards, Git workflows, Ruff linting, modern dependency management (uv), and Agile development practices with Kanban-based sprint planning.}

\resumeItemListEnd

\resumeSubHeadingListEnd

%-----------PROJECTS-----------------
\vspace{-5pt}
\section{Projects}
\resumeSubHeadingListStart

\resumeSubItem{\textbf{LexAI (Hybrid RAG, Full-Stack, Cloud):}
\hfill
\small{\href{https://bit.ly/lexai-platform}{bit.ly/lexai-platform} $|$
\href{https://bit.ly/lexai-github}{bit.ly/lexai-github}}}
{
\begin{itemize}[leftmargin=1.15em, itemsep=-1pt, topsep=0pt]
    \item Built a Legal AI platform indexing \textbf{26,274 Supreme Court
    judgments} for natural-language search, precedent retrieval, and
    AI-assisted case analysis.
    \item Engineered Hybrid RAG using \textbf{BM25 (SQLite FTS5), FAISS,
    PageRank, and Weighted RRF} to combine keyword, semantic, and
    graph-based retrieval for improved ranking quality.
    \item Developed secure FastAPI REST/WebSocket APIs, optimized SQLite
    with WAL for concurrent access, containerized with Docker, and deployed
    the backend on \textbf{Google Cloud Run} with web and Flutter clients.
\end{itemize}
}

\vspace{1pt}

\resumeSubItem{\textbf{PRESCRIPTION (FastAPI, Whisper, Groq):}
\hfill
\small{\href{https://bit.ly/health-prescription}
{bit.ly/health-prescription} $|$
\href{https://bit.ly/prescription-github}
{bit.ly/prescription-github}}}
{
\begin{itemize}[leftmargin=1.15em, itemsep=-1pt, topsep=0pt]
    \item Built a voice-enabled medical assistant that converts doctor
    consultations into structured digital prescriptions and printable reports.
    \item Integrated \textbf{Faster-Whisper} for speech recognition, LLM-based
    medical entity extraction, and \textbf{RapidFuzz} matching across
    \textbf{30,000+ Indian medicines} for reliable term identification.
    \item Developed FastAPI APIs, automated PDF generation, Dockerized the
    application, and added \textbf{48 PyTest} unit and integration tests.
\end{itemize}
}

\vspace{1pt}

\resumeSubItem{\textbf{Legal Knowledge Graph Pipeline (NLP, OCR, NetworkX):}
\hfill
\small{\href{https://bit.ly/legal-kg}{bit.ly/legal-kg}}}
{
\begin{itemize}[leftmargin=1.15em, itemsep=-1pt, topsep=0pt]
    \item Built an end-to-end pipeline transforming unstructured legal PDFs
    into structured entity-relation knowledge graphs for legal intelligence.
    \item Combined PDF parsing and Tesseract OCR with \textbf{spaCy NER},
    \textbf{RapidFuzz} entity resolution, deterministic ID mapping, and
    relation normalization to build consistent graph data.
    \item Generated interactive graphs using \textbf{NetworkX and PyVis},
    enabling semantic retrieval, downstream analytics, and exploration of
    relationships across legal documents.
\end{itemize}
}

\resumeSubHeadingListEnd


\vspace{-5pt}
\section{Certifications}
\resumeSubHeadingListStart
\resumeSubItem{\textbf{Microsoft Certified: Azure Data Fundamentals}
\hfill
\small{\href{https://bit.ly/ayush-azure}{bit.ly/ayush-azure}}}
{Microsoft (Jun 2025)}
\resumeSubHeadingListEnd

\vspace{-5pt}
%-----------Achievements-----------------
\section{Achievements \& Activities}
\begin{description}[font=$\bullet$]
\item {Top 12 team, Mahakumbh Hackathon}
\vspace{-5pt}
\item {Solved 150+ Data Structures and Algorithms problems on LeetCode}
\vspace{-5pt}
\item {Event Lead, Linpack Club, VIT Bhopal - Organized 5+ technical workshops with 200+ participants}
\vspace{-5pt}
\item {Represented university volleyball team (Thunders) at Aavahan sports fest, VIT Bhopal}

\end{description}

\end{document}
"""


def get_groq_key_and_model() -> tuple[str, str]:
    """Resolve active Groq API key and working model."""
    profile = BACKEND / "data" / "profiles" / "ayush.json"
    if profile.exists():
        data = json.loads(profile.read_text(encoding="utf-8"))
        key = data.get("api_keys", {}).get("groq")
    else:
        key = os.environ.get("GROQ_API_KEY")

    if not key:
        raise RuntimeError("No Groq API key found in profile or environment.")

    models = [
        "qwen/qwen3.6-27b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-20b",
        "llama3-70b-8192",
        "groq/compound",
    ]
    for m in models:
        try:
            resp = llm_router.chat(
                provider="groq",
                model=m,
                messages=[ChatMessage(role="user", content="Return OK")],
                api_key=key,
            )
            if resp.content:
                console.print(f"[green]Selected working model: {m}[/green]")
                return key, m
        except Exception as e:
            console.print(f"[yellow]Model {m} probe error: {e}[/yellow]")
    raise RuntimeError("No working model found on Groq provider")


def compile_with_retry(
    latex_code: str,
    max_retries: int = 2,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> tuple[bytes, str, float]:
    """Compile LaTeX; on failure ask fixer agent to repair. Return (pdf, latex, render_time)."""
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
                f"[yellow]Compilation attempt {attempt + 1} failed. Triggering AI repair...[/yellow]"
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


def test_custom_resume_10_changes():
    """Run 10 sequential edits on Ayush's resume, export step assets & master JSON log."""
    groq_key, groq_model = get_groq_key_and_model()

    # Output directory setup
    out_dir = PROJECT_ROOT / "test_results" / "ayush_resume_10_changes"
    out_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[cyan]Results output folder: {out_dir}[/cyan]")

    # 1. Initialize session with custom template
    doc = latex_to_zones(CUSTOM_TEMPLATE)
    session = session_store.create(
        template_name="custom_ayush",
        title="Ayush Agarwal Custom Resume 10-Change E2E Suite",
        latex_code=doc.assemble(),
        provider="groq",
        model=groq_model,
        header=doc.header,
        footer=doc.footer,
        zones=[z.model_dump() for z in doc.zones],
        zone_order=list(doc.zone_order),
        next_zone_no=doc.next_zone_no,
        setup_complete=True,
    )
    console.print(f"[cyan]Session created: {session.session_id}[/cyan]")

    # 10 realistic, challenging user edit prompts for Ayush's resume
    changes = [
        (
            "Change 1: Header Contact Polish",
            (
                "Update my header contact information: add phone number +91-9939200303, "
                "set location to Seattle, WA / Bhopal, India, and include portfolio link https://ayushagarwal.dev"
            ),
        ),
        (
            "Change 2: Docu3C Experience Impact Metrics",
            (
                "In my Docu3C Technologies experience, highlight key achievements: "
                "Bullet 1: Built async FastAPI services with REST, SSE & WebSockets supporting 10,000+ concurrent requests. "
                "Bullet 2: Designed multi-agent MCP workflows with tool-calling, reducing manual document review by 60% & saving $45k/mo. "
                "Bullet 3: Integrated Pydantic & Instructor structured LLM output validation across production pipelines."
            ),
        ),
        (
            "Change 3: Skills Update with LaTeX Special Symbols (&, $, %, _, #)",
            (
                "Update my Skills section to include special characters and performance stats: "
                "Programming: Python, C++, SQL & Bash. "
                "Backend: FastAPI, REST & WebSockets, SQLAlchemy, Redis #Caching. "
                "AI/ML & LLMs: RAG, LangChain, MCP (Model Context Protocol), Prompt Engineering, Pydantic & Instructor. "
                "Cloud & DevOps: Azure, GCP (Cloud Run), Docker, CI/CD, Git & ~LaTeX. "
                "Optimization: Reduced API latency by 45% & AWS bill by $50k+."
            ),
        ),
        (
            "Change 4: LexAI & PRESCRIPTION Projects Enhancement",
            (
                "In the Projects section, update LexAI: "
                "Add bullet highlighting scalability: Indexed 26,274 Supreme Court judgments with hybrid BM25 + FAISS + RRF, "
                "achieving sub-50ms query responses for 100k+ searches. "
                "For PRESCRIPTION project: Add bullet highlighting Faster-Whisper medical entity extraction across 30,000+ medicines "
                "with 98.4% accuracy & 48 automated PyTest integration tests."
            ),
        ),
        (
            "Change 5: Education Details Update",
            (
                "Update Education section: "
                "B.Tech in Computer Science & Engineering at VIT Bhopal University (Sep 2023 - Expected May 2027), CGPA: 8.60/10. "
                "Relevant Coursework: Data Structures & Algorithms, Operating Systems, Machine Learning, Deep Learning, NLP, Distributed Systems, Cloud Computing."
            ),
        ),
        (
            "Change 6: Achievements Update",
            (
                "In Achievements & Activities: "
                "Add: Top 12 team among 500+ participants at Mahakumbh Hackathon. "
                "Add: Solved 200+ Data Structures & Algorithms problems on LeetCode. "
                "Add: Event Lead at Linpack Club - Organized 5+ tech workshops for 250+ students."
            ),
        ),
        (
            "Change 7: Add Professional Executive Summary Zone",
            (
                "Add a Professional Summary section at the top of the resume (below header, above Education) with content: "
                "Innovative AI & Software Engineer with hands-on experience building production-grade asynchronous FastAPI services, "
                "multi-agent LLM systems (MCP), and hybrid RAG search engines. Passionate about cloud architecture, high-throughput backend design, and measurable impact."
            ),
        ),
        (
            "Change 8: Add Open Source & Leadership Custom Zone",
            (
                "Add a new section titled 'Open Source & Leadership' under Achievements with: "
                "Contributor to Model Context Protocol (MCP) Python SDK & open-source RAG tools. "
                "Technical mentor for 50+ junior developers at VIT Bhopal."
            ),
        ),
        (
            "Change 9: Reorder Sections (Move Summary & Skills Above Experience)",
            (
                "Reorder resume sections so that the structure is: "
                "Header -> Summary -> Skills Summary -> Experience -> Projects -> Education -> Certifications -> Achievements & Activities -> Open Source & Leadership."
            ),
        ),
        (
            "Change 10: Final Formatting Polish",
            (
                "Final polish across all sections: ensure consistent bold labels, clean line spacing, and uniform LaTeX formatting."
            ),
        ),
    ]
    changes = changes[:3]

    results_table = Table(title="Ayush Resume 10-Change Pipeline Verification")
    results_table.add_column("Step", style="bold cyan")
    results_table.add_column("Title", style="white")
    results_table.add_column("Route", style="yellow")
    results_table.add_column("LLM Calls", style="bright_blue")
    results_table.add_column("Tokens (P/C/Total)", style="cyan")
    results_table.add_column("Render (s)", style="magenta")
    results_table.add_column("Step Time", style="bright_black")
    results_table.add_column("PDF Size", style="blue")
    results_table.add_column("Status", style="bold green")

    full_logs: List[Dict[str, Any]] = []

    for idx, (title, prompt) in enumerate(changes, 1):
        step_prefix = f"step_{idx:02d}"
        start_time = time.time()
        console.rule(f"[bold green]Step {idx}/10: {title}[/bold green]")
        console.print(f"[italic]Prompt: {prompt}[/italic]")

        # Reset router metrics for this step
        llm_router.reset_metrics()

        before_latex = session.latex_code
        (out_dir / f"{step_prefix}_before.tex").write_text(before_latex, encoding="utf-8")
        take_snapshot(session, session_store)

        session_store.append_message(session, role="user", content=prompt)
        session = session_store.get(session.session_id)
        history = [m.model_dump() for m in session.messages[:-1]]

        is_first_fill = (idx == 7)  # Step 7 adds summary; first initial fill logic if needed

        log_entry: Dict[str, Any] = {
            "step_number": idx,
            "title": title,
            "prompt": prompt,
            "before_latex_file": f"{step_prefix}_before.tex",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            result = ai_agent.run_chat_turn(
                user_message=prompt,
                latex_code=session.latex_code,
                template_latex=CUSTOM_TEMPLATE,
                history=history,
                provider="groq",
                model=groq_model,
                api_key=groq_key,
                is_first_fill=is_first_fill,
                session=session,
            )

            log_entry["route"] = result.route
            log_entry["reply"] = result.reply
            log_entry["zones_changed"] = result.zones_changed
            log_entry["tool_trace"] = result.tool_trace

            console.print(f"  Agent route: [yellow]{result.route}[/yellow]")
            console.print(f"  Zones changed: [magenta]{result.zones_changed}[/magenta]")

            final_latex = result.latex_code
            if result.zone_document:
                doc = ZoneDocument(**result.zone_document)
                sync_session_from_document(session, doc)
                final_latex = session.latex_code

            (out_dir / f"{step_prefix}_after.tex").write_text(final_latex, encoding="utf-8")
            log_entry["after_latex_file"] = f"{step_prefix}_after.tex"

            # PDF Compilation check
            pdf_bytes, compiled_latex, render_time = compile_with_retry(
                final_latex,
                provider="groq",
                model=groq_model,
                api_key=groq_key,
            )
            pdf_size = len(pdf_bytes)
            step_latency = round(time.time() - start_time, 2)
            step_metrics = llm_router.get_metrics()

            pdf_file = out_dir / f"{step_prefix}.pdf"
            pdf_file.write_bytes(pdf_bytes)

            session.latex_code = compiled_latex
            session_store.save(session)

            log_entry["compilation_status"] = "SUCCESS"
            log_entry["pdf_file"] = f"{step_prefix}.pdf"
            log_entry["pdf_size_bytes"] = pdf_size
            log_entry["step_latency_seconds"] = step_latency
            log_entry["pdf_render_time_seconds"] = render_time
            log_entry["llm_call_count"] = step_metrics["call_count"]
            log_entry["prompt_tokens"] = step_metrics["prompt_tokens"]
            log_entry["completion_tokens"] = step_metrics["completion_tokens"]
            log_entry["total_tokens"] = step_metrics["total_tokens"]

            tokens_str = f"{step_metrics['prompt_tokens']}/{step_metrics['completion_tokens']}/{step_metrics['total_tokens']}"

            results_table.add_row(
                f"Step {idx}",
                title,
                result.route,
                str(step_metrics["call_count"]),
                tokens_str,
                f"{render_time:.2f}s",
                f"{step_latency:.2f}s",
                f"{pdf_size} B",
                "[green]PASSED[/green]",
            )
            console.print(
                f"  [green]Passed in {step_latency:.2f}s (Render: {render_time:.2f}s, LLM calls: {step_metrics['call_count']}, Tokens: {step_metrics['total_tokens']})[/green]"
            )

        except Exception as e:
            step_latency = round(time.time() - start_time, 2)
            step_metrics = llm_router.get_metrics()
            console.print(f"  [red]Step {idx} Failed: {e}[/red]")
            rollback_to_snapshot(session, session_store)

            log_entry["compilation_status"] = "FAILED"
            log_entry["error"] = str(e)
            log_entry["step_latency_seconds"] = step_latency
            log_entry["pdf_render_time_seconds"] = 0.0
            log_entry["llm_call_count"] = step_metrics["call_count"]
            log_entry["prompt_tokens"] = step_metrics["prompt_tokens"]
            log_entry["completion_tokens"] = step_metrics["completion_tokens"]
            log_entry["total_tokens"] = step_metrics["total_tokens"]

            tokens_str = f"{step_metrics['prompt_tokens']}/{step_metrics['completion_tokens']}/{step_metrics['total_tokens']}"

            results_table.add_row(
                f"Step {idx}",
                title,
                log_entry.get("route", "error"),
                str(step_metrics["call_count"]),
                tokens_str,
                "0.0s",
                f"{step_latency:.2f}s",
                "0 B",
                "[red]FAILED[/red]",
            )

        full_logs.append(log_entry)

    # Print summary table
    console.print("\n")
    console.print(results_table)

    # Master aggregated metrics across all steps
    tot_llm_calls = sum(e.get("llm_call_count", 0) for e in full_logs)
    tot_prompt_tokens = sum(e.get("prompt_tokens", 0) for e in full_logs)
    tot_completion_tokens = sum(e.get("completion_tokens", 0) for e in full_logs)
    tot_tokens = sum(e.get("total_tokens", 0) for e in full_logs)
    tot_step_time = round(sum(e.get("step_latency_seconds", 0.0) for e in full_logs), 2)
    tot_render_time = round(sum(e.get("pdf_render_time_seconds", 0.0) for e in full_logs), 2)

    # Save master JSON log
    master_log_file = out_dir / "full_execution_log.json"
    log_payload = {
        "session_id": session.session_id,
        "template": "custom_ayush_resume",
        "provider": "groq",
        "model": groq_model,
        "total_steps": len(changes),
        "successful_steps": sum(
            1 for entry in full_logs if entry.get("compilation_status") == "SUCCESS"
        ),
        "total_pipeline_time_seconds": tot_step_time,
        "total_pdf_render_time_seconds": tot_render_time,
        "total_llm_calls": tot_llm_calls,
        "total_prompt_tokens": tot_prompt_tokens,
        "total_completion_tokens": tot_completion_tokens,
        "total_tokens": tot_tokens,
        "steps": full_logs,
    }
    master_log_file.write_text(json.dumps(log_payload, indent=2), encoding="utf-8")

    # Generate summary report markdown in output directory
    report_file = out_dir / "summary_report.md"
    report_md = f"""# Test Execution Summary Report - Ayush Resume 10-Change Suite

- **Template**: Ayush Agarwal Custom LaTeX Resume (`Anubhav Singh` base)
- **LLM Provider**: Groq (`{groq_model}`)
- **Total Steps**: {len(changes)}
- **Successful Steps**: {sum(1 for entry in full_logs if entry.get("compilation_status") == "SUCCESS")}
- **Total Execution Time**: `{tot_step_time} seconds`
- **Total PDF Render Time**: `{tot_render_time} seconds`
- **Total LLM Calls**: `{tot_llm_calls}`
- **Total Tokens Consumed**: `{tot_tokens}` (`{tot_prompt_tokens}` prompt / `{tot_completion_tokens}` completion)
- **Output Directory**: `{out_dir}`

## Step Metrics Breakdown

"""
    for entry in full_logs:
        status_icon = "✅" if entry.get("compilation_status") == "SUCCESS" else "❌"
        report_md += f"### Step {entry['step_number']}: {entry['title']} {status_icon}\n"
        report_md += f"- **Prompt**: `{entry['prompt']}`\n"
        report_md += f"- **Route**: `{entry.get('route', 'N/A')}`\n"
        report_md += f"- **Zones Changed**: `{entry.get('zones_changed', [])}`\n"
        report_md += f"- **Status**: `{entry.get('compilation_status')}`\n"
        report_md += f"- **PDF Size**: `{entry.get('pdf_size_bytes', 0)} bytes` (`{entry.get('pdf_file')}`)\n"
        report_md += f"- **Step Time**: `{entry.get('step_latency_seconds')} seconds`\n"
        report_md += f"- **PDF Render Time**: `{entry.get('pdf_render_time_seconds')} seconds`\n"
        report_md += f"- **LLM Call Count**: `{entry.get('llm_call_count')} calls`\n"
        report_md += f"- **Token Usage**: `{entry.get('total_tokens')} total` (`{entry.get('prompt_tokens')}` prompt / `{entry.get('completion_tokens')}` completion)\n\n"

    report_file.write_text(report_md, encoding="utf-8")

    console.print(f"\n[bold green]Master JSON log saved to: {master_log_file}[/bold green]")
    console.print(f"[bold green]Summary Markdown report saved to: {report_file}[/bold green]")

    # Assert overall pipeline success
    failed_steps = [
        entry["step_number"]
        for entry in full_logs
        if entry.get("compilation_status") != "SUCCESS"
    ]
    assert not failed_steps, f"Pipeline failed on steps: {failed_steps}"


if __name__ == "__main__":
    test_custom_resume_10_changes()
