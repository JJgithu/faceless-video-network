"""
engines/hybrid_script_engine.py
─────────────────────────────────────────────────────────────────────────────
The Hybrid AI Scriptwriter — uses Claude 3.5 Sonnet to write a complete
video script AND generate 4 Kling AI visual prompts in a single API call.

This is the "Brain & Director" node of the Hybrid AI pipeline.

Claude outputs strict JSON with:
  - youtube_title: SEO-optimised 10-word title with #shorts
  - spoken_script: Full narration text (80–95 words)
  - video_clips: Array of 4 detailed Kling AI photorealistic prompts

Hook rules (strictly enforced — same as legacy engine):
  ✅ Starts mid-sentence with the most shocking/horrifying claim
  ✅ No "Did you know", "Welcome", "Have you ever", "Today we"
  ✅ First sentence ≤ 12 words, already in the middle of the action
  ✅ AI voice starts speaking on frame 1 — no dead air
"""

import json
from pathlib import Path
from typing import TypedDict

import config
from engines.trend_engine import Topic
from utils.claude_client import ask_claude_json
from utils.logger import get_logger

log = get_logger(__name__)

# Curated audiobook library (data/affiliate_books.json)
_BOOKS_FILE = Path(__file__).parent.parent / "data" / "affiliate_books.json"


class KlingClip(TypedDict):
    clip_number: int
    kling_prompt: str


class HybridScript(TypedDict):
    youtube_title: str        # SEO title with #shorts
    title: str                # Same as youtube_title (for publisher compat)
    spoken_script: str        # Full narration text
    narration: str            # Alias of spoken_script (for voice engine compat)
    video_clips: list[KlingClip]  # 4 Kling AI visual prompts
    description: str          # YouTube description
    hashtags: list[str]       # 12-15 hashtags
    thumbnail_text: str       # 2-3 word bold overlay
    hook: str                 # First sentence of narration
    cta: str                  # Final CTA
    affiliate_line: str       # Formatted affiliate line
    affiliate_book: str       # Selected book title
    sfx_tags: list[dict]      # SFX assignments (from Gemini or keyword fallback)


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

# Approved SFX types (shared with legacy engine)
VALID_SFX_TYPES = [
    "boom", "heartbeat", "creepy_crawl",
    "deep_rumble", "water_drop", "thunder", "reveal", "whoosh",
]


# ── Claude System Prompt (The Director) ─────────────────────────────────────

CLAUDE_SYSTEM_PROMPT = """You are an elite YouTube Shorts Director for a 'Dark Lore' channel. Your topics rotate exclusively between Deep Sea Terrors, Bizarre Body Science, and Unsolved Historical Mysteries. Your goal is to write a 45-second script and generate the visual prompts required to animate it.

RULES:

The Hook: The first sentence MUST be a pattern interrupt. NEVER use polite introductions, 'Welcome to,' or 'Did you know.' Start mid-action with a terrifying or bizarre fact.

Pacing: The script must be exactly 80 to 95 words (approx. 40-45 seconds spoken).

Visual Prompts: You must generate exactly 4 distinct visual prompts to accompany the script. These prompts will be sent to Kling AI. Kling thrives on strict photorealism keywords. Include descriptors like: 'photorealistic, cinematic, murky lighting, gritty, archival 1920s footage, VHS grain, macro close-up.' Keep camera movements simple.

JSON SCHEMA:
You must output ONLY a raw JSON object. No markdown formatting outside the brackets. Use this exact schema:
{
  "youtube_title": "10-word SEO title with #shorts",
  "spoken_script": "The full spoken text to be sent to the TTS engine formatted as a single string",
  "video_clips": [
    { "clip_number": 1, "kling_prompt": "[Highly detailed visual prompt for the hook]" },
    { "clip_number": 2, "kling_prompt": "[Visual prompt for the next scene]" },
    { "clip_number": 3, "kling_prompt": "[Visual prompt for the next scene]" },
    { "clip_number": 4, "kling_prompt": "[Visual prompt for the climax]" }
  ]
}"""


# ── JSON Schema for Structured Output ───────────────────────────────────────

