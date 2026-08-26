import re
import json
import time
import logging
from extract.llm_client import client, MODEL
from extract.schema import Candidate
from extract.regex_fields import find_email, find_phone

logger = logging.getLogger(__name__)
VALID_EMAIL = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def clean_text(text: str) -> str:
    """Cheap cleanup: strip RTL/LTR marks and collapse excess whitespace."""
    text = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


PROMPT_TEMPLATE = """You are an expert CV parser for a recruitment company.
Extract structured information from the CV text below. The CV may be in French, Arabic,
or English, and may contain OCR noise (misread characters, scrambled order).

Return ONLY a valid JSON object (no markdown, no commentary) with EXACTLY these keys:
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
- Use null (or [] for lists) for anything missing.
- Correct obvious OCR errors only when confident.
- Keep skills as short, individual items.
- Never invent information that is not in the text.
- Put each project (title + what it did) as one string in "projects".

CV TEXT:
\"\"\"
{{CV_TEXT}}
\"\"\"
"""


def _call_llm(prompt: str, retries: int = 3) -> str:
    """Call the model; retry on empty responses (free models blip sometimes)."""
    for attempt in range(1, retries + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content
        if content and content.strip():
            return content
        logger.warning("Empty LLM response (attempt %d/%d), retrying...", attempt, retries)
        time.sleep(2)
    raise ValueError("LLM returned an empty response after retries")


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in LLM response: {raw[:300]!r}")
    return json.loads(match.group(0))


def _validate_contact(candidate: Candidate, cleaned_text: str, source_is_ocr: bool) -> Candidate:
    regex_email = find_email(cleaned_text)
    if regex_email and VALID_EMAIL.match(regex_email):
        candidate.email = regex_email
    elif not (candidate.email and VALID_EMAIL.match(candidate.email)):
        if candidate.email:
            candidate.warnings.append(f"Email unreadable, needs review: '{candidate.email}'")
        candidate.email = None

    regex_phone = find_phone(cleaned_text)
    if regex_phone:
        candidate.phone = regex_phone
    if candidate.phone:
        digits = re.sub(r"\D", "", candidate.phone)
        if not (9 <= len(digits) <= 15):
            candidate.warnings.append(f"Phone looks invalid: '{candidate.phone}'")
            candidate.phone = None

    if source_is_ocr:
        if candidate.email:
            candidate.warnings.append("Email from a scanned/photo CV — verify with candidate.")
        if candidate.phone:
            candidate.warnings.append("Phone from a scanned/photo CV — verify with candidate.")

    return candidate


def parse_cv(text: str, source_is_ocr: bool = False) -> Candidate:
    cleaned = clean_text(text)
    prompt = PROMPT_TEMPLATE.replace("{{CV_TEXT}}", cleaned)

    raw = _call_llm(prompt)
    data = _extract_json(raw)

    candidate = Candidate(**data)
    candidate = _validate_contact(candidate, cleaned, source_is_ocr)
    return candidate


if __name__ == "__main__":
    import argparse
    from ingest.extractor import extract_text

    parser = argparse.ArgumentParser(description="Parse a CV into structured JSON.")
    parser.add_argument("path", help="Path to the CV file")
    args = parser.parse_args()

    text, method = extract_text(args.path, with_method=True)
    candidate = parse_cv(text, source_is_ocr=(method == "ocr"))
    print(json.dumps(candidate.model_dump(), indent=2, ensure_ascii=False))