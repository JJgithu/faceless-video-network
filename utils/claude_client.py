"""
utils/claude_client.py — Anthropic Claude 3.5 Sonnet API client.

Provides strict JSON output via Anthropic's Structured Outputs feature.
Falls back to manual JSON parsing with code-fence stripping if needed.

Mirrors the retry/backoff architecture of gemini_client.py.
"""

import json
import re
import time
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from utils.logger import get_logger

log = get_logger(__name__)

# Initialise client once at import time
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ask_claude(
    prompt: str,
    system: str = "",
    retries: int = 30,
    delay: float = 5.0,
    max_tokens: int = 4096,
) -> str:
    """
    Send a plain text prompt to Claude and return the text response.
    Retries on transient errors with linear back-off.
    """
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, retries + 1):
        try:
            log.debug(f"Claude request (attempt {attempt}): {prompt[:120]}…")
            kwargs = {
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system

            response = _client.messages.create(**kwargs)

            # Extract text from the response content blocks
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            text = text.strip()
            log.debug(f"Claude response: {text[:200]}…")
            return text

        except anthropic.RateLimitError as exc:
            log.warning(f"Claude rate limit on attempt {attempt}: {exc}")
            if attempt < retries:
                wait = delay * attempt
                log.warning(f"Retrying in {wait:.0f}s…")
                time.sleep(wait)
            else:
                raise

        except anthropic.APIError as exc:
            log.warning(f"Claude API error on attempt {attempt}: {exc}")
            if attempt < retries:
                wait = delay * attempt
                log.warning(f"Retrying in {wait:.0f}s…")
                time.sleep(wait)
            else:
                raise

        except Exception as exc:
            log.warning(f"Claude error on attempt {attempt}: {exc}")
            if attempt < retries:
                wait = delay * attempt
                log.warning(f"Retrying in {wait:.0f}s…")
                time.sleep(wait)
            else:
                raise


def ask_claude_json(
    prompt: str,
    system: str = "",
    json_schema: dict | None = None,
    max_tokens: int = 4096,
) -> Any:
    """
    Send a prompt to Claude that must return strict JSON.

    Two strategies for JSON enforcement:
      1. If json_schema is provided, attempt Anthropic Structured Outputs
         (constrained decoding — guaranteed schema compliance)
      2. Fallback: instruct Claude in the system prompt to reply with raw JSON,
         then strip code fences and parse manually.

    Returns the parsed JSON (dict or list).
    Raises ValueError if JSON parsing fails after retries.
    """
    # ── Strategy 1: Structured Outputs (if schema provided) ────────────────
    if json_schema:
        try:
            return _ask_with_structured_output(prompt, system, json_schema, max_tokens)
        except Exception as exc:
            log.warning(
                f"Structured Outputs failed ({exc}), falling back to manual JSON parsing"
            )

    # ── Strategy 2: Manual JSON parsing ────────────────────────────────────
    json_system = system
    if json_system:
        json_system += "\n\n"
    json_system += (
        "CRITICAL: You must output ONLY a raw JSON object. "
        "No markdown formatting, no code fences, no explanation. "
        "Start your reply with { or [."
    )

    raw = ask_claude(prompt, system=json_system, max_tokens=max_tokens)

    # Strip optional ```json ... ``` wrappers
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # Strip any leading text before the first { or [
    json_start = -1
    for i, char in enumerate(cleaned):
        if char in ('{', '['):
            json_start = i
            break
    if json_start > 0:
        cleaned = cleaned[json_start:]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error(f"Failed to parse Claude JSON. Raw response:\n{raw}")
        raise ValueError(f"Claude returned invalid JSON: {exc}") from exc


def _ask_with_structured_output(
    prompt: str,
    system: str,
    json_schema: dict,
    max_tokens: int,
) -> Any:
    """
    Use Anthropic's Structured Outputs feature for guaranteed JSON compliance.
    Wraps the schema in the output_config parameter.
    """
    messages = [{"role": "user", "content": prompt}]

    kwargs = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    # Attempt structured output via tool_use trick:
    # Define a tool whose input_schema matches the desired JSON output,
    # then force Claude to use it with tool_choice.
    tool_name = "generate_video_script"
    kwargs["tools"] = [
        {
            "name": tool_name,
            "description": "Output the structured video script data",
            "input_schema": json_schema,
        }
    ]
    kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

    response = _client.messages.create(**kwargs)

    # Extract the tool input (which is our structured JSON)
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input

    raise ValueError("Claude did not return structured tool output")
