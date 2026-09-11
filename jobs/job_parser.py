import re
import json
import time
import logging
from extract.llm_client import client, MODEL
from jobs.job_schema import JobDetails, PastedJob

logger = logging.getLogger(__name__)

PASTE_PROMPT = """You are an expert job-offer parser for a recruitment company.
The text below was copied from a job board (French / English / Dutch / Arabic).
It contains the job title, the employer, the location and the description all mixed together.

Return ONLY a valid JSON object with EXACTLY these keys:
{
  "title": string or null,
  "employer": string or null,
  "city": string or null,
  "is_remote": true or false,
  "details": {
    "missions": [strings],
    "requirements": [strings],
    "languages": [strings],
    "contract_type": string or null,
    "salary": string or null,
    "schedule": string or null,
    "benefits": [strings],
    "experience_required": string or null
  }
}

Rules:
- Write EVERY extracted value in English, translating from French, Dutch or
  Arabic where needed. This includes the title, the city, the missions, the
  requirements and the benefits.
- Exception: "employer" keeps the company's name exactly as printed.
- "title" is the job title only, without the company or the city.
- "city" uses the standard Latin spelling (Casablanca, Rabat, Tangier,
  Marrakesh, Agadir), never Arabic script.
- "is_remote" is true only if the text says télétravail / remote / thuiswerk /
  work from home.
- "languages" are the languages the job requires, named in English
  (Dutch, French, English, Arabic).
- Use [] for missing lists and null for missing scalars. Never invent anything.

PASTED TEXT:
\"\"\"
{{TEXT}}
\"\"\"
"""


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON found: {raw[:200]!r}")
    return json.loads(m.group(0))


def _ask_json(prompt: str, model_cls, retries: int = 4):
    """Ask the model for one JSON object and validate it, retrying on bad output."""
    messages = [
        {"role": "system", "content": "You are a strict JSON extraction API. Output ONLY one valid JSON object."},
        {"role": "user", "content": prompt},
    ]
    last = None
    for attempt in range(1, retries + 1):
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, temperature=0 if attempt == 1 else 0.3,
        )
        content = resp.choices[0].message.content or ""
        if content.strip():
            try:
                return model_cls(**_extract_json(content))
            except Exception as e:
                last = str(e)[:120]
                logger.warning("Parse retry %d/%d: %s", attempt, retries, last)
        time.sleep(2)
    raise ValueError(f"Failed to parse after {retries} attempts. Last: {last}")


def parse_pasted_job(text: str, retries: int = 4) -> PastedJob:
    """Read a whole pasted advert: title, employer, city and the structured body."""
    return _ask_json(PASTE_PROMPT.replace("{{TEXT}}", text or ""), PastedJob, retries)


if __name__ == "__main__":
    import sys

    parsed = parse_pasted_job(sys.stdin.read())
    print(json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False))