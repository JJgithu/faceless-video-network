"""
scripts/make_trailer.py
─────────────────────────────────────────────────────────────────────────────
Generates a "What this channel is about" trailer for the SooooCool channel.

This is a one-time run script — trigger it from GitHub Actions (make_trailer.yml)
or locally if you have API keys set up in a .env file.

Output: trailer.mp4 (saved as GitHub Actions artifact)
"""

import os
import sys
import shutil
from pathlib import Path

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from utils.logger import get_logger
from engines.voice_engine import synthesise_voice
from engines.asset_engine import gather_assets
from engines.video_engine import assemble_video

log = get_logger("trailer")

# ── Hardcoded trailer script ────────────────────────────────────────────────

TRAILER_SCRIPT = {
    "title": "Welcome to SooooCool 🔥",
    "description": (
        "Every day we post mind-blowing Shorts on historical mysteries, "
        "stoic wisdom, ocean secrets, and brain-bending puzzles. Subscribe!"
    ),
    "hashtags": ["#Shorts", "#SooooCool", "#History", "#Philosophy", "#Ocean"],
    "narration": (
        "What if every day started with something that actually blows your mind? "
        "We uncover historical mysteries buried for centuries. "
        "We share stoic wisdom that makes modern life make sense. "
        "We reveal what lurks in the deepest parts of the ocean. "
        "And we challenge your brain with riddles that prove you're smarter than you think. "
        "That's SooooCool. "
        "New videos every single day. "
        "Hit like and subscribe — you won't run out of cool things to talk about."
    ),
    "thumbnail_text": "SOOO COOL",
    "hook": "What if every day started with something that actually blows your mind?",
    "cta": "Hit like and subscribe for more!",
    "affiliate_line": "",
    "affiliate_book": "",
}

# ── Trailer-specific asset config ────────────────────────────────────────────

TRAILER_PEXELS_KEYWORDS = [
    "ancient ruins mystery",
    "deep ocean bioluminescent",
    "meditation sunrise mountain",
    "brain puzzle geometry",
    "history documentary dramatic",
    "underwater creatures dark",
]

TRAILER_NICHE_CONFIG = {
    "key": "trailer",
    "display_name": "SooooCool",
    "emoji": "🔥",
    "style": "epic cinematic narrator",
    "pexels_keywords": TRAILER_PEXELS_KEYWORDS,
    "reddit_subs": [],
    "wikipedia_unusual": False,
    "elevenlabs_voice_id": os.environ.get("EL_VOICE_HISTORY", "pNInz6obpgDQGcFmaJgB"),
    "youtube_channel_id": "",
    "tiktok_access_token": "",
    "affiliate_link": "",
    "affiliate_cta": "",
}


def main():
    log.info("═══ Trailer Generator: SooooCool Channel Intro ═══")

    # Override the active niche config for this run
    config.NICHES["trailer"] = TRAILER_NICHE_CONFIG
    os.environ["NICHE"] = "trailer"

    # Create output directory
    run_dir = config.OUTPUT_DIR / "trailer_run"
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Gather assets (b-roll clips + music) ──────────────────────
    log.info("Step 1 — Gathering b-roll clips from Pexels…")
    assets = gather_assets(TRAILER_SCRIPT, run_dir)
    log.info(f"  {len(assets['video_clips'])} clips downloaded")

    # ── Step 2: Synthesise narration voice ────────────────────────────────
    log.info("Step 2 — Synthesising narration with ElevenLabs…")
    voice = synthesise_voice(TRAILER_SCRIPT, run_dir)
    log.info(f"  Voice: {voice['duration']:.1f}s via {voice['engine']}")

    # ── Step 3: Assemble video ────────────────────────────────────────────
    log.info("Step 3 — Assembling trailer video…")
    result = assemble_video(TRAILER_SCRIPT, assets, voice, run_dir)
    log.info(f"  ✅ Trailer assembled: {result['duration']:.1f}s")

    # ── Step 4: Copy to output root ───────────────────────────────────────
    trailer_out = config.OUTPUT_DIR / "trailer.mp4"
    shutil.copy(result["video_file"], trailer_out)
    log.info(f"  Saved → {trailer_out}")

    print(f"\n✅ TRAILER DONE: {trailer_out}")
    return str(trailer_out)


if __name__ == "__main__":
    main()
