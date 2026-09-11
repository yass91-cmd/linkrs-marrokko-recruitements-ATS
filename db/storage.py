"""
Original CV files, stored in a private Supabase Storage bucket.

Step 1 originally deleted the uploaded file after extraction (data minimisation:
keep only what is needed). That trade-off is revisited here — the original is now
kept so a recruiter can view exactly what the candidate sent, alongside what the
pipeline extracted from it.

The bucket ('cv-files') is private. Files are never served by a public URL; every
access goes through a short-lived SIGNED url, generated on demand.
"""
import os
import logging

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
BUCKET = "cv-file"


def _headers() -> dict:
    if not SUPABASE_URL or not SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY are not configured")
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def upload_cv_file(contents: bytes, file_path: str, content_type: str) -> str | None:
    """
    Upload the original file to the private bucket. Returns the stored path,
    or None if storage isn't configured — callers must keep working without it
    (an original file is a bonus, not a requirement for the pipeline to run).
    """
    if not SUPABASE_URL or not SERVICE_KEY:
        logger.warning("Supabase Storage not configured — original file not kept")
        return None

    resp = requests.put(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{file_path}",
        headers={**_headers(), "Content-Type": content_type, "x-upsert": "true"},
        data=contents,
        timeout=30,
    )
    if resp.status_code >= 300:
        logger.warning("CV file upload failed (%s): %s", resp.status_code, resp.text[:200])
        return None
    return file_path


def signed_url(file_path: str, expires_in: int = 300) -> str | None:
    """A time-limited URL for one file, valid for `expires_in` seconds (default 5 min)."""
    if not file_path or not SUPABASE_URL or not SERVICE_KEY:
        return None

    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/sign/{BUCKET}/{file_path}",
        headers=_headers(),
        json={"expiresIn": expires_in},
        timeout=15,
    )
    if resp.status_code >= 300:
        logger.warning("Could not sign URL for %s: %s", file_path, resp.text[:200])
        return None
    # Supabase's sign response is relative and omits the "/storage/v1" prefix
    # (e.g. "/object/sign/cv-file/...?token=..."), so it must be re-added here.
    return f"{SUPABASE_URL}/storage/v1{resp.json()['signedURL']}"


def delete_cv_file(file_path: str) -> None:
    """
    Permanently remove a stored file — part of GDPR erasure (Art. 17), not optional.
    Never raises: a missing/already-deleted file should not block candidate deletion.
    """
    if not file_path or not SUPABASE_URL or not SERVICE_KEY:
        return
    try:
        requests.delete(
            f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{file_path}",
            headers=_headers(),
            timeout=15,
        )
    except Exception as e:
        logger.warning("Could not delete stored file %s: %s", file_path, e)
