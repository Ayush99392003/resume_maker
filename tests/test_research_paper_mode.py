"""Tests for Academic Research Paper Mode, agents, templates, and sessions."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.latex_to_zones import latex_to_zones
from core.research_agents import (
    AbstractKeywordsAgent,
    AppendixAgent,
    ConclusionAgent,
    DiscussionAgent,
    ExperimentsAgent,
    IntroductionAgent,
    MethodologyAgent,
    ReferencesAgent,
    RelatedWorkAgent,
    TitleAuthorsAgent,
    research_agent_router,
)
from core.session_store import session_store
from core.templates import template_manager
from core.zone_agents import zone_agent_router


def test_research_agents_registered():
    """Verify all 10 academic agents are registered in routers."""
    expected_agents = [
        TitleAuthorsAgent,
        AbstractKeywordsAgent,
        IntroductionAgent,
        RelatedWorkAgent,
        MethodologyAgent,
        ExperimentsAgent,
        DiscussionAgent,
        ConclusionAgent,
        ReferencesAgent,
        AppendixAgent,
    ]
    for agent_cls in expected_agents:
        zid = agent_cls.zone_id
        assert zid in research_agent_router.agents
        assert zid in zone_agent_router.agents


def test_academic_zone_semantic_resolution():
    """Verify semantic descriptions resolve to research agents."""
    test_cases = [
        ("Title and authors", "predefined_title_authors", "TITLE_AUTHORS"),
        ("Abstract", "predefined_abstract", "ABSTRACT"),
        ("Keywords / Index terms", "predefined_keywords", "ABSTRACT"),
        ("Introduction", "predefined_introduction", "INTRODUCTION"),
        ("Related work", "predefined_related_work", "RELATED_WORK"),
        ("Methodology", "predefined_methodology", "METHODOLOGY"),
        ("Experiments and results", "predefined_experiments", "EXPERIMENTS"),
        ("Discussion", "predefined_discussion", "DISCUSSION"),
        ("Conclusion", "predefined_conclusion", "CONCLUSION"),
        ("References", "predefined_references", "REFERENCES"),
        ("Appendix", "predefined_appendix", "APPENDIX"),
    ]
    for desc, kind, expected_id in test_cases:
        agent = zone_agent_router._resolve_agent(
            "1",
            zone_catalog=[{"zone_no": 1, "description": desc, "kind": kind}],
        )
        assert agent.zone_id == expected_id, (
            f"Failed for {desc}: expected {expected_id}, got {agent.zone_id}"
        )


def test_academic_starter_templates_load_and_parse():
    """Verify all 4 academic starter templates load and produce zones."""
    templates = [
        "paper_starter",
        "ieee_starter",
        "acm_starter",
        "arxiv_starter",
    ]
    for tpl_name in templates:
        tex_content = template_manager.get_template(tpl_name)
        assert len(tex_content) > 0, f"Template {tpl_name} was empty"
        doc = latex_to_zones(tex_content)
        assert len(doc.zones) >= 7, (
            f"Template {tpl_name} only produced {len(doc.zones)} zones"
        )
        assert len(doc.zone_order) == len(doc.zones)
        assert "\\begin{document}" in doc.header
        assert "\\end{document}" in doc.footer
        assembled = doc.assemble()
        assert "% ZONE:1:START" in assembled
        assert f"% ZONE:{len(doc.zones)}:END" in assembled


def test_session_store_document_mode():
    """Verify session_store stores and retrieves document_mode properly."""
    session = session_store.create(
        title="Test Research Paper",
        template_name="paper_starter",
        document_mode="research_paper",
        latex_code="\\documentclass{article}\\begin{document}\\end{document}",
    )
    try:
        assert session.document_mode == "research_paper"
        loaded = session_store.get(session.session_id)
        assert loaded is not None
        assert loaded.document_mode == "research_paper"

        sessions_list = session_store.list_sessions()
        found = next(
            (
                s
                for s in sessions_list
                if s["session_id"] == session.session_id
            ),
            None,
        )
        assert found is not None
        assert found.get("document_mode") == "research_paper"
    finally:
        session_store.delete(session.session_id)
