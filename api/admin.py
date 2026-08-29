import json
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db.database import get_connection

from datetime import datetime, timezone
from jobs.fetch_jobs import collect_all

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

router = APIRouter(prefix="/admin", tags=["admin"])


def fetch(sql: str, params: tuple = ()) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d.name for d in cur.description]
            rows = cur.fetchall()
    return [dict(zip(columns, r)) for r in rows]


def fetch_one(sql: str, params: tuple = ()) -> dict | None:
    rows = fetch(sql, params)
    return rows[0] if rows else None


def as_list(value):
    """jsonb may arrive as a list or as a JSON string."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return value or []


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request):
    stats = fetch_one("""
        SELECT
          (SELECT COUNT(*) FROM candidates) AS candidates,
          (SELECT COUNT(*) FROM jobs WHERE status = 'active') AS active_jobs,
          (SELECT COUNT(*) FROM matches) AS matches,
          (SELECT COUNT(*) FROM jobs WHERE status='active' AND hr_verified=false) AS pending_hr;
    """)
    funnel = fetch("SELECT status, COUNT(*) AS n FROM matches GROUP BY status;")
    top = fetch("""
        SELECT m.candidate_id, c.name AS candidate, j.title AS job, j.employer,
               j.city, m.llm_score, m.verdict, m.status
        FROM matches m
        JOIN candidates c ON c.id = m.candidate_id
        JOIN jobs j ON j.job_uid = m.job_uid
        WHERE m.eligible = true
        ORDER BY m.llm_score DESC NULLS LAST
        LIMIT 8;
    """)
    recent = fetch("""
        SELECT id, name, title, source_method, created_at
        FROM candidates ORDER BY created_at DESC LIMIT 5;
    """)
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "stats": stats,
        "funnel": {f["status"]: f["n"] for f in funnel},
        "top": top,
        "recent": recent,
    })


@router.get("/candidates", response_class=HTMLResponse)
def candidates(request: Request, q: str = ""):
    query = q.strip()
    if query:
        from match.search import search_candidates, _speaks_dutch
        rows = search_candidates(query, limit=20)
        for r in rows:
            r["dutch"] = _speaks_dutch(r["languages"])
    else:
        rows = fetch("""
            SELECT c.id, c.name, c.title, c.location, c.languages, c.source_method,
                   c.created_at,
                   (SELECT COUNT(*) FROM matches m WHERE m.candidate_id = c.id) AS n_matches,
                   (c.embedding IS NOT NULL) AS embedded
            FROM candidates c ORDER BY c.created_at DESC;
        """)
        from match.search import _speaks_dutch
        for r in rows:
            r["dutch"] = _speaks_dutch(r["languages"])

    return templates.TemplateResponse(request, "admin/candidates.html", {
        "rows": rows, "q": query,
    })


@router.get("/candidates/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(request: Request, candidate_id: int):
    candidate = fetch_one("SELECT * FROM candidates WHERE id = %s;", (candidate_id,))
    matches = fetch("""
        SELECT m.*, j.title, j.employer, j.city, j.apply_link
        FROM matches m JOIN jobs j ON j.job_uid = m.job_uid
        WHERE m.candidate_id = %s
        ORDER BY m.llm_score DESC NULLS LAST;
    """, (candidate_id,))
    for m in matches:
        m["strengths"] = as_list(m["strengths"])
        m["gaps"] = as_list(m["gaps"])
    return templates.TemplateResponse(request, "admin/candidate_detail.html", {
        "c": candidate,
        "matches": matches,
        "skills": as_list(candidate["skills"]) if candidate else [],
        "languages": as_list(candidate["languages"]) if candidate else [],
        "education": as_list(candidate["education"]) if candidate else [],
        "experience": as_list(candidate["experience"]) if candidate else [],
        "warnings": as_list(candidate["warnings"]) if candidate else [],
    })


@router.post("/candidates/{candidate_id}/match")
def run_matching(candidate_id: int, top: int = Form(3)):
    """Run the matching engine for this candidate (retrieve + LLM rerank)."""
    from match.rerank import rerank_for_candidate
    rerank_for_candidate(candidate_id, top_n=top)
    return RedirectResponse(f"/admin/candidates/{candidate_id}", status_code=303)


@router.post("/matches/{match_id}/status")
def update_match_status(match_id: int,
                        status: str = Form(...),
                        candidate_id: int = Form(default=0),
                        redirect_to: str = Form(default="")):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE matches SET status = %s, updated_at = now() WHERE id = %s;",
                (status, match_id),
            )
        conn.commit()

    target = redirect_to or f"/admin/candidates/{candidate_id}"
    # Only allow internal paths — never redirect to a URL supplied from outside.
    if not target.startswith("/"):
        target = "/admin/pipeline"
    return RedirectResponse(target, status_code=303)




@router.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request, filter: str = "todo", checked: int = -1, added: int = 0):
    where = {
        "todo":      "WHERE j.status = 'active' AND j.hr_verified = false",
        "recent":    "WHERE j.created_at > now() - interval '24 hours'",
        "unmatched": "WHERE j.status = 'active' AND NOT EXISTS "
                     "(SELECT 1 FROM matches m WHERE m.job_uid = j.job_uid)",
        "verified":  "WHERE j.hr_verified = true",
        "active":    "WHERE j.status = 'active'",
        "all":       "",
    }.get(filter, "")

    rows = fetch(f"""
        SELECT j.job_uid, j.title, j.employer, j.city, j.is_remote, j.status,
               j.hr_verified, j.hr_salary, j.details, j.created_at, j.last_seen_at,
               (j.created_at > now() - interval '24 hours') AS is_new,
               (SELECT COUNT(*) FROM matches m WHERE m.job_uid = j.job_uid) AS n_matches
        FROM jobs j
        {where}
        ORDER BY is_new DESC, j.created_at DESC;
    """)
    for r in rows:
        details = r["details"]
        if isinstance(details, str):
            details = json.loads(details or "{}")
        r["languages"] = (details or {}).get("languages", [])

    counts = fetch_one("""
        SELECT
          COUNT(*) FILTER (WHERE status='active' AND hr_verified=false)     AS todo,
          COUNT(*) FILTER (WHERE created_at > now() - interval '24 hours')  AS recent,
          COUNT(*) FILTER (WHERE status='active' AND NOT EXISTS
                 (SELECT 1 FROM matches m WHERE m.job_uid = jobs.job_uid))  AS unmatched,
          COUNT(*) FILTER (WHERE hr_verified=true)                          AS verified,
          COUNT(*) FILTER (WHERE status='active')                           AS active,
          COUNT(*)                                                          AS all
        FROM jobs;
    """)
    return templates.TemplateResponse(request, "admin/jobs.html", {
        "rows": rows, "filter": filter, "counts": counts,
        "checked": checked, "added": added,
    })

@router.get("/jobs/{job_uid}", response_class=HTMLResponse)
def job_detail(request: Request, job_uid: str):
    job = fetch_one("SELECT * FROM jobs WHERE job_uid = %s;", (job_uid,))
    details = job["details"] if job else None
    if isinstance(details, str):
        details = json.loads(details or "{}")

    candidates = fetch("""
        SELECT m.id, m.candidate_id, m.llm_score, m.verdict, m.eligible, m.status,
               m.summary, c.name, c.title
        FROM matches m JOIN candidates c ON c.id = m.candidate_id
        WHERE m.job_uid = %s
        ORDER BY m.llm_score DESC NULLS LAST;
    """, (job_uid,))

    return templates.TemplateResponse(request, "admin/job_detail.html", {
        "j": job, "d": details or {}, "candidates": candidates,
    })


@router.post("/jobs/{job_uid}/hr")
def save_hr(job_uid: str,
            hr_verified: str = Form(default=""),
            hr_salary: str = Form(default=""),
            hr_notes: str = Form(default=""),
            note: str = Form(default=""),
            status: str = Form(default="active")):
    verified = hr_verified == "on"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs SET
                    hr_verified = %s,
                    hr_verified_at = CASE
                        WHEN %s AND hr_verified_at IS NULL THEN now()
                        WHEN %s THEN hr_verified_at
                        ELSE NULL END,
                    hr_salary = NULLIF(%s, ''),
                    hr_notes  = NULLIF(%s, ''),
                    note      = NULLIF(%s, ''),
                    status    = %s
                WHERE job_uid = %s;
                """,
                (verified, verified, verified, hr_salary, hr_notes, note, status, job_uid),
            )
        conn.commit()
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)

