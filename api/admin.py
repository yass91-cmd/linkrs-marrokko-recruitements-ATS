import json
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db.database import get_connection

from api.auth import require_admin


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])


# (key, column label, statuses shown in it)
STAGES = [
    ("suggested", "Suggéré",       ("suggested",)),
    ("presented", "Présenté",      ("presented",)),
    ("applied",   "Envoyé à l'HR", ("applied",)),
    ("declined",  "Décliné",       ("declined", "rejected")),
    ("hired",     "Accepté",       ("hired",)),
]

# Only these block new suggestions — a candidate may sit on several Suggéré at once.
IN_PROGRESS = ("presented", "applied")

# A job carrying any of these cannot be deleted: the cascade would erase a live
# file or a recorded recruitment. Suggéré is excluded — it is only a shortlist.
PROTECTED = IN_PROGRESS + ("hired",)

STATUS_CHOICES = [
    ("non_traite", "Non traité"),
    ("suggested",  "Suggéré"),
    ("presented",  "Présenté au candidat"),
    ("applied",    "Envoyé à l'HR"),
    ("declined",   "Décliné"),
    ("hired",      "Accepté"),
]

STATUS_LABELS = dict(STATUS_CHOICES)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

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


def _lines(value: str | None) -> list[str]:
    """Turn a textarea (one item per line) into a list."""
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def dashboard(request: Request):
    stats = fetch_one("""
        SELECT
          (SELECT COUNT(*) FROM candidates c
             WHERE NOT EXISTS (SELECT 1 FROM matches m
                               WHERE m.candidate_id = c.id AND m.status = 'hired'))
                                                                      AS pool,
          (SELECT COUNT(*) FROM jobs WHERE status='active'
                                       AND hr_verified = false)       AS jobs_todo,
          (SELECT COUNT(*) FROM jobs WHERE status='active')            AS active_jobs,
          (SELECT COUNT(*) FROM matches WHERE status='hired')          AS placements;
    """)

    # Driven off STAGES so the labels can never drift from the pipeline board.
    by_status = {f["status"]: f["n"] for f in fetch(
        "SELECT status, COUNT(*) AS n FROM matches "
        "WHERE archived = false GROUP BY status;")}
    funnel = [(label, sum(by_status.get(s, 0) for s in statuses))
              for _, label, statuses in STAGES]

    waiting = fetch("""
        SELECT c.id, c.name, COUNT(*) AS n_jobs
        FROM matches m JOIN candidates c ON c.id = m.candidate_id
        WHERE m.status = 'suggested' AND m.archived = false
        GROUP BY c.id, c.name
        ORDER BY c.name
        LIMIT 6;
    """)
    to_call = fetch("""
        SELECT job_uid, title, employer, city
        FROM jobs
        WHERE status = 'active' AND hr_verified = false
        ORDER BY created_at DESC
        LIMIT 6;
    """)
    recent = fetch("""
        SELECT id, name, title, source_method, created_at
        FROM candidates ORDER BY created_at DESC LIMIT 5;
    """)
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "stats": stats, "funnel": funnel, "waiting": waiting,
        "to_call": to_call, "recent": recent,
    })


# --------------------------------------------------------------------------
# candidates
# --------------------------------------------------------------------------

@router.get("/candidates", response_class=HTMLResponse)
def candidates(request: Request, q: str = ""):
    from match.search import _speaks_dutch

    query = q.strip()
    if query:
        from match.search import search_candidates
        rows = search_candidates(query, limit=20)
    else:
        rows = fetch("""
            SELECT c.id, c.name, c.title, c.location, c.languages, c.source_method,
                   c.created_at,
                   (SELECT COUNT(*) FROM matches m WHERE m.candidate_id = c.id) AS n_matches,
                   (c.embedding IS NOT NULL) AS embedded
            FROM candidates c ORDER BY c.created_at DESC;
        """)

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


