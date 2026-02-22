from typing import List, Dict, Optional
from pydantic import BaseModel


class DraftVariant(BaseModel):
    id: str
    latex_code: str
    summary: str
    intent: str  # e.g., "Professional", "Creative", "Concise"


class RefinementProposal(BaseModel):
    original_latex: str
    variants: List[DraftVariant]
    session_id: str


class RefinementManager:
    """Manages multi-turn refinement sessions and versions."""

    def __init__(self):
        self.active_sessions: Dict[str, RefinementProposal] = {}

    def create_session(
        self,
        session_id: str,
        original_latex: str,
        variants: List[DraftVariant]
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
    ) -> Optional[DraftVariant]:
        session = self.active_sessions.get(session_id)
        if not session:
            return None
        for v in session.variants:
            if v.id == variant_id:
                return v
        return None


refinement_manager = RefinementManager()
