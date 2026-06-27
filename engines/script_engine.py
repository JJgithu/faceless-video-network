"""
engines/script_engine.py
─────────────────────────────────────────────────────────────────────────────
The Scriptwriter Agent — uses Gemini 2.5 Flash to write a complete,
publish-ready 45-second vertical video script tailored to the active niche.

Hook rules (strictly enforced):
  ✅ Starts mid-sentence with the most shocking/horrifying claim
  ✅ No "Did you know", "Welcome", "Have you ever", "Today we"
  ✅ First sentence ≤ 12 words, already in the middle of the action
  ✅ AI voice starts speaking on frame 1 — no dead air

Output is structured for all downstream engines:
  - Narration (spoken by ElevenLabs)
  - SFX tags (sentence-level SFX assignments for the audio mixer)
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


class SfxTag(TypedDict):
    sentence_index: int   # 0-based index of the sentence in the narration
    sfx_type: str         # matches an _SFX_GENERATORS key in asset_engine


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
    sfx_tags: list[SfxTag]  # Sentence-level SFX assignments


# ── Banned hook openers ─────────────────────────────────────────────────────
BANNED_OPENERS = [
    "did you know",
    "welcome",
    "have you ever",
    "today we",
    "today, we",
    "in this video",
    "hey guys",
    "hello",
    "greetings",
    "let me tell",
    "let's talk",
    "let us talk",
    "i'm going to",
    "i want to",
    "we're going to",
    "imagine if",
    "have you heard",
]

# Approved SFX types the tagger can assign
VALID_SFX_TYPES = [
    "boom", "heartbeat", "creepy_crawl",
    "deep_rumble", "water_drop", "thunder", "reveal", "whoosh",
]


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


def _validate_and_fix_hook(narration: str) -> str:
    """
    Enforce the anti-"Did you know" hook rules.
    If the narration starts with a banned opener, strip the bad opener and
    restructure to start mid-sentence with the core claim.
    """
    if not narration:
        return narration

    first_line = narration.lstrip().split(".")[0].lower()

    for banned in BANNED_OPENERS:
        if first_line.startswith(banned):
            # Log the violation — script engine will re-ask Gemini if this happens
            log.warning(f"Hook violation detected: starts with banned opener '{banned}'")
            # Strip the bad sentence and use the second sentence as the hook
            sentences = [s.strip() for s in narration.split(".") if s.strip()]
            if len(sentences) > 1:
                # Reconstruct without the bad first sentence
                return ". ".join(sentences[1:]) + "."
            break

    return narration


def _tag_sfx_with_gemini(narration: str, niche: dict) -> list[SfxTag]:
    """
    Ask Gemini to tag each sentence with the most appropriate SFX type.
    This is a lightweight second Gemini call — fast and deterministic.

    Falls back to empty list if it fails (keyword matching in asset_engine handles it).
    """
    sentences = [s.strip() for s in narration.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    if not sentences:
        return []

    sfx_palette = niche.get("sfx_palette", VALID_SFX_TYPES)
    numbered = "\n".join(f"{i}: \"{s}\"" for i, s in enumerate(sentences))

    prompt = f"""You are a sound designer for viral short-form video content.

Given these narration sentences, assign the SINGLE most effective sound effect
for each sentence that has a clear sonic match. Not every sentence needs an SFX.

Available SFX types: {', '.join(sfx_palette)}

SFX meanings:
- boom: sudden impact, crash, massive force
- heartbeat: body, survival, pulse, living organisms
- creepy_crawl: spiders, insects, parasites, crawling things
- deep_rumble: ancient, buried, underground, ominous atmosphere
- water_drop: ocean, depth, underwater, pressure, sea creatures
- thunder: storms, war, disaster, catastrophic events
- reveal: shocking discovery, truth unveiled, classified info revealed
- whoosh: fast movement, speed, cutting through

Sentences:
{numbered}

Reply with ONLY a JSON array. Only include sentences that have a clear SFX match.
Each item must have "sentence_index" (int) and "sfx_type" (string from the list above).
Example: [{{"sentence_index": 0, "sfx_type": "boom"}}, {{"sentence_index": 3, "sfx_type": "reveal"}}]
If nothing matches well, reply with: []
"""

    try:
        result = ask_json(prompt)
        if not isinstance(result, list):
            return []
        # Validate each entry
        valid: list[SfxTag] = []
        for item in result:
            if (
                isinstance(item, dict)
                and isinstance(item.get("sentence_index"), int)
                and item.get("sfx_type") in VALID_SFX_TYPES
            ):
                valid.append(SfxTag(
                    sentence_index=item["sentence_index"],
                    sfx_type=item["sfx_type"],
                ))
        log.info(f"SFX tags from Gemini: {len(valid)} events")
        return valid
    except Exception as exc:
        log.warning(f"Gemini SFX tagging failed ({exc}) — using keyword fallback")
        return []


def generate_script(topic: Topic) -> Script:
    """
    Ask Gemini to write a complete, niche-specific video script.
    The script is engineered for maximum watch-time and virality.

    Enforces strict hook rules:
      - No "Did you know", no fade-in, no pleasantries
      - Must start mid-sentence with the most shocking claim
      - First sentence ≤ 12 words, already in the action
    """
    niche = config.get_niche()
    log.info(f"═══ Script Engine: [{niche['display_name']}] writing '{topic['topic']}' ═══")

    affiliate_instruction = ""
    if niche.get("affiliate_link"):
        affiliate_instruction = (
            f"\nAffiliate: include a natural reference near the end directing viewers to "
            f"the description for more information about this topic."
        )

    niche_hashtag = niche['display_name'].replace(' ', '')

    prompt = f"""You are a professional scriptwriter for the viral short-form channel
