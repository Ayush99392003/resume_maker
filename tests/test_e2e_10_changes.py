"""E2E pipeline test with 10 realistic, challenging user changes.

Tests full orchestrator planning, zone agent routing, Pydantic guardrails,
LaTeX assembly, line indexing, fixer retry loop, and PDF compilation across 10 steps.
Exports full structured execution logs to backend/data/logs/e2e_10_changes_log.json.
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

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.ai_agent import ai_agent
from core.compiler import CompilationError, compiler
from core.latex_to_zones import latex_to_zones
from core.session_store import (
    session_store,
    take_snapshot,
    rollback_to_snapshot,
)
from core.templates import template_manager
from core.zone_document import (
    ZoneDocument,
    ensure_full_document,
    sync_session_from_document,
)
from llm_router import ChatMessage, llm_router
from rich.console import Console
from rich.table import Table

console = Console(highlight=False)


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
) -> tuple[bytes, str]:
    """Compile LaTeX; on failure ask fixer agent to repair."""
    current_latex = ensure_full_document(latex_code or "")
    for attempt in range(max_retries + 1):
        try:
            pdf = compiler.compile(current_latex)
            return (pdf, current_latex)
        except CompilationError as e:
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


def test_10_changes_pipeline():
    """Run 10 sequential resume edits, compile each step, and log full JSON traces."""
    groq_key, groq_model = get_groq_key_and_model()

    # 1. Initialize session with modern template
    template = template_manager.get_template("modern")
    doc = latex_to_zones(template)
    session = session_store.create(
        template_name="modern",
        title="10-Change Real LLM E2E Pipeline Log Suite",
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

    # 10 diverse, comprehensive user changes covering all sections & operations
    changes = [
        (
            "Change 1: Initial Bio Fill",
            (
                "My name is Ayush Sharma, email: ayush@example.com, "
                "phone: +1-555-0199, LinkedIn: linkedin.com/in/ayushs, GitHub: github.com/ayushs. "
                "I am a Senior Backend & Systems Engineer with 6+ years of experience in "
                "Python, Distributed Systems, Go, & Cloud Infrastructure."
            ),
        ),
        (
            "Change 2: Contact & Header Details Update",
            (
                "Update my header contact details: set location to San Francisco, CA, "
                "email to ayush.sharma@techcorp.io, and add portfolio site https://ayushs.dev"
            ),
        ),
        (
            "Change 3: Skills Update with LaTeX Special Symbols (&, $, %, _, #)",
            (
                "Update my Skills section to: "
                "Languages: Python, Go, C++, SQL & Bash. "
                "Frameworks: FastAPI, PyTorch, Django & React. "
                "DevOps & Tools: AWS (S3/EC2/EKS), Docker, Kubernetes, CI/CD, #Git, & ~LaTeX. "
                "Cost Efficiency: Saved $120k/yr & reduced infrastructure overhead by 40%."
            ),
        ),
        (
            "Change 4: Experience Bullet Points & Financial Metrics",
            (
                "In my Work Experience section, update the primary lead engineer role: "
                "Lead Backend Engineer at CloudScale Technologies (2022 - Present). "
                "Bullet 1: Built high-throughput microservices processing 100M+ events/day with 99.99% uptime. "
                "Bullet 2: Reduced database query latency by 55% (saving $95,000/yr in AWS costs). "
                "Bullet 3: Led an engineering team of 8 across R&D initiatives."
            ),
        ),
        (
            "Change 5: Projects Section Enhancement",
            (
                "Add a Projects section (or update existing projects) with: "
                "Project: ResumeMaker AI - Open-source automated LaTeX builder using python & asyncio. "
                "Described as: Designed multi-agent orchestrator with Pydantic validation & Tectonic auto-healing compiler. "
                "Achieved 10,000+ GitHub stars and 200k monthly downloads."
            ),
        ),
        (
            "Change 6: Education & Honors Update",
            (
                "Update Education section: "
                "Degree: M.S. in Computer Science from Stanford University (2020 - 2022), GPA: 3.95/4.0. "
                "B.S. in Computer Engineering from UC Berkeley (2016 - 2020), High Honors. "
                "Awards: Dean's Honor List, National Science Foundation Fellow."
            ),
        ),
        (
            "Change 7: Executive Summary Refinement",
            (
                "Polish my Summary section to: "
                "Results-oriented Senior Systems Engineer with 6+ years specializing in "
                "scalable cloud architecture, high-throughput microservices, and AI workflow automation. "
                "Track record of cutting cloud expenditures by $150k+ while ensuring sub-30ms p99 response times."
            ),
        ),
        (
            "Change 8: Add Custom Zone (Certifications & Publications)",
            (
                "Add a new zone for Certifications & Honors under Experience with content: "
                "AWS Certified Solutions Architect - Professional (2023). "
                "Published paper: 'Scaling Distributed AI Workloads in Heterogeneous Clusters' (IEEE 2024)."
            ),
        ),
        (
            "Change 9: Reorder Zones (Swap Skills and Experience)",
            (
                "Reorder the resume sections so that Skills appears directly after Summary, "
                "followed by Work Experience and Education."
            ),
        ),
        (
            "Change 10: Final Polish & Formatting Check",
            (
                "Final polish on the Skills zone: group items under bold headers like "
                "Programming, Cloud & DevOps, AI & Data Engineering, and Key Metrics."
            ),
        ),
    ]

    results_table = Table(title="10-Change Real LLM E2E Pipeline Verification")
    results_table.add_column("Step", style="bold cyan")
    results_table.add_column("Title", style="white")
    results_table.add_column("Route", style="yellow")
    results_table.add_column("Zones Changed", style="magenta")
    results_table.add_column("Status", style="bold green")
    results_table.add_column("PDF Size", style="blue")
    results_table.add_column("Latency (s)", style="bright_black")

    full_logs: List[Dict[str, Any]] = []

    for idx, (title, prompt) in enumerate(changes, 1):
        start_time = time.time()
        console.rule(f"[bold green]Step {idx}/10: {title}[/bold green]")
        console.print(f"[italic]Prompt: {prompt}[/italic]")

        before_latex = session.latex_code
        take_snapshot(session, session_store)

        session_store.append_message(session, role="user", content=prompt)
        session = session_store.get(session.session_id)
        history = [m.model_dump() for m in session.messages[:-1]]

        is_first_fill = (idx == 1)

        log_entry: Dict[str, Any] = {
            "step_number": idx,
            "title": title,
            "prompt": prompt,
            "is_first_fill": is_first_fill,
            "before_latex": before_latex,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            result = ai_agent.run_chat_turn(
                user_message=prompt,
                latex_code=session.latex_code,
                template_latex=template,
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

            log_entry["after_latex"] = final_latex

            # PDF Compilation check
            pdf_bytes, compiled_latex = compile_with_retry(
                final_latex,
                provider="groq",
                model=groq_model,
                api_key=groq_key,
            )
            pdf_size = len(pdf_bytes)
            elapsed = round(time.time() - start_time, 2)

            session.latex_code = compiled_latex
            session_store.save(session)

            log_entry["compilation_status"] = "SUCCESS"
            log_entry["pdf_size_bytes"] = pdf_size
            log_entry["latency_seconds"] = elapsed
            log_entry["final_compiled_latex"] = compiled_latex

            results_table.add_row(
                f"Step {idx}",
                title,
                result.route,
                str(result.zones_changed),
                "[green]PASSED[/green]",
                f"{pdf_size} B",
                f"{elapsed}s",
            )
            console.print(f"  [green]Passed in {elapsed}s ({pdf_size} bytes PDF)[/green]")

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            console.print(f"  [red]Step {idx} Failed: {e}[/red]")
            rollback_to_snapshot(session, session_store)

            log_entry["compilation_status"] = "FAILED"
            log_entry["error"] = str(e)
            log_entry["latency_seconds"] = elapsed

            results_table.add_row(
                f"Step {idx}",
                title,
                log_entry.get("route", "error"),
                str(log_entry.get("zones_changed", [])),
                "[red]FAILED[/red]",
                "0 B",
                f"{elapsed}s",
            )

        full_logs.append(log_entry)

    # Print summary table
    console.print("\n")
    console.print(results_table)

    # Save full JSON execution log to file
    log_dir = BACKEND / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "e2e_10_changes_log.json"

    log_payload = {
        "session_id": session.session_id,
        "template": "modern",
        "provider": "groq",
        "model": groq_model,
        "total_steps": len(changes),
        "successful_steps": sum(
            1 for entry in full_logs if entry.get("compilation_status") == "SUCCESS"
        ),
        "steps": full_logs,
    }

    log_file.write_text(json.dumps(log_payload, indent=2), encoding="utf-8")
    console.print(f"\n[bold green]Full JSON logs written to: {log_file}[/bold green]")

    # Assert overall pipeline success
    failed_steps = [
        entry["step_number"]
        for entry in full_logs
        if entry.get("compilation_status") != "SUCCESS"
    ]
    assert not failed_steps, f"Pipeline failed on steps: {failed_steps}"


if __name__ == "__main__":
    test_10_changes_pipeline()
