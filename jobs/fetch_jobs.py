import os
import requests
import logging
from dotenv import load_dotenv
from jobs.jobs_repo import save_job
from jobs.job_parser import parse_job_details

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Keywords that signal a Dutch-language requirement (FR/EN/NL variants)
DUTCH_KEYWORDS = [
    "dutch", "nederlands", "nederlandstalig",
    "néerlandais", "neerlandais",
    "néerlandophone", "neerlandophone",
    "flamand", "flemish",
]


def requires_dutch(job: dict) -> bool:
    """Verify the job really mentions Dutch (guards against irrelevant API hits)."""
    text = f"{job.get('job_title', '')} {job.get('job_description', '')}".lower()
    return any(kw in text for kw in DUTCH_KEYWORDS)


def fetch_dutch_jobs(query: str = "néerlandais", pages: int = 1):
    url = "https://jsearch.p.rapidapi.com/search-v2"
    headers = {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }
    params = {
        "query": query,
        "country": "ma",
        "language": "fr",
        "num_pages": str(pages),
        "date_posted": "all",
    }

    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    jobs = resp.json().get("data", {}).get("jobs", [])
    logger.info("API returned %d jobs", len(jobs))

    inserted = 0
    for job in jobs:
        if not requires_dutch(job):
            logger.info("Skipped (no Dutch): %s", job.get("job_title"))
            continue

        # Structure the free-text description with the LLM.
        # Fail-safe: if structuring fails, still store the job without details.
        try:
            details = parse_job_details(job.get("job_description", "")).model_dump()
        except Exception as e:
            logger.warning("Could not structure '%s': %s", job.get("job_title"), e)
            details = None

        if save_job(job, details=details):
            inserted += 1
            logger.info("Saved: %s", job.get("job_title"))
        else:
            logger.info("Already exists: %s", job.get("job_title"))

    return len(jobs), inserted


if __name__ == "__main__":
    total, inserted = fetch_dutch_jobs()
    print(f"\nFetched {total} jobs — inserted {inserted} new Dutch jobs.")