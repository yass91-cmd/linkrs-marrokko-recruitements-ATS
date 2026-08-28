import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Keywords that signal a Dutch-language requirement (FR/EN/NL variants)
DUTCH_KEYWORDS = [
    "dutch", "nederlands", "nederlandstalig",
    "néerlandais", "neerlandais",
    "néerlandophone", "neerlandophone",
    "flamand", "flemish",
]


def requires_dutch(job) -> bool:
    text = f"{job.get('job_title', '')} {job.get('job_description', '')}".lower()
    return any(kw in text for kw in DUTCH_KEYWORDS)


url = "https://jsearch.p.rapidapi.com/search-v2"
headers = {
    "x-rapidapi-key": os.getenv("RAPIDAPI_KEY"),
    "x-rapidapi-host": "jsearch.p.rapidapi.com",
}
params = {
    "query": "néerlandais",   # Dutch-speaking roles
    "country": "ma",          # Morocco
    "num_pages": "1",
    "date_posted": "all",
}

resp = requests.get(url, headers=headers, params=params)
print("Status:", resp.status_code)

data = resp.json()
jobs = data.get("data", {}).get("jobs", [])
print("Total jobs returned:", len(jobs))

dutch_jobs = [j for j in jobs if requires_dutch(j)]
print("Jobs that actually require Dutch:", len(dutch_jobs))

print("\n--- All returned titles (🇳🇱 = requires Dutch) ---")
for job in jobs[:15]:
    flag = "🇳🇱" if requires_dutch(job) else "  "
    print(f"{flag} {job.get('job_title')} | {job.get('employer_name')} | {job.get('job_city')}")