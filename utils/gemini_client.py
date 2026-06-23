"""utils/gemini_client.py — Thin wrapper around the Gemini 2.5 Flash API."""

import json
import re
import time
from typing import Any

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL
from utils.logger import get_logger

log = get_logger(__name__)

# Configure client once at import time
_client = genai.Client(api_key=GEMINI_API_KEY)


def ask(prompt: str, retries: int = 8, delay: float = 5.0) -> str:
    """
    Send a plain text prompt to Gemini and return the text response.
    Retries on transient errors with exponential back-off.
    Default: 8 attempts, starting at 5s delay (5, 10, 15, 20... ~3 min total wait).
    """
    for attempt in range(1, retries + 1):
        try:
            log.debug(f"Gemini request (attempt {attempt}): {prompt[:120]}...")
            response = _client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = response.text.strip()
            log.debug(f"Gemini response: {text[:200]}...")
            return text
        except Exception as exc:
            log.warning(f"Gemini error on attempt {attempt}: {exc}")
            if attempt < retries:
                wait = delay * attempt   # 15s, 30s, 45s, 60s, 75s, 90s, 105s
                log.warning(f"Retrying in {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise


def ask_json(prompt: str, retries: int = 3) -> Any:
    """
    Send a prompt that instructs Gemini to reply with JSON.
    Automatically strips markdown code fences and parses the result.
    Raises ValueError if the response cannot be parsed as JSON.
    """
    json_prompt = (
        prompt
        + "\n\nIMPORTANT: Reply ONLY with valid JSON — no markdown, no explanation, "
        "no code fences. Start your reply with { or [."
    )

    raw = ask(json_prompt, retries=retries)

    # Strip optional ```json ... ``` wrappers
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error(f"Failed to parse Gemini JSON. Raw response:\n{raw}")
        raise ValueError(f"Gemini returned invalid JSON: {exc}") from exc
