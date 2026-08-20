"""E2E pipeline test with 5 realistic, challenging user changes.

Tests the full orchestrator, zone agent routing, Pydantic guardrails,
LaTeX assembly, softening, fixer retry loop, and PDF compilation.
"""

import json
import os
import sys
from pathlib import Path

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


def get_groq_key_and_model():
    profile = BACKEND / "data" / "profiles" / "ayush.json"
    key = json.loads(profile.read_text(encoding="utf-8"))["api_keys"]["groq"]
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
    raise RuntimeError("No working model found on Groq")


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
            fix_update = ai_agent.fix_latex_error(
                current_latex,
                e.logs,
                provider=provider,
                model=model,
                api_key=api_key,
            )
            current_latex = fix_update.latex_code
    raise Exception("Max retries exceeded in compilation loop.")


def test_5_changes_pipeline():
    groq_key, groq_model = get_groq_key_and_model()

    # 1. Initialize session with modern template
    template = template_manager.get_template("modern")
    doc = latex_to_zones(template)
    session = session_store.create(
        template_name="modern",
        title="5-Change E2E Pipeline Verification",
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

    # 5 diverse real-world changes testing different zones & edge cases:
    # 1: Initial Bio fill (all zones)
    # 2: Skills update with special characters (&, $, %, /)
    # 3: Experience update with metrics, numbers, R&D
    # 4: Education & honors update
    # 5: Summary polish with financial metrics ($50k+) & percentages
    changes = [
        (
            "Change 1: Initial Bio Fill",
            (
                "My name is Ayush Sharma, email: ayush@example.com, "
                "phone: +1-555-0199, LinkedIn: linkedin.com/in/ayushs. "
                "I am a Senior Backend Engineer with 6 years of experience in "
                "Python, FastAPI, distributed systems, & cloud computing."
            ),
        ),
        (
            "Change 2: Skills with Special Symbols (&, $, %)",
            (
                "Update my Skills section to: "
                "Languages: Python, Go, C++, SQL & Bash. "
                "Frameworks: FastAPI, Django, PyTorch, React. "
                "Cloud & Tools: AWS (S3/EC2), Docker, Kubernetes, CI/CD, "
                "Git & LaTeX. Cost optimization: saved $120k & 40% latency."
            ),
        ),
        (
            "Change 3: Experience with Metrics & R&D",
            (
                "In my Experience section, update the top job to: "
                "Senior Software Engineer at Acme Cloud (2022 - Present). "
                "Bullet 1: Architected high-throughput R&D microservices "
                "handling 50M+ requests/day with 99.99% uptime. "
                "Bullet 2: Reduced infrastructure cost by 35% (saving $85,000/yr) "
                "by optimizing database queries & caching layer."
            ),
        ),
        (
            "Change 4: Education & Honors",
            (
                "Update Education to: Bachelor of Technology in Computer Science "
                "from Apex Institute of Technology (2016 - 2020), GPA: 3.9/4.0. "
                "Dean's List & Outstanding Senior Capstone Award."
            ),
        ),
        (
            "Change 5: Summary Polish with LaTeX edge cases",
            (
                "Update my Summary to: "
                "Results-driven Senior Engineer specializing in 100% scalable "
                "backend architecture, R&D prototyping, and async processing. "
                "Proven track record of cutting AWS bill by $50k+ while "
                "maintaining sub-50ms p99 latency."
            ),
        ),
    ]

    results_table = Table(title="E2E Pipeline 5-Change Verification Results")
    results_table.add_column("Step", style="bold cyan")
    results_table.add_column("Change Description", style="white")
    results_table.add_column("Route", style="yellow")
    results_table.add_column("Zones Changed", style="magenta")
    results_table.add_column("Compile Status", style="bold green")
    results_table.add_column("PDF Size", style="blue")

    for idx, (title, prompt) in enumerate(changes, 1):
        console.rule(f"[bold green]Executing {title}[/bold green]")
        console.print(f"[italic]Prompt: {prompt}[/italic]")

        # 1. Take snapshot before edit
        take_snapshot(session, session_store)

        # 2. Append user message
        session_store.append_message(session, role="user", content=prompt)
        session = session_store.get(session.session_id)
        history = [m.model_dump() for m in session.messages[:-1]]

        is_first_fill = (idx == 1)

        # 3. Run chat turn through real ai_agent & orchestrator
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

        console.print(f"Agent route: {result.route}")
        console.print(f"Zones changed: {result.zones_changed}")

        # 4. Sync session if document updated
        final_latex = result.latex_code
        if result.zone_document:
            doc = ZoneDocument(**result.zone_document)
            sync_session_from_document(session, doc)
            final_latex = session.latex_code

        # 5. Compile check using compile_with_retry (same as /chat endpoint)
        try:
            pdf_bytes, final_latex = compile_with_retry(
                final_latex,
                provider="groq",
                model=groq_model,
                api_key=groq_key,
            )
            pdf_size = len(pdf_bytes)
            compile_ok = True
            session.latex_code = final_latex
            console.print(f"[green]Compiled successfully ({pdf_size} bytes)[/green]")
        except Exception as e:
            console.print(f"[red]Compile failed: {e}[/red]")
            rolled = rollback_to_snapshot(session, session_store)
            console.print(f"[yellow]Rollback executed: {rolled}[/yellow]")
            compile_ok = False
            pdf_size = 0

        session_store.save(session)

        status_str = "[green]PASSED (Compiled)[/green]" if compile_ok else "[red]FAILED[/red]"
        results_table.add_row(
            f"Step {idx}",
            title,
            result.route,
            str(result.zones_changed),
            status_str,
            f"{pdf_size} B" if compile_ok else "0 B",
        )

        assert compile_ok, f"Compile failed on {title}"

    console.print("\n")
    console.print(results_table)


if __name__ == "__main__":
    test_5_changes_pipeline()
