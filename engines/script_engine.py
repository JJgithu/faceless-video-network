"""
engines/script_engine.py
─────────────────────────────────────────────────────────────────────────────
The Scriptwriter Agent — uses Gemini 2.5 Flash to write a complete,
publish-ready 50-second vertical video script tailored to the active niche.

Output is structured for all downstream engines:
  - Narration (spoken by ElevenLabs)
  - Title, description, hashtags (for YouTube & TikTok)
  - Thumbnail text, hook sentence, CTA
  - Affiliate link placement
"""

import json
from pathlib import Path
from typing import TypedDict

import config
from engines.trend_engine import Topic
from utils.gemini_client import ask, ask_json
from utils.logger import get_logger

log = get_logger(__name__)

# Curated audiobook library (data/affiliate_books.json)
_BOOKS_FILE = Path(__file__).parent.parent / "data" / "affiliate_books.json"


class Script(TypedDict):
    title: str            # Platform title ≤ 100 chars, includes emoji
    description: str      # Full SEO description with affiliate link
    hashtags: list[str]   # 12-15 hashtags, always includes #Shorts
    narration: str        # Full spoken script (≈75-95 words)
    thumbnail_text: str   # 2-3 word bold overlay text, ALL CAPS
    hook: str             # First sentence of narration
    cta: str              # Final CTA sentence
    affiliate_line: str   # Formatted affiliate line for description
    affiliate_book: str   # Book title selected for this video


def _pick_affiliate_book(topic: Topic, niche_key: str) -> dict | None:
    """
    Use the curated book library to find the best audiobook for this video.
    Gemini picks the most thematically relevant book from the niche's list.
    Injects the user's AUDIBLE_AFFILIATE_TAG into the URL automatically.
    Returns None if no books configured or no affiliate tag set.
    """
    affiliate_tag = (
        config.AUDIBLE_AFFILIATE_TAG
        or config.AMAZON_AFFILIATE_TAG
    )
    if not affiliate_tag:
        return None   # user hasn't set up affiliate tag yet

    try:
        books_data = json.loads(_BOOKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    niche_books: list[dict] = books_data.get(niche_key, [])
    if not niche_books:
        return None

    # Build a compact menu for Gemini
    menu = "\n".join(
        f"{i}. \"{b['title']}\" by {b['author']}  —  keywords: {', '.join(b['keywords'][:5])}"
        for i, b in enumerate(niche_books)
    )

    prompt = (
        f"Given this video topic: \"{topic['topic']}\" (\"{topic['angle']}\")"
        f"\n\nChoose the SINGLE most relevant audiobook for viewers who just watched this video."
        f"\n\nOptions:\n{menu}"
        f"\n\nReply with ONLY the number (0, 1, 2, ...). Nothing else."
    )

    try:
        choice_raw = ask(prompt).strip()
        idx = int(''.join(c for c in choice_raw if c.isdigit()) or "0")
        idx = max(0, min(idx, len(niche_books) - 1))
        book = niche_books[idx]
        # Inject the user's affiliate tag
        book = dict(book)
        book["audible_url"] = book["audible_url"].replace("YOURTAG", affiliate_tag)
        return book
    except Exception as exc:
        log.warning(f"Affiliate book picker failed: {exc}")
        return None


def generate_script(topic: Topic) -> Script:
    """
    Ask Gemini to write a complete, niche-specific video script.
    The script is engineered for maximum watch-time and virality.
    """
    niche = config.get_niche()
    log.info(f"═══ Script Engine: [{niche['display_name']}] writing '{topic['topic']}' ═══")

    affiliate_instruction = ""
    if niche.get("affiliate_link"):
        affiliate_instruction = (
            f"\nAffiliate: include a natural reference near the end directing viewers to "
            f"the description for more information about this topic."
        )

    prompt = f"""
You are a professional scriptwriter for the viral short-video channel
"{niche['display_name']}" {niche['emoji']}.

Channel voice / style:
{niche['style']}

TOPIC: {topic['topic']}
ANGLE: {topic['angle']}
OPENING HOOK: {topic['hook']}
{affiliate_instruction}

─── SCRIPT REQUIREMENTS ──────────────────────────────────────────────
Narration length: 75–95 words MAX (spoken in ≈30–38 seconds)
This is a SHORT-FORM video — every single word must earn its place.

Structure (tight, punchy):
  [HOOK]    1–2 sentences — shock or question. No pleasantries.
  [CONTENT] 2–3 surprising facts. Short sentences only.
  [TWIST]   One final revelation.
  [CTA]     1 sentence: "Hit like and subscribe for more!"

Style rules:
  ✦ Sentences under 12 words each
  ✦ Audio-only friendly — no visual references
  ✦ Match the channel's specific voice/tone
  ✦ STRICT word limit: 75–95 words, count carefully
  ✦ The final CTA must ALWAYS be exactly: "Hit like and subscribe for more!"

─── METADATA REQUIREMENTS ──────────────────────────────────────────────
Title: max 60 chars, 1 emoji, punchy hook
Description: 2 sentences, SEO keywords
Hashtags: 14, must include #Shorts, #Viral, #{niche['display_name'].replace(' ','')}
Thumbnail text: 2–3 words MAX, ALL CAPS (e.g. “THEY HID THIS”)

─── REPLY FORMAT ──────────────────────────────────────────────────────
Reply with ONLY this JSON (no markdown, no explanation):
{{
  "title": "...",
  "description": "...",
  "hashtags": ["#Shorts", "#Viral", ...],
  "narration": "Full narration text here...",
  "thumbnail_text": "THEY HID THIS",
  "hook": "First sentence of narration.",
  "cta": "Follow {niche['display_name']} for more!"
}}
"""

    script: Script = ask_json(prompt)

    # Always enforce the CTA — never let Gemini use a channel-specific phrase
    script["cta"] = "Hit like and subscribe for more!"

    # ── Enforce invariants ──────────────────────────────────────────────────────
    if "#Shorts" not in script["hashtags"]:
        script["hashtags"].insert(0, "#Shorts")
    if len(script.get("title", "")) > 100:
        script["title"] = script["title"][:97] + "…"

    # ── Affiliate link (Audible auto-pick → fallback to manual link) ────────────
    affiliate_line = ""
    book_title = ""

    # 1) Try automated Audible book selection
    book = _pick_affiliate_book(topic, niche.get("key", config.ACTIVE_NICHE))
    if book:
        book_title = book["title"]
        affiliate_line = (
            f"\n\n📚 Get the book on Amazon: \"{book['title']}\" by {book['author']}"
            f"\n➡️ {book['audible_url']}"
        )
        log.info(f"Affiliate book selected: {book_title}")

    # 2) Fall back to manual affiliate link from GitHub Secrets
    elif niche.get("affiliate_link"):
        affiliate_cta = niche.get("affiliate_cta", "📚 Learn more:")
        affiliate_line = f"\n\n{affiliate_cta} {niche['affiliate_link']}"

    script["affiliate_line"] = affiliate_line
    script["affiliate_book"] = book_title
    script["description"] = script.get("description", "") + affiliate_line

    word_count = len(script.get("narration", "").split())
    log.info(
        f"Script ready | {word_count} words | "
        f"title: {script.get('title', '')[:50]}…"
    )
    return script
