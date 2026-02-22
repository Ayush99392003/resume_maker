import json
from typing import List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai

# Side effect of importing config: genai.configure() is called
# Side effect: importing config leads to genai.configure() being called.
try:
    import core.config  # noqa: F401
except ImportError:
    from . import config  # noqa: F401


class ResumeUpdate(BaseModel):
    """Schema for individual LaTeX resume updates."""

    latex_code: str = Field(..., description="The LaTeX code generated.")
    summary_of_changes: str = Field(..., description="Brief explanation.")
    is_complete_document: bool = Field(..., description="True if full doc.")


class ProposalVariant(BaseModel):
    """A single proposed variation of a change."""

    id: str
    intent: str
    latex_code: str
    summary: str


class RefinementProposal(BaseModel):
    """A collection of proposals for a single user request."""

    original_context: str
    proposals: List[ProposalVariant]


class AIAgent:
    """Handles AI interactions for LaTeX resume management using Gemini."""

    def __init__(self, model: str = "gemini-1.5-pro"):
        self.model_name = model
        self.model = genai.GenerativeModel(
            model_name=model,
            generation_config={"response_mime_type": "application/json"},
        )

    def _call_gemini(
        self, system_prompt: str, user_prompt: str, schema_class
    ) -> any:
        """Helper to call Gemini and parse JSON response."""
        prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
        response = self.model.generate_content(prompt)
        try:
            data = json.loads(response.text)
            return schema_class(**data)
        except Exception as e:
            raise Exception(f"Failed to parse Gemini response: {str(e)}")

    def generate_initial_resume(
        self, bio: str, template_latex: str
    ) -> ResumeUpdate:
        """Generates initial resume."""
        system = (
            "You are a LaTeX expert. Fill the provided LaTeX template with "
            "data from the user bio. Return a JSON matching ResumeUpdate."
        )
        user = f"Template:\n{template_latex}\n\nBio:\n{bio}"
        return self._call_gemini(system, user, ResumeUpdate)

    def generate_edit_proposals(
        self,
        current_latex: str,
        command: str,
        section_name: Optional[str] = None,
    ) -> RefinementProposal:
        """Generates multiple proposed variations for an edit."""
        context = f"Section: {section_name}" if section_name else "Full Doc"
        system = (
            "Generate 3 distinct variations for the requested edit: "
            "1. 'Standard' (Safe & Professional), 2. 'Creative' (Dynamic), "
            "3. 'Concise' (Space-saving). Return a RefinementProposal JSON. "
            "Each proposal must contain ONLY the new LaTeX for the "
            "target area."
        )
        user = (
            f"Context: {context}\n"
            f"LaTeX:\n{current_latex}\n"
            f"Command: {command}"
        )
        return self._call_gemini(system, user, RefinementProposal)

    def fix_latex_error(
        self, broken_latex: str, error_logs: str
    ) -> ResumeUpdate:
        """Fixes LaTeX error."""
        system = (
            "Repair the broken LaTeX code based on the provided logs. "
            "Return the FULL document in the JSON response."
        )
        user = f"Logs:\n{error_logs}\n\nBroken LaTeX:\n{broken_latex}"
        return self._call_gemini(system, user, ResumeUpdate)

    def squeeze_layout(self, latex_code: str) -> ResumeUpdate:
        """Optimizes LaTeX layout to fit more content (Page Squeezer)."""
        system = (
            "Optimize the provided LaTeX code to fit more content. "
            "Adjust margins, line spacing, and font sizes as needed. "
            "Return the optimized FULL LaTeX in a ResumeUpdate JSON. "
            "Keep it professional and readable."
        )
        user = f"LaTeX Code:\n{latex_code}"
        return self._call_gemini(system, user, ResumeUpdate)


ai_agent = AIAgent()
