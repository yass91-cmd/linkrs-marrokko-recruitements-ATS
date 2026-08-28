import re
import json
import time
import logging
from extract.llm_client import client, MODEL
from jobs.job_schema import JobDetails

logger = logging.getLogger(__name__)

PROMPT = """You are an expert job-offer parser for a recruitment company.
Extract structured information from the job description below (French / English / Arabic).

Return ONLY a valid JSON object with EXACTLY these keys:
{
  "missions": [strings],
  "requirements": [strings],
  "languages": [strings],
  "contract_type": string or null,
  "salary": string or null,
  "schedule": string or null,
  "benefits": [strings],
  "experience_required": string or null
}

Rules:
- Use [] for missing lists and null for missing scalars.
- "languages": languages the job requires (e.g. Néerlandais, Français, Anglais).
- Keep each mission / requirement / benefit as a short individual string.
- Never invent information not in the text.

JOB DESCRIPTION:
\"\"\"
{{DESC}}
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


def parse_job_details(description: str, retries: int = 4) -> JobDetails:
    prompt = PROMPT.replace("{{DESC}}", description or "")
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
                return JobDetails(**_extract_json(content))
            except Exception as e:
                last = str(e)[:120]
                logger.warning("Job-parse retry %d/%d: %s", attempt, retries, last)
        time.sleep(2)
    raise ValueError(f"Failed to parse job after {retries} attempts. Last: {last}")


if __name__ == "__main__":
    import os
    import requests
    from dotenv import load_dotenv

    load_dotenv()
    resp = requests.get(
        "https://jsearch.p.rapidapi.com/search-v2",
        headers={"x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
                 "x-rapidapi-host": "jsearch.p.rapidapi.com"},
        params={"query": "néerlandais", "country": "ma", "num_pages": "1", "date_posted": "all"},
    )
    jobs = resp.json().get("data", {}).get("jobs", [])
    if jobs:
        job = jobs[0]
        print("JOB:", job.get("job_title"), "\n")
        details = parse_job_details(job.get("job_description", ""))
        print(json.dumps(details.model_dump(), indent=2, ensure_ascii=False))