
from pydantic import BaseModel


class DraftVariant(BaseModel):
    id: str
    latex_code: str
    summary: str
    intent: str  # e.g., "Professional", "Creative", "Concise"
    zone_id: str | None = None


class RefinementProposal(BaseModel):
    original_latex: str
    variants: list[DraftVariant]
    session_id: str


class RefinementManager:
    """Manages multi-turn refinement sessions and versions."""

    def __init__(self):
        self.active_sessions: dict[str, RefinementProposal] = {}

    def create_session(
        self,
        session_id: str,
        original_latex: str,
        variants: list[DraftVariant]
    ) -> RefinementProposal:
        proposal = RefinementProposal(
            original_latex=original_latex,
            variants=variants,
            session_id=session_id
        )
        self.active_sessions[session_id] = proposal
        return proposal

    def get_variant(
        self,
        session_id: str,
        variant_id: str
    ) -> DraftVariant | None:
        session = self.active_sessions.get(session_id)
        if not session:
            return None
        for v in session.variants:
            if v.id == variant_id:
                return v
        return None


refinement_manager = RefinementManager()
