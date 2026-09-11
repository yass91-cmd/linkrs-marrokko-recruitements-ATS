from psycopg.types.json import Json
from db.database import get_connection
from extract.schema import Candidate


def save_candidate(candidate: Candidate, source_method: str, raw_text: str,
                   file_path: str | None = None) -> tuple[int, bool]:
    """Store a CV, keyed on the verified email.

    Returns (id, inserted). `inserted` is False when an existing profile was
    replaced — the caller must then discard anything derived from the old one,
    because a second person signing in with the same address overwrites the
    first and their matches would otherwise describe someone who is gone.
    """
    data = candidate.model_dump()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                        """
                INSERT INTO candidates
                    (name, title, email, phone, location, skills, languages,
                     education, experience, projects, years_experience, summary,
                     warnings, source_method, raw_text, file_path)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) WHERE email IS NOT NULL DO UPDATE SET
                    name = EXCLUDED.name,
                    title = EXCLUDED.title,
                    phone = EXCLUDED.phone,
                    location = EXCLUDED.location,
                    skills = EXCLUDED.skills,
                    languages = EXCLUDED.languages,
                    education = EXCLUDED.education,
                    experience = EXCLUDED.experience,
                    projects = EXCLUDED.projects,
                    years_experience = EXCLUDED.years_experience,
                    summary = EXCLUDED.summary,
                    warnings = EXCLUDED.warnings,
                    source_method = EXCLUDED.source_method,
                    raw_text = EXCLUDED.raw_text,
                    file_path = COALESCE(EXCLUDED.file_path, candidates.file_path)
                RETURNING id, (xmax = 0) AS inserted;
                """,
                (
                    data["name"], data["title"], data["email"], data["phone"],
                    data["location"], Json(data["skills"]), Json(data["languages"]),
                    Json(data["education"]), Json(data["experience"]), Json(data["projects"]),
                    data["years_experience"], data["summary"], Json(data["warnings"]),
                    source_method, raw_text, file_path,
                ),
            )
            new_id, inserted = cur.fetchone()
        conn.commit()
    return new_id, inserted