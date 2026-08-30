import os
import base64
import hashlib
import secrets
from pathlib import Path

import requests
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from db.database import get_connection

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")

router = APIRouter(tags=["candidate-auth"])


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


@router.get("/auth/google")
def auth_google(request: Request, next: str = "/me"):
    """Start the Google sign-in flow (PKCE, because we are a server-rendered app)."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(500, "Supabase is not configured")

    # Remember the intended destination; only internal paths (no open redirect).
    request.session["post_login_next"] = next if next.startswith("/") else "/me"

    verifier, challenge = _pkce_pair()
    request.session["pkce_verifier"] = verifier

    url = (
        f"{SUPABASE_URL}/auth/v1/authorize"
        f"?provider=google"
        f"&redirect_to={APP_BASE_URL}/auth/callback"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=s256"
    )
    return RedirectResponse(url, status_code=302)


@router.get("/auth/callback")
def auth_callback(request: Request, code: str = "", error_description: str = ""):
    """Exchange the one-time code for a session and record the verified email."""
    if error_description:
        return templates.TemplateResponse(
            request, "error.html", {"message": f"Connexion refusée : {error_description}"}
        )

    verifier = request.session.pop("pkce_verifier", None)
    if not code or not verifier:
        return templates.TemplateResponse(
            request, "error.html", {"message": "Session de connexion invalide. Réessayez."}
        )

    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
        headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"auth_code": code, "code_verifier": verifier},
        timeout=20,
    )
    if resp.status_code != 200:
        return templates.TemplateResponse(
            request, "error.html",
            {"message": "Échec de la connexion Google. Réessayez."},
        )

    data = resp.json()
    email = (data.get("user") or {}).get("email")
    if not email:
        return templates.TemplateResponse(
            request, "error.html", {"message": "Aucune adresse email retournée par Google."}
        )

    # A Google-verified email is authoritative — unlike one read by OCR.
    # One identity per session: signing in as candidate ends any admin session.
    request.session.pop("admin", None)
    request.session.pop("email", None)

    # A Google-verified email is authoritative — unlike one read by OCR.
    request.session["candidate_email"] = email.lower()

    target = request.session.pop("post_login_next", "/me")
    return RedirectResponse(target, status_code=303)


@router.get("/me", response_class=HTMLResponse)
def my_profile(request: Request):
    email = request.session.get("candidate_email")
    if not email:
        return RedirectResponse("/auth/google", status_code=303)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM candidates WHERE lower(email) = %s;", (email,))
            row = cur.fetchone()
            candidate = dict(zip([d.name for d in cur.description], row)) if row else None

            matches = []
            if candidate:
                cur.execute(
                    """
                    SELECT m.llm_score, m.status, m.eligible, m.summary,
                           j.title, j.employer, j.city, j.apply_link
                    FROM matches m JOIN jobs j ON j.job_uid = m.job_uid
                    WHERE m.candidate_id = %s AND m.eligible = true
                      AND m.status IN ('presented','approved','applied','hired')
                    ORDER BY m.llm_score DESC NULLS LAST;
                    """,
                    (candidate["id"],),
                )
                cols = [d.name for d in cur.description]
                matches = [dict(zip(cols, r)) for r in cur.fetchall()]

    # A logged-in candidate owns this profile, so they may edit it.
    if candidate:
        request.session["own_candidate_id"] = candidate["id"]

    return templates.TemplateResponse(request, "me.html", {
        "email": email, "candidate": candidate, "matches": matches,
    })


@router.get("/auth/logout")
def candidate_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)