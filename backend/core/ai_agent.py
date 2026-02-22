import os
import json
from typing import List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Initialize Gemini Client
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


class ResumeUpdate(BaseModel):
    """Schema for structured LaTeX resume updates."""
    latex_code: str = Field(
        ..., description="The full or partial LaTeX code generated.")
    summary_of_changes: str = Field(
        ..., description="A brief explanation of what was updated.")
    is_complete_document: bool = Field(
        ...,
        description="True if full doc, False if sectional.")


class AIAgent:
    """Handles AI interactions for LaTeX resume management using Gemini."""

    def __init__(self, model: str = "gemini-1.5-pro"):
        self.model_name = model
        self.model = genai.GenerativeModel(
            model_name=model,
            generation_config={"response_mime_type": "application/json"}
        )

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> ResumeUpdate:
        """Helper to call Gemini and parse JSON response."""
        prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
        response = self.model.generate_content(prompt)
        try:
            data = json.loads(response.text)
            return ResumeUpdate(**data)
        except Exception as e:
            # Fallback or error handling
            raise Exception(f"Failed to parse Gemini response: {str(e)}")

    def generate_initial_resume(self,
                                bio: str,
                                template_latex: str) -> ResumeUpdate:
        """Generates initial resume."""
        system = (
            "You are a LaTeX expert. Fill the provided LaTeX template with "
            "data from the user bio. Return a JSON object matching the "
            "ResumeUpdate schema."
        )
        user = f"Template:\n{template_latex}\n\nBio:\n{bio}"
        return self._call_gemini(system, user)

    def edit_resume(self,
                    current_latex: str,
                    command: str,
                    job_description: Optional[str] = None) -> ResumeUpdate:
        """Edits full document."""
        system = (
            "You are a LaTeX editor. Optimize the resume for the JD if "
            "provided. Return a JSON object matching the ResumeUpdate schema."
        )
        user = f"LaTeX:\n{current_latex}\n\nCommand: {command}"
        if job_description:
            user += f"\n\nJD: {job_description}"
        return self._call_gemini(system, user)

    def edit_section(self,
                     section_name: str,
                     section_content: str,
                     command: str) -> ResumeUpdate:
        """Edits one section."""
        system = (
            f"Edit only the section '{section_name}'. Return ONLY the "
            f"new LaTeX content for this section within the JSON object."
        )
        user = (
            f"Section Name: {section_name}\n"
            f"Current Content:\n{section_content}\n\n"
            f"Command: {command}"
        )
        return self._call_gemini(system, user)

    def fix_latex_error(self,
                        broken_latex: str,
                        error_logs: str) -> ResumeUpdate:
        """Fixes LaTeX error."""
        system = (
            "Repair the broken LaTeX code based on the provided logs. "
            "Return the FULL document in the JSON response."
        )
        user = f"Logs:\n{error_logs}\n\nBroken LaTeX:\n{broken_latex}"
        return self._call_gemini(system, user)


ai_agent = AIAgent()
