"""
Vision-based CV parsing.

The OCR pipeline (Tesseract -> text -> LLM) loses information the moment the
image becomes text: reading order is inferred from glyph positions, so
multi-column CVs come out scrambled, and character confusions (l/1, rn/m) are
unrecoverable downstream.

A multimodal model reads the page directly. It perceives layout, so columns are
read in the correct order, and it never passes through a lossy text stage.

This module is a second implementation of Step 2, deliberately kept alongside
the OCR path so the two can be compared on the same documents.
"""
import base64
import json
import logging
import re
import time

import pymupdf

from extract.llm_client import client
from extract.schema import Candidate

logger = logging.getLogger(__name__)

# Free vision endpoints are volatile: models are withdrawn (404) and the shared
# free pool saturates (429). The parser therefore tries a list rather than
# depending on any single model, and reports which one actually answered.
# "openrouter/free" is an auto-router and makes a good last resort.
VISION_MODELS = [
    "google/gemma-4-31b-it:free",
    "minimax/minimax-m3:free",
    "google/gemma-4-26b-a4b-it:free",
    "openrouter/free",
]

# Rendering resolution for PDF pages. Higher is sharper but costs tokens;
# 150 DPI is legible for body text without inflating the payload.
RENDER_DPI = 150
MAX_PAGES = 3


PROMPT = """You are an expert CV parser for a recruitment company in Morocco.

Read this CV image and extract the information into JSON. The CV may be in
French, Arabic or English, and may be a photograph or a scan.

Return ONLY a valid JSON object with EXACTLY these keys:
{
  "name": string or null,
  "title": string or null,
  "email": string or null,
  "phone": string or null,
  "location": string or null,
  "skills": [strings],
  "languages": [strings],
  "education": [{"degree": string, "institution": string, "year": string}],
  "experience": [{"title": string, "company": string, "duration": string}],
  "projects": [strings],
  "years_experience": number or null,
  "summary": string or null
}

Rules:
- Read the layout carefully: many CVs have a sidebar and a main column.
  Keep each item with the section it belongs to.
- Transcribe the email and phone character by character. Do not guess or
  normalise them. If a character is genuinely illegible, use null rather than
  inventing one.
- Use [] for missing lists and null for missing scalars.
- Never invent information that is not visible in the image.
- Output only the JSON object, no commentary.
"""


def _render_pages(path: str) -> list[bytes]:
    """Render a PDF or image file to PNG bytes, one entry per page.

    PyMuPDF opens images as single-page documents, so one code path covers
    both PDFs and photographs (and avoids a PIL dependency entirely).
    """
    doc = pymupdf.open(path)
    pages = []
    for index, page in enumerate(doc):
        if index >= MAX_PAGES:
            break
        pixmap = page.get_pixmap(dpi=RENDER_DPI)
        pages.append(pixmap.tobytes("png"))
    doc.close()
    return pages


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in vision response: {raw[:200]!r}")
    return json.loads(match.group(0))


def parse_cv_from_file(path: str, attempts_per_model: int = 2) -> Candidate:
    """Parse a CV image or PDF directly with a multimodal model.

    Tries each model in VISION_MODELS in turn. A model that is withdrawn (404)
    or rate-limited (429) is skipped immediately rather than retried, since
    neither condition resolves within the retry window.
    """
    pages = _render_pages(path)
    if not pages:
        raise ValueError(f"No renderable pages in {path}")

    content = [{"type": "text", "text": PROMPT}]
    for png in pages:
        encoded = base64.b64encode(png).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encoded}"},
        })

    last_error = None
    for model in VISION_MODELS:
        for attempt in range(1, attempts_per_model + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0,
                )
            except Exception as e:
                last_error = f"{model}: {type(e).__name__}"
                status = getattr(e, "status_code", None)
                if status in (404, 429):
                    # Withdrawn or saturated: no point retrying this model.
                    logger.warning("%s unavailable (%s), trying next model", model, status)
                    break
                logger.warning("%s error attempt %d: %s", model, attempt, str(e)[:120])
                time.sleep(2)
                continue

            # Some providers return choices=None with an error payload in the
            # body rather than an HTTP error, so this cannot be indexed blindly.
            choices = getattr(response, "choices", None)
            raw = choices[0].message.content or "" if choices else ""
            if not raw.strip():
                logger.warning("%s returned empty response (attempt %d)", model, attempt)
                time.sleep(2)
                continue

            try:
                candidate = Candidate(**_extract_json(raw))
                logger.info("Parsed with %s", model)
                return candidate
            except Exception as e:
                last_error = f"{model}: {str(e)[:120]}"
                logger.warning("%s parse retry %d: %s", model, attempt, last_error)
                time.sleep(2)

    raise ValueError(f"Vision parsing failed on all models. Last: {last_error}")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Parse a CV image with a vision model.")
    parser.add_argument("path")
    args = parser.parse_args()

    candidate = parse_cv_from_file(args.path)
    print(json.dumps(candidate.model_dump(), indent=2, ensure_ascii=False))