@router.post("/candidates/{candidate_id}/suggest")
def suggest_top(candidate_id: int, top: int = Form(3), q: str = Form(default="")):
    """Clicking a name in the pool drops their best matches into Suggéré."""
    busy = fetch_one(
        "SELECT 1 AS x FROM matches WHERE candidate_id = %s AND status = ANY(%s) LIMIT 1;",
        (candidate_id, list(IN_PROGRESS)),
    )
    if not busy:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE matches SET status = 'suggested', updated_at = now()
                    WHERE id IN (
                        SELECT m.id FROM matches m
                        JOIN jobs j ON j.job_uid = m.job_uid
                        WHERE m.candidate_id = %s
                          AND m.status IN ('non_traite','declined','rejected')
                          AND m.archived = false
                          AND j.status = 'active'
                        ORDER BY m.llm_score DESC NULLS LAST
                        LIMIT %s
                    );
                """, (candidate_id, top))
            conn.commit()
    return RedirectResponse("/admin/pipeline?" + urlencode({"q": q}), status_code=303)


@router.post("/candidates/{candidate_id}/delete")
def delete_candidate(candidate_id: int):
    """
    Permanently erase a candidate and everything derived from them.

    GDPR Art. 17 (right to erasure): this must remove ALL personal data, including
    raw_text (which holds the full CV) and the embedding (derived from it).
    Their matches are removed automatically by ON DELETE CASCADE.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM candidates WHERE id = %s;", (candidate_id,))
        conn.commit()
    return RedirectResponse("/admin/candidates", status_code=303)


# --------------------------------------------------------------------------
# matches
# --------------------------------------------------------------------------

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


@router.post("/matches/pick")
def pick_match(match_id: int = Form(...), candidate_id: int = Form(...)):
    """Keep this job; the candidate's other suggestions go back to the pool."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # candidate_id in the WHERE clause: a forged match id can't be promoted.
            cur.execute(
                """UPDATE matches SET status='presented', updated_at=now()
                   WHERE id=%s AND candidate_id=%s;""",
                (match_id, candidate_id),
            )
            cur.execute(
                """UPDATE matches SET status='non_traite', updated_at=now()
                   WHERE candidate_id=%s AND status='suggested' AND id<>%s;""",
                (candidate_id, match_id),
            )
        conn.commit()
    return RedirectResponse("/admin/pipeline", status_code=303)


@router.post("/matches/{match_id}/clear")
def clear_match(match_id: int):
    """Take a finished card off the board.

    Accepted files are archived — the status is untouched so they stay on
    Recrutements. Declined ones go back to the pool, making the pairing
    selectable again. Only one of the two statements can ever match, so an
    in-progress card cannot be cleared.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE matches SET archived = true, updated_at = now() "
                "WHERE id = %s AND status = 'hired';",
                (match_id,),
            )
            cur.execute(
                "UPDATE matches SET status = 'non_traite', updated_at = now() "
                "WHERE id = %s AND status IN ('declined','rejected');",
                (match_id,),
            )
        conn.commit()
    return RedirectResponse("/admin/pipeline", status_code=303)


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

@router.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request, filter: str = "todo"):
    where = {
        "todo":     "WHERE j.status = 'active' AND j.hr_verified = false",
        "verified": "WHERE j.hr_verified = true",
        "all":      "",
    }.get(filter, "")

    rows = fetch(f"""
        SELECT j.job_uid, j.title, j.employer, j.city, j.is_remote, j.status,
               j.hr_verified, j.created_at,
               (j.created_at > now() - interval '24 hours') AS is_new,
               (SELECT COUNT(*) FROM matches m WHERE m.job_uid = j.job_uid) AS n_matches,
               EXISTS (SELECT 1 FROM matches m
                       WHERE m.job_uid = j.job_uid AND m.status = ANY(%s)) AS placed
        FROM jobs j
        {where}
        ORDER BY is_new DESC, j.created_at DESC;
    """, (list(PROTECTED),))

    counts = fetch_one("""
        SELECT
          COUNT(*) FILTER (WHERE status='active' AND hr_verified=false) AS todo,
          COUNT(*) FILTER (WHERE hr_verified=true)                      AS verified,
          COUNT(*)                                                      AS all
        FROM jobs;
    """)
    return templates.TemplateResponse(request, "admin/jobs.html", {
        "rows": rows, "filter": filter, "counts": counts,
    })