"{niche['display_name']}" {niche['emoji']}.

Channel voice / style:
{niche['style']}

TOPIC: {topic['topic']}
ANGLE: {topic['angle']}
OPENING HOOK: {topic['hook']}
{affiliate_instruction}

━━━ HOOK RULES — THESE ARE ABSOLUTE ━━━
❌ NEVER start with: "Did you know", "Welcome", "Have you ever",
   "Today we", "Let me tell you", "Imagine if", "Hey guys", or any pleasantry.
   These are INSTANT SWIPE triggers. Starting with them = video fails.

✅ INSTEAD: Start with the most terrifying/shocking/impossible claim.
   The narration must begin MID-SENTENCE, as if the viewer is already deep
   inside the story. The AI voice starts speaking on FRAME 1 — no dead air.

BAD hook:  "Did you know that the deep sea holds many mysteries?"
GREAT hook: "If you swim past 1,000 feet, your lungs will literally crush themselves."

BAD hook:  "Welcome back! Today we're talking about ancient Egypt."
GREAT hook: "In 1908, the Egyptian government erased this city from every map."

The first sentence must be ≤ 12 words and be the single most shocking claim
in the entire video. The viewer must be unable to scroll after word 3.

━━━ SCRIPT REQUIREMENTS ━━━
Narration length: 75-95 words MAX (spoken in ~30-38 seconds at natural pace)
Every single word must earn its place. Cut all filler.

Structure:
  [HOOK]    1 sentence — the craziest claim, mid-sentence, no buildup.
  [CONTENT] 3-4 punchy sentences. Stack shocking facts. Short sentences only.
  [TWIST]   One final revelation that reframes everything.
  [CTA]     Exactly: "Hit like and subscribe for more!"

Style rules:
  - Sentences under 10 words each — short, punchy, unstoppable rhythm
  - Audio-only friendly — no visual references ("as you can see", "look at this")
  - Sound like the narration is urgent classified information
  - STRICT word limit: 75-95 words, count carefully
  - The final CTA must ALWAYS be exactly: "Hit like and subscribe for more!"

━━━ METADATA REQUIREMENTS ━━━
Title: max 60 chars, 1 emoji, punchy hook that mirrors the narration opener
Description: 2 sentences, SEO keywords
Hashtags: 14, must include #Shorts, #Viral, #{niche_hashtag}
Thumbnail text: 2-3 words MAX, ALL CAPS, the most shocking claim (e.g. "LUNGS COLLAPSE")

━━━ REPLY FORMAT ━━━
Reply with ONLY this JSON (no markdown, no explanation):
{{
  "title": "...",
  "description": "...",
  "hashtags": ["#Shorts", "#Viral", ...],
  "narration": "Full narration text here...",
  "thumbnail_text": "THEY HID THIS",
  "hook": "First sentence of narration.",
  "cta": "Hit like and subscribe for more!"
}}
"""

    max_attempts = 3
    script: Script = {}

    for attempt in range(1, max_attempts + 1):
        script = ask_json(prompt)

        # Validate hook — no banned openers
        narration = script.get("narration", "")
        fixed_narration = _validate_and_fix_hook(narration)

        if fixed_narration != narration and attempt < max_attempts:
            log.warning(f"Hook violation on attempt {attempt} — re-requesting from Gemini")
            # Add a stronger instruction to the prompt
            prompt += (
                f"\n\n⚠️ IMPORTANT: Your previous narration started with a banned opener. "
                f"Start with the SHOCKING CLAIM directly. No pleasantries. "
                f"The first word must be part of the horrifying fact itself."
            )
            continue

        script["narration"] = fixed_narration
        break

    # Always enforce the CTA
    script["cta"] = "Hit like and subscribe for more!"

    # ── Enforce invariants ──────────────────────────────────────────────────────
    if "#Shorts" not in script.get("hashtags", []):
        if "hashtags" not in script:
            script["hashtags"] = []
        script["hashtags"].insert(0, "#Shorts")
    if len(script.get("title", "")) > 100:
        script["title"] = script["title"][:97] + "…"

    # ── SFX Tagging pass ────────────────────────────────────────────────────────
    log.info("Running Gemini SFX tagging pass…")
    sfx_tags = _tag_sfx_with_gemini(script.get("narration", ""), niche)
    script["sfx_tags"] = sfx_tags

    # ── Affiliate link (Audible auto-pick → fallback to manual link) ────────────
    affiliate_line = ""
    book_title = ""

    # 1) Try automated Audible book selection
    book = _pick_affiliate_book(topic, niche.get("key", config.ACTIVE_NICHE))
    if book:
        book_title = book["title"]
        affiliate_line = (
            f"\n\n📚 Get the book on Amazon: \"{book['title']}\" by {book['author']}\n"
            f"{book['audible_url']}"
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
        f"sfx_tags={len(sfx_tags)} | "
        f"title: {script.get('title', '')[:50]}…"
    )
    return script
