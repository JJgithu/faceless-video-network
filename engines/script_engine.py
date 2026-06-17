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

from typing import TypedDict

import config
from engines.trend_engine import Topic
from utils.gemini_client import ask_json
from utils.logger import get_logger

log = get_logger(__name__)


class Script(TypedDict):
    title: str           # Platform title ≤ 100 chars, includes emoji
    description: str     # Full SEO description with affiliate link
    hashtags: list[str]  # 12-15 hashtags, always includes #Shorts
    narration: str       # Full spoken script (≈130-160 words)
    thumbnail_text: str  # 3-5 word bold overlay text, ALL CAPS
    hook: str            # First 1-2 sentences of narration
    cta: str             # Final CTA sentence
    affiliate_line: str  # Formatted affiliate line for description


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
  [CTA]     1 sentence: “Follow for more!”

Style rules:
  ✦ Sentences under 12 words each
  ✦ Audio-only friendly — no visual references
  ✦ Match the channel's specific voice/tone
  ✦ STRICT word limit: 75–95 words, count carefully

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

    # ── Enforce invariants ─────────────────────────────────────────────────
    # Always include #Shorts for YouTube Shorts distribution
    if "#Shorts" not in script["hashtags"]:
        script["hashtags"].insert(0, "#Shorts")

    # Enforce title length
    if len(script.get("title", "")) > 100:
        script["title"] = script["title"][:97] + "…"

    # Build the affiliate line for the description
    affiliate_link = niche.get("affiliate_link", "")
    affiliate_cta = niche.get("affiliate_cta", "")
    if affiliate_link:
        script["affiliate_line"] = f"\n\n{affiliate_cta} {affiliate_link}"
        script["description"] = script["description"] + script["affiliate_line"]
    else:
        script["affiliate_line"] = ""

    word_count = len(script.get("narration", "").split())
    log.info(
        f"Script ready | {word_count} words | "
        f"title: {script.get('title', '')[:50]}…"
    )

    return script
