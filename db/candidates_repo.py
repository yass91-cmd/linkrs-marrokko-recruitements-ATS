from psycopg.types.json import Json
from db.database import get_connection
from extract.schema import Candidate


def save_candidate(candidate: Candidate, source_method: str, raw_text: str) -> int:
    data = candidate.model_dump()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                        """
                INSERT INTO candidates
                    (name, title, email, phone, location, skills, languages,
                     education, experience, projects, years_experience, summary,
                     warnings, source_method, raw_text)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    raw_text = EXCLUDED.raw_text
                RETURNING id;
                """,
                (
                    data["name"], data["title"], data["email"], data["phone"],
                    data["location"], Json(data["skills"]), Json(data["languages"]),
                    Json(data["education"]), Json(data["experience"]), Json(data["projects"]),
                    data["years_experience"], data["summary"], Json(data["warnings"]),
                    source_method, raw_text,
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id