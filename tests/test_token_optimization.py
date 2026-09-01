"""Unit tests for token optimization, compact_digest, and fast-path zone routing."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from core.zone_document import ZoneDocument, ZoneRecord
from core.chat_router import classify_route
from core.orchestrator import plan_intents, _match_zone_by_text


@pytest.fixture
def sample_doc() -> ZoneDocument:
    doc = ZoneDocument(
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
    return doc


def test_compact_digest_excludes_active_zone(sample_doc: ZoneDocument):
    """compact_digest should exclude the active zone and produce 1 line per remaining zone."""
    digest = sample_doc.compact_digest(active_zone_no=3)
    assert "Zone 3" not in digest
    assert "Zone 1 [Header]" in digest
    assert "Zone 2 [Education]" in digest
    assert "Zone 4 [Experience]" in digest
    # Verify concise snippet format
    assert len(digest.splitlines()) == 3


def test_chat_router_target_zone_fast_path(sample_doc: ZoneDocument):
    """When target_zone is provided and not 'auto', chat_router must return orchestrator immediately."""
    route_dec = classify_route(
        "Make this more concise",
        catalog=sample_doc.catalog(),
        target_zone="skills",
        use_llm=False,
    )
    assert route_dec.route == "orchestrator"
    assert "target_zone_skills" in route_dec.reason


def test_orchestrator_target_zone_fast_path(sample_doc: ZoneDocument):
    """plan_intents with explicit target_zone should return OrchStep(intent='edit', zone_nos=[matched]) with 0 LLM calls."""
    # Test target_zone by name
    plan_skills = plan_intents(
        "Update python to 3.12",
        sample_doc,
        is_first_fill=False,
        target_zone="skills",
        provider=None,
        model=None,
        api_key=None,
    )
    assert plan_skills.steps[0].intent == "edit"
    assert plan_skills.steps[0].zone_nos == [3]
    assert plan_skills.reason == "user_target_skills"

    # Test target_zone by number
    plan_num = plan_intents(
        "Fix my degree",
        sample_doc,
        is_first_fill=False,
        target_zone="2",
        provider=None,
        model=None,
        api_key=None,
    )
    assert plan_num.steps[0].intent == "edit"
    assert plan_num.steps[0].zone_nos == [2]
    assert plan_num.reason == "user_target_2"

    # Test full rewrite chip
    plan_all = plan_intents(
        "Rewrite everything with new bio",
        sample_doc,
        is_first_fill=False,
        target_zone="full_rewrite",
        provider=None,
        model=None,
        api_key=None,
    )
    assert plan_all.steps[0].intent == "fill"
    assert plan_all.steps[0].zone_nos == [1, 2, 3, 4]


def test_orchestrator_keyword_rule_fast_path(sample_doc: ZoneDocument):
    """plan_intents with unambiguous keyword targeting single section should fast-path without LLM."""
    plan = plan_intents(
        "Add Docker to skills",
        sample_doc,
        is_first_fill=False,
        target_zone="auto",
        provider=None,
        model=None,
        api_key=None,
    )
    assert plan.steps[0].intent == "edit"
    assert plan.steps[0].zone_nos == [3]
    assert plan.reason == "rule_single_zone"
