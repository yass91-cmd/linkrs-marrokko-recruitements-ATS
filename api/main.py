import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from psycopg.types.json import Json
from pgvector.psycopg import register_vector
from dotenv import load_dotenv

from ingest.extractor import extract_text, ExtractionError
from extract.cv_parser import parse_cv
from db.candidates_repo import save_candidate
from db.database import get_connection
from match.embeddings import embed
from match.build_embeddings import candidate_to_text
from api.admin import router as admin_router
from api.auth import router as auth_router

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
MAX_UPLOAD_MB = 10
ALLOWED = {".pdf", ".docx", ".jpg", ".jpeg", ".png"}

# A missing secret must stop the application, never silently fall back to an
# insecure default — a known signing key means forgeable admin sessions.
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is not set — refusing to start insecurely")

app = FastAPI(title="CV Matcher — Linkrs Morocco")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=8 * 3600,      # sessions expire after 8 hours
    same_site="lax",       # cookie not sent on cross-site POSTs (partial CSRF defence)
    https_only=False,      # set True once deployed behind HTTPS
)

app.include_router(auth_router)
app.include_router(admin_router)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _embed_candidate(candidate_id: int, row: dict) -> None:
    """(Re)compute the candidate's embedding after creation or edit."""
    vector = embed(candidate_to_text(row))
    with get_connection() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("UPDATE candidates SET embedding = %s WHERE id = %s;",
                        (vector, candidate_id))
        conn.commit()


def _lines(value: str | None) -> list[str]:
    """Turn a textarea (one item per line) into a list."""
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _zip_rows(form, keys: list[str], names: list[str]) -> list[dict]:
    """Rebuild a list of dicts from parallel repeated form fields."""
    columns = [form.getlist(k) for k in keys]
    rows = []
    for values in zip(*columns):
        if any(v.strip() for v in values):
            rows.append({n: (v.strip() or None) for n, v in zip(names, values)})
    return rows


# --------------------------------------------------------------------------
# public routes
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in ALLOWED:
        return templates.TemplateResponse(
            request, "error.html",
            {"message": f"Format non supporté : {suffix or 'inconnu'}. "
                        f"Formats acceptés : PDF, DOCX, JPG, PNG."},
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_MB * 1024 * 1024:
        return templates.TemplateResponse(
            request, "error.html",
            {"message": f"Fichier trop volumineux (maximum {MAX_UPLOAD_MB} Mo)."},
        )

    # The ingestion layer works on file paths. The original CV is deliberately
    # NOT retained on the server once processed (data minimisation).
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(contents)
        tmp.close()

        text, method = extract_text(tmp.name, with_method=True)
        candidate = parse_cv(text, source_is_ocr=(method == "ocr"))
        candidate_id = save_candidate(candidate, source_method=method, raw_text=text)
        _embed_candidate(candidate_id, candidate.model_dump())

    except ExtractionError as e:
        return templates.TemplateResponse(request, "error.html", {"message": str(e)})
    except Exception:
        # Never leak internals to a public user; details stay in the server logs.
        return templates.TemplateResponse(
            request, "error.html",
            {"message": "Une erreur est survenue lors de l'analyse. Veuillez réessayer."},
        )
    finally:
        os.unlink(tmp.name)

    # Remember which profile this visitor may edit (authorization, not authentication).
    request.session["own_candidate_id"] = candidate_id

    return templates.TemplateResponse(
        request, "result.html",
        {"candidate": candidate, "candidate_id": candidate_id, "method": method},
    )


@app.post("/candidate/{candidate_id}/update", response_class=HTMLResponse)
async def update_candidate(request: Request, candidate_id: int):
    # Authorization: only the visitor who uploaded this CV may edit it.
    # Without this check, anyone could overwrite any profile by guessing an id (IDOR).
    if request.session.get("own_candidate_id") != candidate_id:
        return templates.TemplateResponse(
            request, "error.html",
            {"message": "Vous n'êtes pas autorisé à modifier ce profil."},
        )

    form = await request.form()

    education = _zip_rows(form, ["edu_degree", "edu_institution", "edu_year"],
                          ["degree", "institution", "year"])
    experience = _zip_rows(form, ["exp_title", "exp_company", "exp_duration"],
                           ["title", "company", "duration"])

    row = {
        "name": form.get("name") or None,
        "title": form.get("title") or None,
        "email": form.get("email") or None,
        "phone": form.get("phone") or None,
        "location": form.get("location") or None,
        "languages": _lines(form.get("languages")),
        "skills": _lines(form.get("skills")),
        "projects": _lines(form.get("projects")),
        "summary": form.get("summary") or None,
        "education": education,
        "experience": experience,
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE candidates SET
                    name = %s, title = %s, email = %s, phone = %s, location = %s,
                    languages = %s, skills = %s, projects = %s, summary = %s,
                    education = %s, experience = %s,
                    warnings = '[]'::jsonb
                WHERE id = %s;
                """,
                (row["name"], row["title"], row["email"], row["phone"], row["location"],
                 Json(row["languages"]), Json(row["skills"]), Json(row["projects"]),
                 row["summary"], Json(education), Json(experience), candidate_id),
            )
        conn.commit()

    # The profile text changed, so the embedding must be recomputed —
    # otherwise matching would still use the uncorrected data.
    _embed_candidate(candidate_id, row)

    return templates.TemplateResponse(request, "confirmed.html", {"name": row["name"]})