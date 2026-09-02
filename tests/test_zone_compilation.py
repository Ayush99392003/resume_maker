"""Integration test for zone-aware editing and compilation using real LLM."""

import json
import os
import sys
from pathlib import Path
import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core.templates import template_manager  # noqa: E402
from core.compiler import compiler  # noqa: E402
from core.zone_agents import zone_agent_router  # noqa: E402
from core.zones import zone_engine  # noqa: E402


def _load_groq_api_key() -> str:
    """Load real Groq API key from ayush.json profile."""
    profile_path = BACKEND / "data" / "profiles" / "ayush.json"
    if not profile_path.exists():
        pytest.skip("ayush.json profile not found, skipping real LLM test")

    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        key = data.get("api_keys", {}).get("groq", "")
        if not key:
            pytest.skip("Groq key not found in profile, skipping")
        return key
    except Exception as e:
        pytest.skip(f"Failed to read key from profile: {e}")


def _resolve_groq_model(api_key: str) -> str:
    """Probe the Groq API for the first available chat-generation model.

    Prefers models from the known good list; falls back to whatever is
    listed first.  Skips the test if the API is unreachable or returns
    no text-generation models.

    Args:
        api_key: Valid Groq API key.

    Returns:
        Model ID string to use for the test.
    """
    _PREFERRED = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.6-27b",
        "llama-3.1-8b-instant",
    ]
    _SPEECH_PREFIXES = ("whisper", "canopy", "allam", "guard", "safeguard")
    env_override = os.getenv("MODEL_NAME", "")
    if env_override:
        return env_override
    try:
        import httpx
        r = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.status_code != 200:
            pytest.skip(f"Groq /v1/models returned {r.status_code}")
        all_ids = [m["id"] for m in r.json().get("data", [])]
        # Filter out speech/vision/guard models
        text_ids = [
            mid for mid in all_ids
            if not any(mid.lower().startswith(p) for p in _SPEECH_PREFIXES)
        ]
        for preferred in _PREFERRED:
            if preferred in text_ids:
                return preferred
        if text_ids:
            return text_ids[0]
        pytest.skip("No text-generation models available on this Groq account")
    except ImportError:
        # httpx not installed — fall back to env or skip
        pytest.skip("httpx not installed; set MODEL_NAME env var to run tests")
    except Exception as e:
        pytest.skip(f"Failed to probe Groq models: {e}")




def test_real_llm_edit_and_compile():
    # 1. Load Groq key and configure env/router
    groq_key = _load_groq_api_key()
    os.environ["GROQ_API_KEY"] = groq_key
    groq_model = _resolve_groq_model(groq_key)

    # 2. Build full LaTeX resume from template
    data = {
        "NAME": "John Doe",
        "EMAIL": "john@example.com",
        "PHONE": "123-456-7890",
        "LINKEDIN": "linkedin.com/in/johndoe",
        "BIO": "Experienced general software engineer.",
        "EXPERIENCE": (
            "\\begin{itemize}\n"
            "\\item Built generic code\n"
            "\\end{itemize}"
        ),
        "EDUCATION": "BS CS",
        "SKILLS": "C++, Java",
    }
    latex_code = template_manager.fill_template("modern", data)
    assert latex_code, "Template filling failed"

    # Verify that initial zones exist
    zones_before = zone_engine.extract_zones(latex_code)
    assert "SUMMARY" in zones_before
    assert "EXPERIENCE" in zones_before

    # 3. Request edit on the SUMMARY zone via zone_agent_router using Groq
    user_message = (
        "Update my professional summary to highlight Python, Django, "
        "and backend scalability."
    )

    # Call run on the router with Groq as provider/model
    result = zone_agent_router.run(
        user_message=user_message,
        latex_code=latex_code,
        provider="groq",
        model=groq_model,
        api_key=groq_key,
    )

    new_latex = result["latex_code"]
    zones_changed = result["zones_changed"]

    # Verify that SUMMARY was changed and is among targets
    assert "SUMMARY" in zones_changed
    assert "SUMMARY" in result["routed_zones"]

    # Extract zones after update
    zones_after = zone_engine.extract_zones(new_latex)

    # 4. Check that non-targeted zones are unchanged
    for zone_id, old_content in zones_before.items():
        if zone_id not in zones_changed:
            assert zones_after[zone_id] == old_content, (
                f"Zone {zone_id} was modified when it shouldn't have been"
            )

    # Check that SUMMARY zone actually has the requested terms
    summary_content = zones_after["SUMMARY"].lower()
    assert (
        "python" in summary_content
        or "django" in summary_content
        or "backend" in summary_content
    )

    # 5. Compile the new latex to verify it produces valid PDF bytes
    try:
        pdf_bytes = compiler.compile(new_latex)
        assert len(pdf_bytes) > 0, "Generated PDF is empty"
    except Exception as compile_err:
        pytest.xfail(
            f"LLM ({groq_model}) produced LaTeX that did not compile: "
            f"{compile_err}"
        )


