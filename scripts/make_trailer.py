"""
scripts/make_trailer.py
─────────────────────────────────────────────────────────────────────────────
Generates a "What this channel is about" trailer for the SooooCool channel.
Trigger via GitHub Actions → make_trailer.yml → Run workflow.
Output: trailer.mp4 uploaded as a GitHub Actions artifact.
"""

import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from utils.logger import get_logger
from engines.voice_engine import generate_voiceover
from engines.asset_engine import download_video_clips, generate_ambient_music
from engines.video_engine import assemble_video

log = get_logger("trailer")

# ── Hardcoded trailer script ─────────────────────────────────────────────────

TRAILER_NARRATION = (
    "What if every day started with something that actually blows your mind? "
    "We uncover historical mysteries buried for centuries. "
    "We share stoic wisdom that makes modern life make sense. "
    "We reveal what lurks in the deepest parts of the ocean. "
    "And we challenge your brain with riddles that prove you are smarter than you think. "
    "That is SooooCool. "
    "New videos every single day. "
    "Hit like and subscribe — you will not run out of cool things to talk about."
)

TRAILER_SCRIPT = {
    "title": "Welcome to SooooCool 🔥",
    "description": (
        "History mysteries, stoic wisdom, ocean secrets, and brain-bending puzzles. "
        "New Shorts every day. Subscribe!"
    ),
    "hashtags": ["#Shorts", "#SooooCool", "#History", "#Philosophy", "#Ocean"],
    "narration": TRAILER_NARRATION,
    "thumbnail_text": "SOOO COOL",
    "hook": "What if every day started with something that blows your mind?",
    "cta": "Hit like and subscribe for more!",
    "affiliate_line": "",
    "affiliate_book": "",
}

TRAILER_KEYWORDS = [
    "ancient ruins mystery",
    "deep ocean bioluminescent",
    "meditation sunrise",
    "brain puzzle neon",
    "dramatic history cinematic",
    "underwater dark ocean",
]

TRAILER_VOICE_ID = (
    os.environ.get("EL_VOICE_HISTORY")
    or os.environ.get("ELEVENLABS_VOICE_ID")
    or "pNInz6obpgDQGcFmaJgB"   # ElevenLabs Adam (default)
)


def main():
    log.info("═══ SooooCool Trailer Generator ═══")

    run_dir = config.OUTPUT_DIR / "trailer_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Run dir: {run_dir}")

    # ── Step 1: Download b-roll clips ────────────────────────────────────────
    log.info("Step 1/4 — Downloading b-roll from Pexels…")
    clips = download_video_clips(TRAILER_KEYWORDS, run_dir)
    log.info(f"  {len(clips)} clips downloaded")

    # ── Step 2: Generate ambient music ───────────────────────────────────────
    log.info("Step 2/4 — Generating ambient music…")
    # Estimate ~40s narration; music will be trimmed to actual duration later
    music = generate_ambient_music(50.0, run_dir)
    log.info(f"  Music: {music}")

    assets = {
        "video_clips": clips,
        "music_file": music,
    }

    # ── Step 3: Synthesise narration ─────────────────────────────────────────
    log.info("Step 3/4 — Synthesising voice narration…")
    # Temporarily override voice ID for this run
    original_env = os.environ.get("NICHE", "")
    os.environ["NICHE"] = "historical_mysteries"  # use any valid niche for voice lookup

    voice = generate_voiceover(TRAILER_NARRATION, run_dir)
    log.info(f"  Voice: {voice['duration']:.1f}s via {voice['engine']}")

    if original_env:
        os.environ["NICHE"] = original_env

    # ── Step 4: Assemble video ───────────────────────────────────────────────
    log.info("Step 4/4 — Assembling trailer video…")
    result = assemble_video(TRAILER_SCRIPT, assets, voice, run_dir)
    log.info(f"  ✅ Trailer: {result['duration']:.1f}s")

    # Copy to output root for artifact upload
    trailer_out = config.OUTPUT_DIR / "trailer.mp4"
    shutil.copy(result["video_file"], trailer_out)
    log.info(f"  Saved → {trailer_out}")

    print(f"\n✅ TRAILER COMPLETE: {trailer_out}")


if __name__ == "__main__":
    main()
