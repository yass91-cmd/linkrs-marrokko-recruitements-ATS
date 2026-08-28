import re

MOROCCAN_CITIES = {
    "casablanca": "Casablanca", "الدار البيضاء": "Casablanca", "casa": "Casablanca",
    "rabat": "Rabat", "الرباط": "Rabat",
    "marrakech": "Marrakech", "مراكش": "Marrakech",
    "tanger": "Tanger", "طنجة": "Tanger", "tangier": "Tanger",
    "fes": "Fès", "fès": "Fès", "فاس": "Fès",
    "agadir": "Agadir", "أكادير": "Agadir",
    "kenitra": "Kénitra", "kénitra": "Kénitra", "القنيطرة": "Kénitra",
    "oujda": "Oujda", "tetouan": "Tétouan", "meknes": "Meknès",
}


def clean_text(text: str | None) -> str | None:
    """Normalize line endings and collapse blank lines."""
    if not text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def detect_city(job: dict) -> str | None:
    """Find the city from the API field, the location string, or the title."""
    if job.get("job_city"):
        return job["job_city"]
    haystack = f"{job.get('job_location', '')} {job.get('job_title', '')}".lower()
    for key, city in MOROCCAN_CITIES.items():
        if key in haystack:
            return city
    return None


def clean_employer(name: str | None) -> str | None:
    """The API uses 'Unspecified' as a placeholder — store NULL instead."""
    if not name or name.strip().lower() in {"unspecified", "n/a", "unknown"}:
        return None
    return name.strip()