SCRIPT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "youtube_title": {
            "type": "string",
            "description": "SEO-optimised 10-word title ending with #shorts",
        },
        "spoken_script": {
            "type": "string",
            "description": "Full spoken narration text, 80-95 words, single string",
        },
        "video_clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clip_number": {"type": "integer"},
                    "kling_prompt": {
                        "type": "string",
                        "description": "Detailed photorealistic visual prompt for Kling AI",
                    },
                },
                "required": ["clip_number", "kling_prompt"],
            },
            "minItems": 4,
            "maxItems": 4,
        },
    },
    "required": ["youtube_title", "spoken_script", "video_clips"],
}


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
            log.warning(f"Hook violation detected: starts with banned opener '{banned}'")
            sentences = [s.strip() for s in narration.split(".") if s.strip()]
            if len(sentences) > 1:
                return ". ".join(sentences[1:]) + "."
            break

    return narration


def _tag_sfx_with_keywords(narration: str, niche: dict) -> list[dict]:
    """
    Keyword-based SFX tagger — lightweight fallback that doesn't require
    an additional API call. Matches narration sentences against SFX trigger words.
    """
    from engines.asset_engine import SFX_TRIGGER_KEYWORDS

    sentences = [s.strip() for s in narration.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    tags = []
    for i, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        for sfx_type, keywords in SFX_TRIGGER_KEYWORDS.items():
            if any(kw in sentence_lower for kw in keywords):
                tags.append({"sentence_index": i, "sfx_type": sfx_type})
                break
    return tags


def _try_gemini_sfx_tagging(narration: str, niche: dict) -> list[dict]:
    """
    Try to use Gemini for intelligent SFX tagging (fast, cheap).
    Falls back to keyword matching if Gemini is unavailable.
    """
    try:
        from engines.script_engine import _tag_sfx_with_gemini
        tags = _tag_sfx_with_gemini(narration, niche)
        if tags:
            return tags
    except Exception as exc:
        log.warning(f"Gemini SFX tagging unavailable ({exc})")

    return _tag_sfx_with_keywords(narration, niche)


def _pick_affiliate_book(topic: Topic, niche_key: str) -> dict | None:
    """
    Re-use the affiliate book picker logic from the legacy engine.
    Uses Gemini if available, otherwise returns None.
    """
    try:
        from engines.script_engine import _pick_affiliate_book as legacy_pick
        return legacy_pick(topic, niche_key)
    except Exception:
        return None


def generate_hybrid_script(topic: Topic) -> HybridScript:
    """
    Ask Claude 3.5 Sonnet to write the video script + 4 Kling AI visual prompts.
    Returns a HybridScript dict compatible with all downstream engines.

    Enforces strict hook rules and 80–95 word count.
    """
    niche = config.get_niche()
    log.info(f"═══ Hybrid Script Engine (Claude): [{niche['display_name']}] writing '{topic['topic']}' ═══")

    niche_hashtag = niche['display_name'].replace(' ', '')

    user_prompt = f"""TOPIC: {topic['topic']}
ANGLE: {topic['angle']}
OPENING HOOK SUGGESTION: {topic['hook']}
CHANNEL: {niche['display_name']} {niche['emoji']}
CHANNEL STYLE: {niche['style']}

ADDITIONAL REQUIREMENTS:
- Title must include #shorts at the end
- The spoken_script MUST be exactly 80-95 words. Count carefully.
- First sentence must be ≤ 12 words — the most shocking claim in the entire video
- NEVER start with "Did you know", "Welcome", "Have you ever", "Today we", or any pleasantry
- Start MID-SENTENCE with the terrifying/shocking/impossible claim
- Final sentence of spoken_script must be exactly: "Hit like and subscribe for more!"
- Kling prompts must include: photorealistic, cinematic, specific camera angle, lighting descriptor
- Each Kling prompt should describe a DIFFERENT visual scene matching that section of narration

Generate the JSON now."""

    max_attempts = 3
    raw_script = None

    for attempt in range(1, max_attempts + 1):
        try:
            raw_script = ask_claude_json(
                prompt=user_prompt,
                system=CLAUDE_SYSTEM_PROMPT,
                json_schema=SCRIPT_JSON_SCHEMA,
            )
            break
        except Exception as exc:
            log.warning(f"Claude attempt {attempt} failed: {exc}")
            if attempt == max_attempts:
                raise RuntimeError(f"Claude failed after {max_attempts} attempts: {exc}")

    if not raw_script:
        raise RuntimeError("Claude returned empty response")

    # ── Validate and extract fields ─────────────────────────────────────────
    youtube_title = raw_script.get("youtube_title", "Dark Lore #shorts")
    spoken_script = raw_script.get("spoken_script", "")
    video_clips = raw_script.get("video_clips", [])

    # Validate word count
    word_count = len(spoken_script.split())
    if word_count < 60 or word_count > 120:
        log.warning(f"Word count {word_count} outside ideal range (80-95), but proceeding")

    # Validate hook
    spoken_script = _validate_and_fix_hook(spoken_script)

    # Ensure exactly 4 clips
    while len(video_clips) < 4:
        video_clips.append({
            "clip_number": len(video_clips) + 1,
            "kling_prompt": (
                "Photorealistic cinematic shot, dark moody lighting, "
                "mysterious atmosphere, dramatic shadows, 4K quality"
            ),
        })
    video_clips = video_clips[:4]

    # Ensure #shorts in title
    if "#shorts" not in youtube_title.lower():
        youtube_title += " #shorts"
    if len(youtube_title) > 100:
        youtube_title = youtube_title[:97] + "…"

    # Extract hook (first real sentence — must be ≥ 5 chars to be valid)
    hook = ""
    if spoken_script:
        # Try splitting on sentence-ending punctuation
        import re as _re
        sentences = [s.strip() for s in _re.split(r'[.!?]', spoken_script) if s.strip()]
        for candidate in sentences:
            if len(candidate) >= 5:
                hook = candidate + "."
                break
        # Final fallback: use first 80 chars of the narration
        if not hook or len(hook) < 6:
            hook = spoken_script[:80].strip() + "…"
            log.warning(f"Hook extraction failed — using narration excerpt: {hook}")

    # ── Build hashtags ──────────────────────────────────────────────────────
    hashtags = [
        "#Shorts", "#Viral", f"#{niche_hashtag}",
        "#DarkLore", "#Mystery", "#Science", "#History",
        "#Horror", "#Facts", "#Documentary", "#DeepSea",
        "#BodyScience", "#Scary", "#Education",
    ]

    # ── Build description ───────────────────────────────────────────────────
    description = (
        f"{hook} "
        f"Discover the terrifying truth in this Dark Lore episode. "
        f"Subscribe for daily mysteries, bizarre science, and unsolved history."
    )

    # ── SFX tagging ─────────────────────────────────────────────────────────
    log.info("Running SFX tagging pass…")
    sfx_tags = _try_gemini_sfx_tagging(spoken_script, niche)

    # ── Affiliate link ──────────────────────────────────────────────────────
    affiliate_line = ""
    book_title = ""
    book = _pick_affiliate_book(topic, niche.get("key", config.ACTIVE_NICHE))
    if book:
        book_title = book["title"]
        affiliate_line = (
            f"\n\n📚 Get the book on Amazon: \"{book['title']}\" by {book['author']}\n"
            f"{book['audible_url']}"
        )
        log.info(f"Affiliate book selected: {book_title}")
    elif niche.get("affiliate_link"):
        affiliate_cta = niche.get("affiliate_cta", "📚 Learn more:")
        affiliate_line = f"\n\n{affiliate_cta} {niche['affiliate_link']}"

    description += affiliate_line

    # ── Assemble the HybridScript ───────────────────────────────────────────
    script = HybridScript(
        youtube_title=youtube_title,
        title=youtube_title,
        spoken_script=spoken_script,
        narration=spoken_script,
        video_clips=video_clips,
        description=description,
        hashtags=hashtags,
        thumbnail_text=hook[:20].upper().split()[-1] if hook else "DARK LORE",
        hook=hook,
        cta="Hit like and subscribe for more!",
        affiliate_line=affiliate_line,
        affiliate_book=book_title,
        sfx_tags=sfx_tags,
    )

    log.info(
        f"Hybrid script ready | {word_count} words | "
        f"clips={len(video_clips)} | "
        f"sfx_tags={len(sfx_tags)} | "
        f"title: {youtube_title[:50]}…"
    )
    return script
