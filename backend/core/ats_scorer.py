import json
from typing import Dict, List
import numpy as np
import google.generativeai as genai

# Side effect: genai is already configured in core.config
try:
    import core.config  # noqa: F401
except ImportError:
    from . import config  # noqa: F401


class ATSScorer:
    """Calculates ATS score based on JD and Resume text using Gemini."""

    def get_embedding(self, text: str, model="models/text-embedding-004"):
        """Gets vector embedding using Gemini."""
        text = text.replace("\n", " ")
        result = genai.embed_content(
            model=model,
            content=text,
            task_type="retrieval_document"
        )
        return result['embedding']

    def cosine_similarity(self, v1, v2):
        """Calculates cosine similarity between two vectors."""
        v1 = np.array(v1)
        v2 = np.array(v2)
        dot_product = np.dot(v1, v2)
        norm_v1 = np.linalg.norm(v1)
        norm_v2 = np.linalg.norm(v2)
        return dot_product / (norm_v1 * norm_v2)

    def extract_keywords_ai(self, text: str) -> List[str]:
        """Uses Gemini to extract professional keywords."""
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            "Extract a list of professional skills, technologies, and "
            "qualifications from the following text. Return the list as a "
            "JSON array of strings.\n\nText:\n" + text
        )
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, Exception):
            return []

    def calculate_score(self,
                        resume_text: str,
                        jd_text: str) -> Dict[str, any]:
        """
        Calculates a comprehensive ATS score using semantic matching and
        AI-driven keyword analysis.
        """
        # 1. Semantic Similarity (60%)
        res_emb = self.get_embedding(resume_text)
        jd_emb = self.get_embedding(jd_text)
        semantic_score = self.cosine_similarity(res_emb, jd_emb)

        # 2. AI Keyword Coverage (40%)
        jd_keys = set(self.extract_keywords_ai(jd_text))
        res_keys = set(self.extract_keywords_ai(resume_text))

        matches = jd_keys.intersection(res_keys)
        missing = jd_keys - res_keys

        keyword_score = len(matches) / len(jd_keys) if jd_keys else 1.0

        # Total Score
        total_score = (semantic_score * 0.6) + (keyword_score * 0.4)

        return {
            "total_score": round(total_score * 100, 2),
            "semantic_match": round(semantic_score * 100, 2),
            "keyword_match": round(keyword_score * 100, 2),
            "missing_keywords": list(missing)[:10],
            "matched_keywords": list(matches)[:10]
        }


# Singleton
ats_scorer = ATSScorer()
