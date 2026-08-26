import re

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+212|0)[\s.\-]?[\d\s.\-]{8,}\d")


def find_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def find_phone(text: str) -> str | None:
    m = PHONE_RE.search(text)
    return re.sub(r"[\s.\-]", "", m.group(0)) if m else None