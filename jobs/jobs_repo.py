from psycopg.types.json import Json
from db.database import get_connection
from jobs.normalize import clean_text, detect_city, clean_employer


def job_exists(job_uid: str) -> bool:
    """Cheap existence check, so we don't pay for LLM structuring on known jobs."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM jobs WHERE job_uid = %s;", (job_uid,))
            return cur.fetchone() is not None


def touch_job(job_uid: str) -> None:
    """Mark an already-known job as still being advertised."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE jobs SET last_seen_at = now() WHERE job_uid = %s;", (job_uid,))
        conn.commit()


def save_job(job: dict, details: dict | None = None) -> bool:
    """Insert a job keyed on job_uid; refresh last_seen_at if already known."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs
                    (job_uid, title, employer, city, is_remote,
                     apply_link, description, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_uid) DO UPDATE SET last_seen_at = now()
                RETURNING (xmax = 0) AS inserted;
                """,
                (
                    job.get("job_uid"),
                    job.get("job_title"),
                    clean_employer(job.get("employer_name")),
                    detect_city(job),
                    job.get("job_is_remote"),
                    job.get("job_apply_link"),
                    clean_text(job.get("job_description")),
                    Json(details) if details is not None else None,
                ),
            )
            inserted = cur.fetchone()[0]
        conn.commit()
    return inserted