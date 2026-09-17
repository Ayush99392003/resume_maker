"""Scenario-based benchmarks and unit tests for tree-based tool routing.

Measures:
1. Routing decision accuracy across scenarios without regex.
2. Token consumption across tree branches.
3. Execution latency (ms) per scenario.
4. Token savings in structural vs content branches.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from core.chat_router import classify_route
from core.orchestrator import plan_intents
from core.zone_document import ZoneDocument, ZoneRecord
from llm_router import ChatMessage, LLMResponse, llm_router


@pytest.fixture
def sample_doc() -> ZoneDocument:
    """Standard 4-zone document for benchmarking."""
    return ZoneDocument(
        header="\\documentclass{article}\n\\begin{document}\n",
        footer="\\end{document}\n",
        zones=[
            ZoneRecord(
                zone_no=1,
                description="Header",
                kind="header",
                latex="% ZONE:1:START\n{\\Large \\textbf{Ayush Kumar}}\\\\ Email: ayush@example.com\n% ZONE:1:END\n",
            ),
            ZoneRecord(
                zone_no=2,
                description="Education",
                kind="education",
                latex="% ZONE:2:START\n\\section*{Education}\nVIT Bhopal University - B.Tech CSE (2020 - 2024)\n% ZONE:2:END\n",
            ),
            ZoneRecord(
                zone_no=3,
                description="Skills",
                kind="skills",
                latex="% ZONE:3:START\n\\section*{Skills}\nPython, PyTorch, LaTeX, FastAPI\n% ZONE:3:END\n",
            ),
            ZoneRecord(
                zone_no=4,
                description="Experience",
                kind="experience",
                latex="% ZONE:4:START\n\\section*{Experience}\nSoftware Engineer at Google\n% ZONE:4:END\n",
            ),
        ],
        zone_order=[1, 2, 3, 4],
        next_zone_no=5,
    )


class MockBenchProvider:
    """Deterministic LLM mock that records prompt length, tokens, and returns JSON."""

    def __init__(self):
        self.recorded_calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: str = "json",
    ) -> LLMResponse:
        full_prompt = " ".join(m.content for m in messages)
        prompt_tokens = max(10, len(full_prompt.split()))
        last_msg = messages[-1].content.lower()

        # Simulated intelligent responses based on content & prompt tools
        if "available structural tools" in full_prompt.lower():
            if "certificat" in last_msg or "add" in last_msg:
                content = json.dumps(
                    {
                        "tool": "add_zone",
                        "args": {
                            "title": "Certifications",
                            "after_zone_no": 2,
                            "at_start": False,
                        },
                        "reason": "user_wants_certifications_section",
                    }
                )
            elif "remove" in last_msg or "delete" in last_msg:
                content = json.dumps(
                    {
                        "tool": "remove_zone",
                        "args": {"zone_nos": [4]},
                        "reason": "user_wants_experience_removed",
                    }
                )
            elif "swap" in last_msg or "reorder" in last_msg:
                content = json.dumps(
                    {
                        "tool": "reorder_zones",
                        "args": {"swap": [2, 3]},
                        "reason": "user_wants_swap_zones",
                    }
                )
            else:
                content = json.dumps({"tool": "reorder_zones", "args": {}})
        elif "available content tools" in full_prompt.lower():
            if "docker" in last_msg or "skill" in last_msg:
                content = json.dumps(
                    {
                        "tool": "edit_zone_content",
                        "args": {
                            "zone_no": 3,
                            "instructions": "Add Docker and Kubernetes to skills",
                        },
                        "reason": "user_editing_skills",
                    }
                )
            elif "gpa" in last_msg or "education" in last_msg:
                content = json.dumps(
                    {
                        "tool": "edit_zone_content",
                        "args": {
                            "zone_no": 2,
                            "instructions": "Update GPA to 3.9",
                        },
                        "reason": "user_editing_education",
                    }
                )
            else:
                content = json.dumps(
                    {
                        "tool": "fill_resume",
                        "args": {"zone_nos": [1, 2, 3, 4]},
                        "reason": "user_pasting_bio",
                    }
                )
        else:
            # Main Router classification
            if any(w in last_msg for w in ("hello", "hi", "what sections", "help", "how does")):
                content = json.dumps(
                    {
                        "route": "direct_reply",
                        "reason": "conversational_chitchat_or_query",
                        "reply": (
                            "Hello! Your resume currently has 4 sections: "
                            "Header, Education, Skills, and Experience."
                        ),
                    }
                )
            elif any(
                w in last_msg
                for w in (
                    "certifications section",
                    "experience section",
                    "swap zone",
                    "add a certifications",
                    "remove the experience",
                    "delete the experience",
                )
            ):
                content = json.dumps(
                    {
                        "route": "structure",
                        "reason": "user_modifying_section_layout",
                    }
                )
            else:
                content = json.dumps(
                    {
                        "route": "content",
                        "reason": "user_modifying_text_content",
                    }
                )

        completion_tokens = max(5, len(content.split()))
        resp = LLMResponse(
            content=content,
            provider="mock_bench",
            model=model,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )
        self.recorded_calls.append(
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "prompt_text": full_prompt,
            }
        )
        return resp


@pytest.fixture(autouse=True)
def patch_llm_bench(monkeypatch):
    """Patch llm_router with deterministic benchmark provider."""
    bench_provider = MockBenchProvider()
    monkeypatch.setattr(llm_router, "get_provider", lambda *a, **kw: bench_provider)
    llm_router.reset_metrics()
    return bench_provider


# =========================================================================
# 1. SCENARIO UNIT TESTS
# =========================================================================


def test_scenario_1_conversational_direct_reply(sample_doc: ZoneDocument):
    """Scenario 1: Greetings & questions handled directly in Main Router with chat history."""
    history = [
        {"role": "user", "content": "Hi there!"},
        {"role": "assistant", "content": "Hello! How can I help with your resume?"},
    ]
    catalog = sample_doc.catalog()

    t0 = time.perf_counter()
    decision = classify_route(
        "What sections are in my resume?",
        catalog=catalog,
        history=history,
        target_zone=None,
        use_llm=True,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert decision.route == "direct_reply"
    assert "4 sections" in decision.reply
    assert elapsed_ms < 500  # Sub-second execution


def test_scenario_2_structure_add_zone(sample_doc: ZoneDocument):
    """Scenario 2: Add zone route -> structure tool adds section without loading LaTeX."""
    catalog = sample_doc.catalog()

    # Step A: Main router classifies
    decision = classify_route(
        "Add a certifications section under education",
        catalog=catalog,
        use_llm=True,
    )
    assert decision.route == "structure"

    # Step B: Tree planner calls structure tool
    plan = plan_intents(
        "Add a certifications section under education",
        sample_doc,
        is_first_fill=False,
        category="structure",
        provider=None,
        model=None,
        api_key=None,
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].intent == "add_zone"
    assert plan.steps[0].description == "Certifications"
    assert plan.steps[0].after_zone_no == 2


def test_scenario_3_structure_remove_zone(sample_doc: ZoneDocument):
    """Scenario 3: Remove zone route -> structure tool permanently removes entire section."""
    plan = plan_intents(
        "Delete the experience section",
        sample_doc,
        is_first_fill=False,
        category="structure",
        provider=None,
        model=None,
        api_key=None,
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].intent == "remove_zone"
    assert plan.steps[0].zone_nos == [4]


def test_scenario_4_structure_reorder_zones(sample_doc: ZoneDocument):
    """Scenario 4: Reorder zones -> structure tool swaps positions."""
    plan = plan_intents(
        "Swap zone 2 and zone 3",
        sample_doc,
        is_first_fill=False,
        category="structure",
        provider=None,
        model=None,
        api_key=None,
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].intent == "reorder"
    assert plan.steps[0].swap == [2, 3]


def test_scenario_5_content_edit_zone(sample_doc: ZoneDocument):
    """Scenario 5: Content edit -> routes to target zone without touching structure."""
    plan = plan_intents(
        "Add Docker and Kubernetes to skills",
        sample_doc,
        is_first_fill=False,
        category="content",
        provider=None,
        model=None,
        api_key=None,
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].intent == "edit"
    assert plan.steps[0].zone_nos == [3]


# =========================================================================
# 2. BENCHMARK SUITE (TIME & TOKENS ACROSS SCENARIOS)
# =========================================================================


def test_benchmark_scenarios_time_and_tokens(sample_doc: ZoneDocument, patch_llm_bench):
    """Benchmark table measuring time (ms) and tokens across all scenarios."""
    scenarios = [
        ("Conversational Query", "What sections do I have?", "direct_reply"),
        ("Structural Add Zone", "Add a certifications section under education", "structure"),
        ("Structural Remove Zone", "Remove the experience section", "structure"),
        ("Structural Reorder", "Swap zone 2 and zone 3", "structure"),
        ("Content Edit Zone", "Add Docker and Kubernetes to skills", "content"),
        ("Bio Data Fill", "Here is my bio: Ayush Kumar, Software Engineer at Google...", "content"),
    ]

    benchmark_results = []
    catalog = sample_doc.catalog()

    for name, user_msg, expected_category in scenarios:
        llm_router.reset_metrics()
        t_start = time.perf_counter()

        # Step 1: Route
        route_decision = classify_route(user_msg, catalog=catalog, use_llm=True)

        # Step 2: If structure or content, plan with tree
        if route_decision.route in ("structure", "content"):
            plan = plan_intents(
                user_msg,
                sample_doc,
                is_first_fill=False,
                category=route_decision.route,
                provider=None,
                model=None,
                api_key=None,
            )
            step_desc = plan.steps[0].intent if plan.steps else "clarify"
        else:
            step_desc = "direct_reply"

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        metrics = llm_router.get_metrics()

        benchmark_results.append(
            {
                "Scenario": name,
                "Route": route_decision.route,
                "Tool/Action": step_desc,
                "Calls": metrics["call_count"],
                "Prompt Tokens": metrics["prompt_tokens"],
                "Comp Tokens": metrics["completion_tokens"],
                "Total Tokens": metrics["total_tokens"],
                "Time (ms)": round(elapsed_ms, 2),
            }
        )

    # Print clean benchmark summary table
    print("\n" + "=" * 90)
    print("TREE-BASED ROUTER & TOOL BENCHMARK REPORT (TIME & TOKEN CONSUMPTION)")
    print("=" * 90)
    header = (
        f"{'Scenario':<26} | {'Route':<12} | {'Action':<14} | "
        f"{'Calls':<5} | {'Tokens':<8} | {'Time (ms)':<9}"
    )
    print(header)
    print("-" * 90)
    for r in benchmark_results:
        row = (
            f"{r['Scenario']:<26} | {r['Route']:<12} | {r['Tool/Action']:<14} | "
            f"{r['Calls']:<5} | {r['Total Tokens']:<8} | {r['Time (ms)']:<9}"
        )
        print(row)
    print("=" * 90 + "\n")

    # Assertions
    # Direct reply should consume 1 call and minimal tokens
    assert benchmark_results[0]["Route"] == "direct_reply"
    assert benchmark_results[0]["Calls"] == 1
    # Structural ops should use 2 small tree calls (router + structure tool)
    assert benchmark_results[1]["Route"] == "structure"
    assert benchmark_results[1]["Calls"] == 2
    # All scenarios execute in < 250ms with mock provider
    assert all(r["Time (ms)"] < 250 for r in benchmark_results)