# Declared before /jobs/{job_uid}, otherwise "new" is read as a job_uid.
@router.get("/jobs/new", response_class=HTMLResponse)
def new_job_form(request: Request):
    return templates.TemplateResponse(request, "admin/job_new.html", {
        "form": {}, "details": None, "error": "",
    })


def _insert_manual_job(title, employer, city, is_remote,
                       apply_link, description, details) -> str:
    """Store a hand-added job with its embedding. Returns the new job_uid."""
    from psycopg.types.json import Json
    from pgvector.psycopg import register_vector
    from match.embeddings import embed
    from match.build_embeddings import job_to_text

    job_uid = f"manual-{uuid4()}"
    # Without a vector the job can never be matched, so it is computed here.
    # details matters too: job_to_text falls back to truncating the raw
    # description when it is missing.
    vector = embed(job_to_text({"title": title, "description": description,
                                "details": details}))
    with get_connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (job_uid, title, employer, city, is_remote,
                                  apply_link, description, details, source, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual', %s);
                """,
                (job_uid, title, employer or None, city or None, bool(is_remote),
                 apply_link or None, description or None,
                 Json(details) if details else None, vector),
            )
        conn.commit()
    return job_uid


@router.post("/jobs/paste", response_class=HTMLResponse)
def create_job_from_text(request: Request, raw: str = Form(default=""),
                         apply_link: str = Form(default="")):
    """One shot: paste an advert, get a stored job with an embedding."""
    from jobs.job_parser import parse_pasted_job

    text = raw.strip()
    if not text:
        return RedirectResponse("/admin/jobs/new", status_code=303)

    try:
        parsed = parse_pasted_job(text)
    except Exception as e:
        return templates.TemplateResponse(request, "admin/job_new.html", {
            "form": {"description": text}, "details": None,
            "error": f"Le texte n'a pas pu être analysé : {e}",
        })

    # No title means nothing usable was found — fall back to the manual form
    # rather than storing a nameless job.
    if not parsed.title:
        return templates.TemplateResponse(request, "admin/job_new.html", {
            "form": {"description": text}, "details": parsed.details.model_dump(),
            "error": "Le poste n'a pas pu être identifié. Complétez le formulaire ci-dessous.",
        })

    job_uid = _insert_manual_job(parsed.title, parsed.employer, parsed.city,
                                 parsed.is_remote, apply_link, text,
                                 parsed.details.model_dump())
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)


@router.post("/jobs/new")
def create_job(title: str = Form(...),
               employer: str = Form(default=""),
               city: str = Form(default=""),
               is_remote: str = Form(default=""),
               apply_link: str = Form(default=""),
               description: str = Form(default=""),
               details_json: str = Form(default="")):
    """Add an offer by hand, filling the form yourself."""
    try:
        details = json.loads(details_json) if details_json.strip() else None
    except json.JSONDecodeError:
        details = None

    job_uid = _insert_manual_job(title, employer, city, is_remote == "on",
                                 apply_link, description, details)
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)


@router.get("/jobs/{job_uid}", response_class=HTMLResponse)
def job_detail(request: Request, job_uid: str, locked: int = 0, edit: int = 0):
    job = fetch_one("SELECT * FROM jobs WHERE job_uid = %s;", (job_uid,))
    details = job["details"] if job else None
    if isinstance(details, str):
        details = json.loads(details or "{}")

    candidates = fetch("""
        SELECT m.id, m.candidate_id, m.llm_score, m.verdict, m.eligible, m.status,
               m.summary, m.strengths, m.gaps, m.blocking_reasons,
               c.name, c.title
        FROM matches m JOIN candidates c ON c.id = m.candidate_id
        WHERE m.job_uid = %s
        ORDER BY m.llm_score DESC NULLS LAST;
    """, (job_uid,))
    for c in candidates:
        c["strengths"] = as_list(c["strengths"])
        c["gaps"] = as_list(c["gaps"])
        c["blocking_reasons"] = as_list(c["blocking_reasons"])

    placed = any(c["status"] in PROTECTED for c in candidates)
    return templates.TemplateResponse(request, "admin/job_detail.html", {
        "j": job, "d": details or {}, "candidates": candidates,
        "placed": placed, "locked": locked, "edit": edit,
    })


@router.post("/jobs/{job_uid}/hr")
def save_hr(job_uid: str,
            hr_verified: str = Form(default=""),
            employer: str = Form(default=""),
            city: str = Form(default=""),
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
                    employer  = NULLIF(%s, ''),
                    city      = NULLIF(%s, ''),
                    hr_salary = NULLIF(%s, ''),
                    hr_notes  = NULLIF(%s, ''),
                    note      = NULLIF(%s, ''),
                    status    = %s
                WHERE job_uid = %s;
                """,
                (verified, verified, verified, employer, city,
                 hr_salary, hr_notes, note, status, job_uid),
            )
        conn.commit()
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)


