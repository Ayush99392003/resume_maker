"""ATS scoring — embeddings when Gemini available, keywords via LLM router."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

import numpy as np

try:
    from llm_router import ChatMessage, llm_router
    from core import config  # noqa: F401
except ImportError:
    from ..llm_router import ChatMessage, llm_router
    from . import config  # noqa: F401


class ATSScorer:
    """Calculates ATS score from JD and resume text."""

    def get_embedding(self, text: str, model="models/text-embedding-004"):
        """Gets vector embedding using Gemini when configured."""
        import google.generativeai as genai

        if not config.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY required for embedding-based ATS semantic score"
            )
        text = text.replace("\n", " ")
        result = genai.embed_content(
            model=model,
            content=text,
            task_type="retrieval_document",
        )
        return result["embedding"]

    def cosine_similarity(self, v1, v2):
        v1 = np.array(v1)
        v2 = np.array(v2)
        return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

    def extract_keywords_ai(
        self,
        text: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> List[str]:
        prompt = (
            "Extract professional skills, technologies, and qualifications. "
            'Return JSON: {"keywords": ["...", "..."]}.\n\nText:\n' + text
        )
        resp = llm_router.chat(
            [
                ChatMessage(
                    role="system",
                    content="You extract keywords. Reply with JSON only.",
                ),
                ChatMessage(role="user", content=prompt),
            ],
            provider=provider,
            model=model,
            api_key=api_key,
            temperature=0.1,
            response_format="json",
        )
        try:
            data = json.loads(resp.content)
            if isinstance(data, list):
                return [str(x) for x in data]
            return [str(x) for x in data.get("keywords", [])]
        except (json.JSONDecodeError, TypeError):
            return re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", text)[:30]

    def calculate_score(
        self,
        resume_text: str,
        jd_text: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict:
        jd_keys = set(
            self.extract_keywords_ai(
                jd_text, provider=provider, model=model, api_key=api_key
            )
        )
        res_keys = set(
            self.extract_keywords_ai(
                resume_text, provider=provider, model=model, api_key=api_key
            )
        )
        matches = jd_keys.intersection(res_keys)
        missing = jd_keys - res_keys
        keyword_score = len(matches) / len(jd_keys) if jd_keys else 1.0

        semantic_score = keyword_score
        if config.GEMINI_API_KEY:
            try:
                res_emb = self.get_embedding(resume_text)
                jd_emb = self.get_embedding(jd_text)
                semantic_score = self.cosine_similarity(res_emb, jd_emb)
            except Exception:
                semantic_score = keyword_score

        total_score = (semantic_score * 0.6) + (keyword_score * 0.4)
        return {
            "total_score": round(total_score * 100, 2),
            "semantic_match": round(semantic_score * 100, 2),
            "keyword_match": round(keyword_score * 100, 2),
            "missing_keywords": list(missing)[:10],
            "matched_keywords": list(matches)[:10],
        }


ats_scorer = ATSScorer()