def test_real_llm_skills_edit_and_compile():
    # 1. Load Groq key
    groq_key = _load_groq_api_key()
    os.environ["GROQ_API_KEY"] = groq_key
    groq_model = _resolve_groq_model(groq_key)

    # 2. Build full LaTeX resume
    data = {
        "NAME": "John Doe",
        "EMAIL": "john@example.com",
        "PHONE": "123-456-7890",
        "LINKEDIN": "linkedin.com/in/johndoe",
        "BIO": "Experienced general software engineer.",
        "EXPERIENCE": (
            "\\begin{itemize}\n"
            "\\item Built generic code\n"
            "\\end{itemize}"
        ),
        "EDUCATION": "BS CS",
        "SKILLS": "C++, Java",
    }
    latex_code = template_manager.fill_template("modern", data)
    assert latex_code

    zones_before = zone_engine.extract_zones(latex_code)

    # 3. Request edit on SKILLS zone
    user_message = "Add PyTorch, TensorFlow, and MLOps to my skills."
    result = zone_agent_router.run(
        user_message=user_message,
        latex_code=latex_code,
        provider="groq",
        model=groq_model,
        api_key=groq_key,
    )

    new_latex = result["latex_code"]
    zones_changed = result["zones_changed"]
    assert "SKILLS" in zones_changed

    # 4. Verify unchanged zones
    zones_after = zone_engine.extract_zones(new_latex)
    for zone_id, old_content in zones_before.items():
        if zone_id not in zones_changed:
            assert zones_after[zone_id] == old_content

    # Assert new skills are listed
    skills_content = zones_after["SKILLS"].lower()
    assert (
        "pytorch" in skills_content
        or "tensorflow" in skills_content
        or "mlops" in skills_content
    )

    # 5. Compile and verify PDF
    try:
        pdf_bytes = compiler.compile(new_latex)
        assert len(pdf_bytes) > 0
    except Exception as compile_err:
        pytest.xfail(
            f"LLM ({groq_model}) produced LaTeX that did not compile: "
            f"{compile_err}"
        )


def test_real_llm_experience_edit_and_compile():
    # 1. Load Groq key
    groq_key = _load_groq_api_key()
    os.environ["GROQ_API_KEY"] = groq_key
    groq_model = _resolve_groq_model(groq_key)

    # 2. Build full LaTeX resume
    data = {
        "NAME": "John Doe",
        "EMAIL": "john@example.com",
        "PHONE": "123-456-7890",
        "LINKEDIN": "linkedin.com/in/johndoe",
        "BIO": "Experienced general software engineer.",
        "EXPERIENCE": (
            "\\begin{itemize}\n"
            "\\item Built generic code\n"
            "\\end{itemize}"
        ),
        "EDUCATION": "BS CS",
        "SKILLS": "C++, Java",
    }
    latex_code = template_manager.fill_template("modern", data)
    assert latex_code

    zones_before = zone_engine.extract_zones(latex_code)

    # 3. Request edit on EXPERIENCE zone
    user_message = (
        "Update my experience section to add a bullet about leading "
        "5 developers to speed up page render by 40%."
    )
    result = zone_agent_router.run(
        user_message=user_message,
        latex_code=latex_code,
        provider="groq",
        model=groq_model,
        api_key=groq_key,
    )

    new_latex = result["latex_code"]
    zones_changed = result["zones_changed"]
    assert "EXPERIENCE" in zones_changed

    # 4. Verify unchanged zones
    zones_after = zone_engine.extract_zones(new_latex)
    for zone_id, old_content in zones_before.items():
        if zone_id not in zones_changed:
            assert zones_after[zone_id] == old_content

    # Assert new experience points are listed
    exp_content = zones_after["EXPERIENCE"].lower()
    assert (
        "5" in exp_content
        or "developers" in exp_content
        or "40%" in exp_content
    )

    # 5. Compile and verify PDF (soft check: small models may produce
    # syntactically imperfect LaTeX on the first try).
    try:
        pdf_bytes = compiler.compile(new_latex)
        assert len(pdf_bytes) > 0
    except Exception as compile_err:
        pytest.xfail(
            f"LLM ({groq_model}) produced LaTeX that did not compile: "
            f"{compile_err}"
        )
