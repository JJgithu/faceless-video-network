"""
main.py — Orchestrator for the Faceless Video Network pipeline.

Runs ONE complete video generation cycle:
  1. Trend Engine   — finds the best story for the active niche
  2. Script Engine  — Gemini writes the full script
  3. Asset Engine   — downloads Pexels footage + generates music
  4. Voice Engine   — ElevenLabs (or edge-tts) narration + kinetic captions
  5. Video Engine   — FFmpeg assembles the 1080×1920 portrait video
  6. Publisher      — uploads to YouTube Shorts + TikTok

Called by GitHub Actions twice per day (9am ET + 9pm ET).
Can also be run locally for testing.

Usage:
  NICHE=historical_mysteries python main.py
  NICHE=stoic_philosophy python main.py --dry-run
"""

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import config
from engines.trend_engine import get_trending_topic
from engines.script_engine import generate_script
from engines.asset_engine import gather_assets
from engines.voice_engine import generate_voiceover
from engines.video_engine import assemble_video
from engines.publisher import publish
from utils.file_manager import fresh_run_dir, cleanup
from utils.logger import get_logger

log = get_logger("main")


def run_pipeline(dry_run: bool = False) -> dict:
    """
    Execute the full video generation and publishing pipeline.
    Returns a results dict with all URLs and metadata.
    """
    niche = config.get_niche()
    start_time = datetime.utcnow()

    log.info("=" * 65)
    log.info(f"  FACELESS VIDEO NETWORK — {niche['display_name']} {niche['emoji']}")
    log.info(f"  Run started: {start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"  Dry run: {dry_run}")
    log.info("=" * 65)

    run_dir = fresh_run_dir()
    results = {
        "niche": config.ACTIVE_NICHE,
        "started_at": start_time.isoformat(),
        "topic": None,
        "title": None,
        "youtube_url": None,
        "tiktok_url": None,
        "video_duration": None,
        "voice_engine": None,
        "success": False,
        "error": None,
    }

    try:
        # ── 1. Discover trending topic ──────────────────────────────────────
        topic = get_trending_topic()
        results["topic"] = topic["topic"]
        log.info(f"\n✦ Topic: {topic['topic']}\n  Angle: {topic['angle']}\n")

        # ── 2. Generate script ──────────────────────────────────────────────
        script = generate_script(topic)
        results["title"] = script["title"]
        log.info(f"✦ Title: {script['title']}\n")

        # ── 3. Download assets ──────────────────────────────────────────────
        assets = gather_assets(topic, script, run_dir)
        log.info(f"✦ Assets: {len(assets['video_clips'])} clips downloaded\n")

        # ── 4. Generate voiceover + captions ──────────────────────────────
        voice = generate_voiceover(script["narration"], run_dir)
        results["voice_engine"] = voice["engine"]
        log.info(f"✦ Voice: {voice['duration']:.1f}s via {voice['engine']}\n")

        # ── 5. Assemble video ──────────────────────────────────────────────
        video = assemble_video(script, assets, voice, run_dir)
        results["video_duration"] = round(video["duration"], 1)
        log.info(f"✦ Video: {video['duration']:.1f}s → {video['video_file'].name}\n")

        if dry_run:
            log.info("🔵 DRY RUN — skipping upload. Video saved to:")
            log.info(f"   {video['video_file']}")
            results["success"] = True
            return results

        # ── 6. Publish to YouTube + TikTok ─────────────────────────────────
        publish_result = publish(video["video_file"], script)
        results["youtube_url"] = publish_result.get("youtube_url")
        results["tiktok_url"]  = publish_result.get("tiktok_url")
        results["success"] = bool(
            results["youtube_url"] or results["tiktok_url"]
        )

        elapsed = (datetime.utcnow() - start_time).seconds
        log.info("=" * 65)
        log.info(f"  ✅ PIPELINE COMPLETE in {elapsed}s")
        log.info(f"  YouTube: {results['youtube_url'] or 'failed'}")
        log.info(f"  TikTok:  {results['tiktok_url'] or 'failed'}")
        log.info("=" * 65)

    except Exception as exc:
        results["error"] = str(exc)
        log.error(f"Pipeline failed: {exc}")
        log.debug(traceback.format_exc())

    finally:
        # Always clean up temp files to avoid filling disk
        try:
            cleanup(run_dir)
        except Exception:
            pass

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Faceless Video Network — autonomous video pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate video but skip uploading",
    )
    parser.add_argument(
        "--niche",
        choices=list(config.NICHES.keys()),
        help="Override the NICHE environment variable",
    )
    args = parser.parse_args()

    # Allow CLI override of NICHE
    if args.niche:
        import os
        os.environ["NICHE"] = args.niche
        config.ACTIVE_NICHE = args.niche

    results = run_pipeline(dry_run=args.dry_run)

    # Print JSON results for GitHub Actions step output
    print("\n── RESULTS ──")
    print(json.dumps(results, indent=2))

    sys.exit(0 if results["success"] else 1)


if __name__ == "__main__":
    main()
