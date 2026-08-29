import re
import json
import time
import logging
from extract.llm_client import client, MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are a strict JSON API. Output ONLY one valid JSON object, nothing else."


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {raw[:200]!r}")
    return json.loads(match.group(0))


def get_structured(prompt: str, retries: int = 4) -> dict:
    """Call the LLM and return parsed JSON. Retries on empty or unparseable output."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    last_error = None
    for attempt in range(1, retries + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0 if attempt == 1 else 0.3,
        )
        content = response.choices[0].message.content or ""
        if content.strip():
            try:
                return _extract_json(content)
            except (ValueError, json.JSONDecodeError):
                last_error = content.strip()[:120]
                logger.warning("Non-JSON response (attempt %d/%d): %r", attempt, retries, last_error)
        else:
            logger.warning("Empty response (attempt %d/%d)", attempt, retries)
        time.sleep(2)
    raise ValueError(f"Failed to get JSON after {retries} attempts. Last: {last_error!r}")