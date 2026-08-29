import json
import logging
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re

from db.database import get_connection
from extract.llm_json import get_structured
from match.build_embeddings import candidate_to_text, job_to_text
from match.search import find_jobs_for_candidate

logger = logging.getLogger(__name__)


class MatchAssessment(BaseModel):
    score: int = 0                                  # 0-100
    verdict: Optional[str] = None                   # strong / moderate / weak
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    summary: Optional[str] = None

    @field_validator("gaps", mode="before")
    @classmethod
    def clean_gaps(cls, v):
        if v is None:
            return []
        # Drop filler the model writes instead of returning an empty list.
        filler = ("aucune lacune", "aucun gap", "pas de lacune", "aucune faiblesse",
                  "no gaps", "none identified", "aucun point faible")
        return [x for x in v if not any(f in str(x).lower() for f in filler)]

    @field_validator("strengths", mode="before")
    @classmethod
    def clean_strengths(cls, v):
        return [] if v is None else v

    @field_validator("score", mode="before")
    @classmethod
    def clamp(cls, v):
        try:
            return max(0, min(100, int(v)))
        except (TypeError, ValueError):
            return 0

    @field_validator("strengths", "gaps", "summary", "verdict", mode="after")
    @classmethod
    def strip_cjk(cls, v):
        """Defence in depth: remove CJK characters the model occasionally leaks."""
        def clean(s):
            return re.sub(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "", s).strip()
        if isinstance(v, list):
            return [clean(x) for x in v]
        return clean(v) if isinstance(v, str) else v

PROMPT = """You are an experienced recruiter at a Moroccan recruitment agency that places
candidates into Dutch-speaking roles.

Assess how well this CANDIDATE fits this JOB.

Return ONLY a valid JSON object with EXACTLY these keys:
{
  "score": integer from 0 to 100,
  "verdict": "strong" or "moderate" or "weak",
  "strengths": [short strings — concrete reasons the candidate fits],
  "gaps": [short strings — concrete things the candidate is missing],
  "summary": "one or two sentences a recruiter can read"
}

Rules:
- Base the assessment ONLY on the information given; never invent experience.
- The Dutch language requirement is critical: if the candidate does not speak Dutch,
  the score must be below 30 and this must appear in "gaps".
- If there are no real gaps, return an EMPTY list: "gaps": []. Never write
  "no gaps found" or similar filler as a gap entry.
- Write ALL text in French, using ONLY Latin characters. Never use Chinese,
  Japanese, Korean, or any non-Latin script.

CANDIDATE:
\"\"\"
{{CANDIDATE}}
\"\"\"

JOB:
\"\"\"
{{JOB}}
\"\"\"
"""


def _fetch_row(table: str, key: str, value) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table} WHERE {key} = %s;", (value,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No row in {table} where {key} = {value}")
            columns = [d.name for d in cur.description]
    return dict(zip(columns, row))


def assess(candidate_id: int, job_uid: str) -> MatchAssessment:
    candidate = _fetch_row("candidates", "id", candidate_id)
    job = _fetch_row("jobs", "job_uid", job_uid)

    prompt = (PROMPT
              .replace("{{CANDIDATE}}", candidate_to_text(candidate))
              .replace("{{JOB}}", job_to_text(job)))
    return MatchAssessment(**get_structured(prompt))


def rerank_for_candidate(candidate_id: int, top_n: int = 3):
    """Semantic retrieval, then LLM assessment of only the top N (economical)."""
    candidate, results = find_jobs_for_candidate(candidate_id, limit=top_n)
    assessed = []
    for r in results:
        try:
            a = assess(candidate_id, r["job_uid"])
        except Exception as e:
            logger.warning("Assessment failed for %s: %s", r["title"], e)
            continue
        assessed.append({**r, "assessment": a})
    assessed.sort(key=lambda x: x["assessment"].score, reverse=True)
    return candidate, assessed


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Rank and explain job matches for a candidate.")
    parser.add_argument("candidate_id", type=int)
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    candidate, results = rerank_for_candidate(args.candidate_id, args.top)

    print(f"\n{'='*78}")
    print(f"Candidate #{candidate['id']}: {candidate['name']} — {candidate['title']}")
    print(f"{'='*78}")
    for r in results:
        a = r["assessment"]
        print(f"\n▸ {r['title'][:60]}")
        print(f"  {r['employer'] or '—'} · {r['city'] or '—'}")
        print(f"  Semantic: {r['similarity']:.3f}   |   LLM score: {a.score}/100 ({a.verdict})")
        if a.summary:
            print(f"  → {a.summary}")
        for s in a.strengths:
            print(f"    ✅ {s}")
        for g in a.gaps:
            print(f"    ⚠️  {g}")
    print()