@router.post("/jobs/{job_uid}/edit")
def edit_job(job_uid: str,
             title: str = Form(...),
             apply_link: str = Form(default=""),
             is_remote: str = Form(default=""),
             description: str = Form(default=""),
             languages: str = Form(default=""),
             contract_type: str = Form(default=""),
             experience_required: str = Form(default=""),
             schedule: str = Form(default=""),
             salary: str = Form(default=""),
             missions: str = Form(default=""),
             requirements: str = Form(default=""),
             benefits: str = Form(default="")):
    """Correct the offer itself, structured fields included.

    The embedding is rebuilt from the new text — leave it stale and matching
    keeps scoring against the description you just replaced.
    """
    from psycopg.types.json import Json
    from pgvector.psycopg import register_vector
    from match.embeddings import embed
    from match.build_embeddings import job_to_text

    details = {
        "missions": _lines(missions),
        "requirements": _lines(requirements),
        "languages": _lines(languages),
        "benefits": _lines(benefits),
        "contract_type": contract_type or None,
        "salary": salary or None,
        "schedule": schedule or None,
        "experience_required": experience_required or None,
    }
    vector = embed(job_to_text({"title": title, "description": description,
                                "details": details}))

    with get_connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs SET
                    title       = %s,
                    apply_link  = NULLIF(%s, ''),
                    is_remote   = %s,
                    description = NULLIF(%s, ''),
                    details     = %s,
                    embedding   = %s
                WHERE job_uid = %s;
                """,
                (title, apply_link, is_remote == "on", description,
                 Json(details), vector, job_uid),
            )
        conn.commit()
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)


@router.post("/jobs/{job_uid}/match")
def run_job_matching(job_uid: str, top: int = Form(3)):
    """Reverse matching: find the best candidates for this job."""
    from match.rerank import rerank_for_job
    rerank_for_job(job_uid, top_n=top)
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)


@router.post("/jobs/{job_uid}/present")
def present_candidates(job_uid: str, match_ids: list[int] = Form(default=[])):
    """Shortlist several candidates on one job so HR picks who fits."""
    if match_ids:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # job_uid in the WHERE clause: a forged id from another job can't be flipped.
                cur.execute(
                    """UPDATE matches SET status='presented', updated_at=now()
                       WHERE id = ANY(%s) AND job_uid = %s;""",
                    (match_ids, job_uid),
                )
            conn.commit()
    return RedirectResponse(f"/admin/jobs/{job_uid}", status_code=303)


@router.post("/jobs/{job_uid}/delete")
def delete_job(job_uid: str):
    """Permanently remove a job. Its matches go too (ON DELETE CASCADE).

    Refused while a candidate is live on it or has been recruited: the cascade
    would take that match with it, losing the file or the recruitment record.
    """
    if fetch_one("SELECT 1 AS x FROM matches "
                 "WHERE job_uid = %s AND status = ANY(%s) LIMIT 1;",
                 (job_uid, list(PROTECTED))):
        return RedirectResponse(f"/admin/jobs/{job_uid}?locked=1", status_code=303)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE job_uid = %s;", (job_uid,))
        conn.commit()
    return RedirectResponse("/admin/jobs?filter=all", status_code=303)


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

@router.get("/pipeline", response_class=HTMLResponse)
def pipeline(request: Request, eligible: str = "1", q: str = ""):
    filters = ["m.archived = false"]
    if eligible == "1":
        # NULL eligible = hand-picked, never assessed — it must not be filtered out.
        filters.append("m.eligible IS NOT FALSE")
    where = "WHERE " + " AND ".join(filters)

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
    board = {key: [r for r in rows if r["status"] in statuses]
             for key, _, statuses in STAGES}

    # Suggéré is yours, not the matcher's — never hide it behind the eligibility filter.
        # A candidate enters this column by being clicked (they get a 'suggested'
    # match), but the card then offers every job still open to them — otherwise
    # it freezes whatever existed at click time and the best options stay hidden.
    grouped: dict[int, dict] = {}
    for r in fetch("""
        SELECT m.id, m.candidate_id, m.job_uid, m.llm_score, m.status,
               c.name AS candidate, j.title AS job, j.employer, j.city
        FROM matches m
        JOIN candidates c ON c.id = m.candidate_id
        JOIN jobs j       ON j.job_uid = m.job_uid
        WHERE m.archived = false
          AND m.eligible IS NOT FALSE
          AND m.status IN ('suggested', 'non_traite')
          AND j.status = 'active'
          AND EXISTS (SELECT 1 FROM matches s
                      WHERE s.candidate_id = m.candidate_id
                        AND s.status = 'suggested' AND s.archived = false)
        ORDER BY m.candidate_id, m.llm_score DESC NULLS LAST;
    """):
        grouped.setdefault(r["candidate_id"], {
            "candidate_id": r["candidate_id"], "name": r["candidate"], "jobs": [],
        })["jobs"].append(r)
    shortlist = list(grouped.values())

    # Unfinished candidates only: accepted ones live on Recrutements.
    query = q.strip()
    pool = fetch("""
        SELECT c.id AS candidate_id, c.name,
               (SELECT j.title FROM matches m JOIN jobs j ON j.job_uid = m.job_uid
                WHERE m.candidate_id = c.id AND m.status IN ('presented','applied')
                LIMIT 1) AS active_job,
               EXISTS (SELECT 1 FROM matches m
                       WHERE m.candidate_id = c.id AND m.status = 'suggested') AS shortlisted
        FROM candidates c
        WHERE NOT EXISTS (SELECT 1 FROM matches m
                          WHERE m.candidate_id = c.id AND m.status = 'hired')
          AND (%s = '' OR COALESCE(c.name, '') ILIKE %s)
        ORDER BY c.created_at DESC
        LIMIT 50;
    """, (query, f"%{query}%"))

    return templates.TemplateResponse(request, "admin/pipeline.html", {
        "stages": STAGES, "status_choices": STATUS_CHOICES, "labels": STATUS_LABELS,
        "board": board, "shortlist": shortlist, "pool": pool, "q": query,
        "eligible": eligible, "total": len(rows),
    })


# --------------------------------------------------------------------------
# recrutements
# --------------------------------------------------------------------------

@router.get("/placements", response_class=HTMLResponse)
def placements(request: Request):
    rows = fetch("""
        SELECT m.id, m.candidate_id, m.job_uid, m.updated_at,
               c.name AS candidate, j.title AS job, j.employer, j.city
        FROM matches m
        JOIN candidates c ON c.id = m.candidate_id
        JOIN jobs j       ON j.job_uid = m.job_uid
        WHERE m.status = 'hired'
        ORDER BY m.updated_at DESC;
    """)
    return templates.TemplateResponse(request, "admin/placements.html", {"rows": rows})


@router.post("/placements/{match_id}/remove")
def remove_placement(match_id: int):
    """Undo a placement. The pairing returns to the pool instead of being deleted,
    so a mis-clicked Accepté can be walked back."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE matches SET status='non_traite', archived=false, updated_at=now() "
                "WHERE id=%s AND status='hired';",
                (match_id,),
            )
        conn.commit()
    return RedirectResponse("/admin/placements", status_code=303)