@router.post("/jobs/{job_uid}/match")
def run_job_matching(job_uid: str, top: int = Form(3)):
    """Reverse matching: find the best candidates for this job."""
    from match.rerank import rerank_for_job
    rerank_for_job(job_uid, top_n=top)
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)
STAGES = [
    ("suggested", "Suggéré"),
    ("presented", "Présenté"),
    ("approved", "Accepté"),
    ("applied", "Candidature"),
    ("hired", "Recruté"),
]


@router.get("/pipeline", response_class=HTMLResponse)
def pipeline(request: Request, eligible: str = "1"):
    where = "WHERE m.eligible = true" if eligible == "1" else ""
    rows = fetch(f"""
        SELECT m.id, m.candidate_id, m.job_uid, m.status, m.llm_score,
               m.verdict, m.eligible, m.updated_at,
               c.name AS candidate, j.title AS job, j.employer, j.city
        FROM matches m
        JOIN candidates c ON c.id = m.candidate_id
        JOIN jobs j       ON j.job_uid = m.job_uid
        {where}
        ORDER BY m.llm_score DESC NULLS LAST;
    """)
    board = {key: [r for r in rows if r["status"] == key] for key, _ in STAGES}
    closed = [r for r in rows if r["status"] in ("declined", "rejected")]
    return templates.TemplateResponse(request, "admin/pipeline.html", {
        "stages": STAGES, "board": board, "closed": closed,
        "eligible": eligible, "total": len(rows),
    })


@router.post("/jobs/collect")
def collect_jobs():
    """Run the JSearch collector, then embed any newly stored jobs."""
    from jobs.fetch_jobs import fetch_dutch_jobs
    from match.build_embeddings import embed_table, job_to_text

    total, inserted = fetch_dutch_jobs()
    embed_table("jobs", "job_uid", job_to_text)   # new jobs need vectors to be matchable
    return RedirectResponse(
        f"/admin/jobs?filter=all&checked={total}&added={inserted}", status_code=303
    )
total, inserted = collect_all()