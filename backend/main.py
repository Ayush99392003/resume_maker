import base64
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

try:
    from core.compiler import compiler, CompilationError
    from core.ai_agent import ai_agent
    from core.templates import template_manager
    from core.parser import sectional_parser
    from core.ats_scorer import ats_scorer
    from core.indent_guard import indent_guard
    from core.refinement import refinement_manager, DraftVariant
except ImportError:
    from .core.compiler import compiler, CompilationError
    from .core.ai_agent import ai_agent
    from .core.templates import template_manager
    from .core.parser import sectional_parser
    from .core.ats_scorer import ats_scorer
    from .core.indent_guard import indent_guard
    from .core.refinement import refinement_manager, DraftVariant

app = FastAPI(
    title="AI LaTeX Resume Maker API",
    description="Backend with Sectional Batching and AI Self-Correction",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    bio: str
    template_name: str = "classic"


class EditRequest(BaseModel):
    current_latex: str
    command: str
    job_description: Optional[str] = None
    section_name: Optional[str] = None


class ProposalRequest(BaseModel):
    current_latex: str
    command: str
    section_name: Optional[str] = None


class ApplyRequest(BaseModel):
    session_id: str
    variant_id: str
    current_latex: str
    section_name: Optional[str] = None


class ScoreRequest(BaseModel):
    resume_text: str
    job_description: str


def compile_with_retry(latex_code: str, max_retries: int = 2) -> bytes:
    """Compiles LaTeX with a recursive AI fix loop."""
    current_latex = latex_code
    last_error = ""

    for attempt in range(max_retries + 1):
        try:
            return compiler.compile(current_latex)
        except CompilationError as e:
            if attempt == max_retries:
                raise e
            last_error = e.logs
            # Trigger Silent Fix
            fix_update = ai_agent.fix_latex_error(current_latex, last_error)
            current_latex = fix_update.latex_code

    raise Exception("Max retries exceeded in compilation loop.")


class CompileRequest(BaseModel):
    latex_code: str


@app.get("/")
async def root():
    return {"message": "AI LaTeX Resume Maker API is running"}


@app.post("/compile")
async def compile_latex_direct(req: CompileRequest):
    """Directly compiles LaTeX without AI interaction."""
    try:
        pdf_bytes = compiler.compile(req.latex_code)
        return {
            "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate")
async def generate_resume(req: GenerateRequest):
    template = template_manager.get_template(req.template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        update = ai_agent.generate_initial_resume(req.bio, template)
        pdf_bytes = compile_with_retry(update.latex_code)
        return {
            "latex_code": update.latex_code,
            "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
            "summary": update.summary_of_changes,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/propose")
async def propose_edits(req: ProposalRequest):
    """Generates multiple draft variants for an edit."""
    try:
        # Use a timestamp or hash for session_id in a real app
        import uuid

        session_id = str(uuid.uuid4())
        proposal = ai_agent.generate_edit_proposals(
            req.current_latex, req.command, req.section_name
        )

        variants = [
            DraftVariant(
                id=v.id,
                latex_code=v.latex_code,
                summary=v.summary,
                intent=v.intent,
            )
            for v in proposal.proposals
        ]

        refinement_manager.create_session(
            session_id, req.current_latex, variants
        )

        return {"session_id": session_id, "variants": variants}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/apply")
async def apply_edit(req: ApplyRequest):
    """Applies a selected variant to the document."""
    try:
        variant = refinement_manager.get_variant(
            req.session_id, req.variant_id
        )
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        target_latex = req.current_latex
        if req.section_name:
            new_latex = sectional_parser.replace_section(
                target_latex, req.section_name, variant.latex_code
            )
        else:
            # If AI returned full doc in variant, use it;
            # otherwise assume it's a replacement if context was full doc
            new_latex = variant.latex_code

        pdf_bytes = compile_with_retry(new_latex)
        return {
            "latex_code": new_latex,
            "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
            "summary": variant.summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/score")
async def score_resume(req: ScoreRequest):
    try:
        return ats_scorer.calculate_score(req.resume_text, req.job_description)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validate")
async def validate_latex(req: dict):
    try:
        return indent_guard.validate_indentation(req.get("latex_code", ""))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sections")
async def get_sections(req: dict):
    """Returns detected sections from LaTeX code."""
    try:
        latex = req.get("latex_code", "")
        sections = sectional_parser.extract_sections(latex)
        return {"sections": list(sections.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/squeeze")
async def squeeze_resume(req: dict):
    """Optimizes LaTeX layout to fit more content."""
    try:
        latex = req.get("latex_code", "")
        update = ai_agent.squeeze_layout(latex)
        pdf_bytes = compile_with_retry(update.latex_code)
        return {
            "latex_code": update.latex_code,
            "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
            "summary": update.summary_of_changes,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
