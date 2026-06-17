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

─── SCRIPT REQUIREMENTS ───────────────────────────────────────────────────
Narration length: exactly 130–160 words (≈45–55 seconds at natural speaking pace)

Structure:
  [HOOK]    First 2–3 sentences — shock/intrigue/question. No pleasantries.
  [CONTENT] Build the story with 2–4 surprising facts or escalating details.
  [TWIST]   One final surprising revelation or profound thought.
  [CTA]     1–2 sentences max: "Follow for more [niche topic]!" or similar.

Style rules:
  ✦ Every sentence must earn its place — no filler
  ✦ Short sentences (under 20 words) — easier to subtitle, punch harder
  ✦ Audio-only friendly — no "as you can see" or visual references
  ✦ Match the channel's specific voice/tone perfectly
  ✦ End with a strong hook that makes viewers want more

─── METADATA REQUIREMENTS ─────────────────────────────────────────────────
Title: max 70 chars, includes 1 emoji, ends with a teasing phrase
Description: 2–3 sentences that naturally include keywords (SEO)
Hashtags: 14 hashtags — must include #Shorts, #Viral, #{niche['display_name'].replace(' ','')}
Thumbnail text: 3–5 words, ALL CAPS, punchy (e.g. "THEY HID THIS FROM US")

─── REPLY FORMAT ──────────────────────────────────────────────────────────
Reply with ONLY this JSON object (no markdown, no explanation):
{{
  "title": "...",
  "description": "...",
  "hashtags": ["#Shorts", "#Viral", ...],
  "narration": "Full narration text here...",
  "thumbnail_text": "SHOCKING TRUTH REVEALED",
  "hook": "First 2 sentences of the narration.",
  "cta": "Follow {niche['display_name']} for more mind-blowing content!"
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
