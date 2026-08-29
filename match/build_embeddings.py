import json
import logging
from pgvector.psycopg import register_vector
from db.database import get_connection
from match.embeddings import embed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _as_list(value):
    """jsonb columns may come back as a list or as a JSON string."""
    if isinstance(value, str):
        return json.loads(value)
    return value or []


def candidate_to_text(row: dict) -> str:
    """Compose the text that represents a candidate for matching.
    Deliberately excludes name/email/phone — no matching signal, and it keeps PII out."""
    parts = [
        row.get("title") or "",
        row.get("summary") or "",
        "Compétences: " + ", ".join(_as_list(row.get("skills"))),
        "Langues: " + ", ".join(_as_list(row.get("languages"))),
    ]
    education = _as_list(row.get("education"))
    parts += [f"{e.get('degree', '')} {e.get('institution', '')}" for e in education]
    experience = _as_list(row.get("experience"))
    parts += [f"{e.get('title', '')} {e.get('company', '')}" for e in experience]
    parts += _as_list(row.get("projects"))
    return "\n".join(p for p in parts if p.strip())


def job_to_text(row: dict) -> str:
    """Compose the text that represents a job for matching."""
    details = row.get("details") or {}
    if isinstance(details, str):
        details = json.loads(details)
    parts = [
        row.get("title") or "",
        "Missions: " + ", ".join(details.get("missions") or []),
        "Exigences: " + ", ".join(details.get("requirements") or []),
        "Langues: " + ", ".join(details.get("languages") or []),
    ]
    if not details:                       # fall back to the raw description
        parts.append((row.get("description") or "")[:2000])
    return "\n".join(p for p in parts if p.strip())


def embed_table(table: str, key: str, to_text) -> int:
    with get_connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table} WHERE embedding IS NULL;")
            columns = [d.name for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]

            for row in rows:
                text = to_text(row)
                if not text.strip():
                    logger.warning("Skipping %s (no text)", row[key])
                    continue
                vector = embed(text)
                cur.execute(
                    f"UPDATE {table} SET embedding = %s WHERE {key} = %s;",
                    (vector, row[key]),
                )
                logger.info("Embedded %s: %s", table, str(row.get("title") or row.get("name"))[:60])
        conn.commit()
    return len(rows)


if __name__ == "__main__":
    n_c = embed_table("candidates", "id", candidate_to_text)
    n_j = embed_table("jobs", "job_uid", job_to_text)
    print(f"\nEmbedded {n_c} candidates and {n_j} jobs.")