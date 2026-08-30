import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

router = APIRouter(tags=["auth"])


def require_admin(request: Request):
    """Dependency: block the request unless the session is authenticated."""
    if not request.session.get("admin"):
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return True


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise HTTPException(500, "ADMIN_EMAIL or ADMIN_PASSWORD is not configured")

    # Constant-time comparison on BOTH fields: a normal == leaks information
    # through timing, and short-circuiting on email would reveal whether it exists.
    email_ok = secrets.compare_digest(email.strip().lower(), ADMIN_EMAIL.strip().lower())
    password_ok = secrets.compare_digest(password, ADMIN_PASSWORD)

    if email_ok and password_ok:
        # One identity per session: signing in as recruiter ends any candidate session.
        request.session.pop("candidate_email", None)
        request.session.pop("own_candidate_id", None)
        request.session["admin"] = True
        request.session["email"] = ADMIN_EMAIL
        return RedirectResponse("/admin", status_code=303)

    # One generic message — never reveal which field was wrong.
    return RedirectResponse("/login?error=1", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)