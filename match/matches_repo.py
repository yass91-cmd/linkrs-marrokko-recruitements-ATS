from psycopg.types.json import Json
from db.database import get_connection


def save_match(candidate_id: int, job_uid: str, result: dict) -> bool:
    """
    Store (or refresh) the assessment for a candidate-job pair.
    Re-running the reranker updates the SCORES but never resets the workflow status.
    Returns True if this pair was newly created.
    """
    a = result["assessment"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO matches
                    (candidate_id, job_uid, similarity, llm_score, verdict,
                     strengths, gaps, summary, eligible, blocking_reasons)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (candidate_id, job_uid) DO UPDATE SET
                    similarity       = EXCLUDED.similarity,
                    llm_score        = EXCLUDED.llm_score,
                    verdict          = EXCLUDED.verdict,
                    strengths        = EXCLUDED.strengths,
                    gaps             = EXCLUDED.gaps,
                    summary          = EXCLUDED.summary,
                    eligible         = EXCLUDED.eligible,
                    blocking_reasons = EXCLUDED.blocking_reasons,
                    assessed_at      = now(),
                    updated_at       = now()
                RETURNING (xmax = 0) AS inserted;
                """,
                (
                    candidate_id,
                    job_uid,
                    result["similarity"],
                    a.score,
                    a.verdict,
                    Json(a.strengths),
                    Json(a.gaps),
                    a.summary,
                    result["eligible"],
                    Json(result["blocking_reasons"]),
                ),
            )
            inserted = cur.fetchone()[0]
        conn.commit()
    return inserted


def set_status(candidate_id: int, job_uid: str, status: str, note: str | None = None) -> None:
    """Advance a match through the workflow (presented → approved → applied → hired…)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE matches
                SET status = %s,
                    note = COALESCE(%s, note),
                    updated_at = now()
                WHERE candidate_id = %s AND job_uid = %s;
                """,
                (status, note, candidate_id, job_uid),
            )
        conn.commit()