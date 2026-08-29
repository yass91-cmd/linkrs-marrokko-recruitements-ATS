import json
import logging
from pgvector.psycopg import register_vector
from db.database import get_connection

logger = logging.getLogger(__name__)

DUTCH_TERMS = ["dutch", "nederlands", "néerlandais", "neerlandais",
               "néerlandophone", "flamand", "flemish"]


def _as_list(value):
    if isinstance(value, str):
        return json.loads(value)
    return value or []


def _speaks_dutch(languages) -> bool:
    text = " ".join(_as_list(languages)).lower()
    return any(term in text for term in DUTCH_TERMS)


def find_jobs_for_candidate(candidate_id: int, limit: int = 5):
    """Rank active jobs by semantic similarity to a candidate, with eligibility gates."""
    with get_connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, title, languages FROM candidates WHERE id = %s;",
                (candidate_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No candidate with id {candidate_id}")
            candidate = {"id": row[0], "name": row[1], "title": row[2], "languages": row[3]}

            # pgvector: <=> is cosine distance (0 = identical). Similarity = 1 - distance.
            cur.execute(
                """
                SELECT j.job_uid, j.title, j.employer, j.city, j.details,
                       1 - (j.embedding <=> c.embedding) AS similarity
                FROM jobs j, candidates c
                WHERE c.id = %s
                  AND j.embedding IS NOT NULL
                  AND j.status = 'active'
                ORDER BY j.embedding <=> c.embedding
                LIMIT %s;
                """,
                (candidate_id, limit),
            )
            jobs = cur.fetchall()

    candidate_speaks_dutch = _speaks_dutch(candidate["languages"])

    results = []
    for job_uid, title, employer, city, details, similarity in jobs:
        if isinstance(details, str):
            details = json.loads(details)
        job_languages = (details or {}).get("languages", [])
        needs_dutch = _speaks_dutch(job_languages) or True   # all stored jobs require Dutch

        blocking = []
        if needs_dutch and not candidate_speaks_dutch:
            blocking.append("Candidate does not list Dutch")

        results.append({
            "job_uid": job_uid, "title": title, "employer": employer, "city": city,
            "similarity": round(float(similarity), 3),
            "eligible": not blocking,
            "blocking_reasons": blocking,
        })
    return candidate, results



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Find matching jobs for a candidate.")
    parser.add_argument("candidate_id", type=int)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    candidate, results = find_jobs_for_candidate(args.candidate_id, args.limit)

    print(f"\nCandidate #{candidate['id']}: {candidate['name']} — {candidate['title']}")
    print(f"Languages: {candidate['languages']}\n")
    print(f"{'Score':>7}  {'✓':^3} Job")
    print("-" * 78)
    for r in results:
        mark = "✅" if r["eligible"] else "⛔"
        print(f"{r['similarity']:>7.3f}  {mark}  {r['title'][:52]}")
        print(f"{'':>7}     {r['employer'] or '—'} · {r['city'] or '—'}")
        for reason in r["blocking_reasons"]:
            print(f"{'':>7}     ⚠ {reason}")
    print()
def find_candidates_for_job(job_uid: str, limit: int = 5):
    """Rank candidates by semantic similarity to a job, with eligibility gates."""
    with get_connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT job_uid, title, employer, city FROM jobs WHERE job_uid = %s;",
                (job_uid,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No job with uid {job_uid}")
            job = {"job_uid": row[0], "title": row[1], "employer": row[2], "city": row[3]}

            cur.execute(
                """
                SELECT c.id, c.name, c.title, c.languages, c.location,
                       1 - (c.embedding <=> j.embedding) AS similarity
                FROM candidates c, jobs j
                WHERE j.job_uid = %s AND c.embedding IS NOT NULL AND j.embedding IS NOT NULL
                ORDER BY c.embedding <=> j.embedding
                LIMIT %s;
                """,
                (job_uid, limit),
            )
            rows = cur.fetchall()

    results = []
    for cid, name, title, languages, location, similarity in rows:
        blocking = []
        if not _speaks_dutch(languages):
            blocking.append("Candidate does not list Dutch")
        results.append({
            "candidate_id": cid, "name": name, "title": title, "location": location,
            "similarity": round(float(similarity), 3),
            "eligible": not blocking,
            "blocking_reasons": blocking,
        })
    return job, results