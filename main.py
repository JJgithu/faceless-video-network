"""
main.py — Orchestrator for the Faceless Video Network pipeline.

Supports TWO pipeline modes (controlled by PIPELINE_MODE env var):

  HYBRID (default):
    1. Trend Engine   — finds the best story for the active niche
    2. Claude 3.5 Sonnet — writes script + 4 Kling AI visual prompts
    3. Kling AI Standard — generates 4 × 5s AI video clips (9:16 portrait)
    4. ElevenLabs TTS   — narration + 1.15x speedup + Hormozi captions
       (falls back to OpenAI TTS if ElevenLabs quota exhausted)
    5. FFmpeg Stitcher  — 0.5s hard cut + BOOM SFX + audio mix + captions
    6. Publisher        — uploads to YouTube Shorts + TikTok

  LEGACY:
    1. Trend Engine   — finds the best story for the active niche
    2. Gemini 2.5 Flash — writes the full script + SFX tags
    3. Pexels API      — downloads stock footage clips
    4. ElevenLabs TTS  — narration + Hormozi captions
    5. FFmpeg Stitcher — assembles the portrait video
    6. Publisher       — uploads to YouTube Shorts + TikTok

Called by GitHub Actions twice per day:
  - Morning run (9am ET)
  - Evening run (9pm ET)

Can also be run locally for testing:
  NICHE=historical_mysteries python main.py
  NICHE=deep_sea python main.py --dry-run
  PIPELINE_MODE=legacy python main.py --dry-run
"""

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import config
from engines.trend_engine import get_trending_topic
from engines.voice_engine import generate_voiceover, ElevenLabsQuotaError
from engines.video_engine import assemble_video
from engines.publisher import publish
from utils.file_manager import fresh_run_dir, cleanup
from utils.logger import get_logger

log = get_logger("main")


def _run_hybrid_pipeline(topic: dict, run_dir: Path, dry_run: bool) -> dict:
    """
    Execute the Hybrid AI pipeline:
    Claude 3.5 Sonnet → Kling AI Standard → ElevenLabs/OpenAI TTS → FFmpeg
    """
    from engines.hybrid_script_engine import generate_hybrid_script
    from engines.kling_engine import generate_kling_clips
    from engines.asset_engine import generate_ambient_music, generate_hook_sfx, build_inline_sfx_cues

    results = {
        "pipeline": "hybrid",
        "niche": config.ACTIVE_NICHE,
        "started_at": datetime.utcnow().isoformat(),
        "topic": topic["topic"],
        "title": None,
        "youtube_url": None,
        "tiktok_url": None,
        "video_duration": None,
        "voice_engine": None,
        "kling_clips_generated": 0,
        "kling_clips_failed": 0,
        "success": False,
        "error": None,
    }

    # ── 2. Generate script + Kling prompts (Claude 3.5 Sonnet) ──────────
    script = generate_hybrid_script(topic)
    results["title"] = script["youtube_title"]
    log.info(f"✦ Title: {script['youtube_title']}\n")
    log.info(f"✦ Hook: {script['hook']}\n")

    # ── 3. Generate AI video clips (Kling AI Standard) ──────────────────
    kling_result = generate_kling_clips(script["video_clips"], run_dir)
    results["kling_clips_generated"] = len(kling_result["video_clips"])
    results["kling_clips_failed"] = len(kling_result["failed_clips"])
    log.info(
        f"✦ Kling AI: {len(kling_result['video_clips'])} clips generated, "
        f"{len(kling_result['failed_clips'])} failed\n"
    )

    # All clips must come from Kling AI — no Pexels fallback
    video_clips = kling_result["video_clips"]
    if not video_clips:
        raise RuntimeError(
            "All 4 Kling AI clips failed to generate. "
            "Cannot produce video without AI-generated footage. "
            "Check Kling API key, quota, and logs above for details."
        )

    # ── Generate shared assets (music + SFX) ────────────────────────────
    music_duration = config.MAX_VIDEO_DURATION + 5
    music_file = generate_ambient_music(music_duration, run_dir)
    hook_sfx_file = generate_hook_sfx(run_dir)

    # Build SFX cues
    sfx_tags = script.get("sfx_tags", [])
    narration = script.get("narration", "") or script.get("spoken_script", "")
    _sfx_files, sfx_cues = build_inline_sfx_cues(
        narration=narration,
        voice_duration=config.MAX_VIDEO_DURATION,
        sfx_tags=sfx_tags,
        run_dir=run_dir,
    )

    # Build an Assets-compatible dict
    from engines.asset_engine import Assets
    assets = Assets(
        video_clips=video_clips,
        music_file=music_file,
        hook_sfx_file=hook_sfx_file,
        sfx_cues=sfx_cues,
    )
    log.info(f"✦ Assets: {len(video_clips)} clips + music + SFX ready\n")

    # ── 4. Generate voiceover (ElevenLabs → OpenAI TTS fallback) ────────
    narration_text = script.get("narration", "") or script.get("spoken_script", "")
    voice = generate_voiceover(narration_text, run_dir)
    results["voice_engine"] = voice["engine"]
    log.info(
        f"✦ Voice: {voice['duration']:.1f}s via {voice['engine']} "
        f"(speedup: {config.TTS_SPEEDUP}x)\n"
    )

    # ── 5. Assemble video (FFmpeg — 0.5s cut + BOOM + captions) ─────────
    video = assemble_video(script, assets, voice, run_dir)
    results["video_duration"] = round(video["duration"], 1)
    log.info(f"✦ Video: {video['duration']:.1f}s → {video['video_file'].name}\n")

    return results, script, video


def _run_legacy_pipeline(topic: dict, run_dir: Path, dry_run: bool) -> dict:
    """
    Execute the Legacy pipeline:
    Gemini 2.5 Flash → Pexels → ElevenLabs → FFmpeg
    """
    from engines.script_engine import generate_script
    from engines.asset_engine import gather_assets

    results = {
        "pipeline": "legacy",
        "niche": config.ACTIVE_NICHE,
        "started_at": datetime.utcnow().isoformat(),
        "topic": topic["topic"],
        "title": None,
        "youtube_url": None,
        "tiktok_url": None,
        "video_duration": None,
        "voice_engine": None,
        "success": False,
        "error": None,
    }

    # ── 2. Generate script (Gemini) ────────────────────────────────────
    script = generate_script(topic)
    results["title"] = script["title"]
    log.info(f"✦ Title: {script['title']}\n")
    log.info(f"✦ Hook: {script.get('hook', '(see narration)')}\n")

    # ── 3. Download assets (Pexels clips + music + SFX) ────────────────
    assets = gather_assets(topic, script, run_dir)
    log.info(f"✦ Assets: {len(assets['video_clips'])} clips downloaded\n")

    # ── 4. Generate voiceover + aligned captions ───────────────────────
    voice = generate_voiceover(script["narration"], run_dir)
    results["voice_engine"] = voice["engine"]
    log.info(f"✦ Voice: {voice['duration']:.1f}s via {voice['engine']}\n")

    # ── 5. Assemble video ──────────────────────────────────────────────
    video = assemble_video(script, assets, voice, run_dir)
    results["video_duration"] = round(video["duration"], 1)
    log.info(f"✦ Video: {video['duration']:.1f}s → {video['video_file'].name}\n")

    return results, script, video


def run_pipeline(dry_run: bool = False) -> dict:
    """
    Execute the full video generation and publishing pipeline.
    Routes to hybrid or legacy pipeline based on PIPELINE_MODE config.
    Returns a results dict with all URLs and metadata.
    """
    niche = config.get_niche()
    start_time = datetime.utcnow()
    pipeline_mode = config.PIPELINE_MODE

    log.info("=" * 65)
    log.info(f"  FACELESS VIDEO NETWORK — {niche['display_name']} {niche['emoji']}")
    log.info(f"  Pipeline: {pipeline_mode.upper()}")
    log.info(f"  Run started: {start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"  Dry run: {dry_run}")
    log.info("=" * 65)

    run_dir = fresh_run_dir()

    # Initialize results early so error handlers always have something to write to
    results = {
        "pipeline": pipeline_mode,
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
        log.info(f"\n✦ Topic: {topic['topic']}\n  Angle: {topic['angle']}\n")

        # ── Route to appropriate pipeline ───────────────────────────────────
        if pipeline_mode == "hybrid":
            results, script, video = _run_hybrid_pipeline(topic, run_dir, dry_run)
        else:
            results, script, video = _run_legacy_pipeline(topic, run_dir, dry_run)

        if dry_run:
            # Copy video to a stable path before cleanup so the
            # GitHub Actions artifact upload step can find it
            import shutil
            artifact_path = config.OUTPUT_DIR / "preview_video.mp4"
            shutil.copy(video["video_file"], artifact_path)
            log.info(f"🔵 DRY RUN — video saved for download:")
            log.info(f"   {artifact_path}")
            results["video_file"] = str(artifact_path)
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
        log.info(f"  ✅ PIPELINE COMPLETE in {elapsed}s ({pipeline_mode.upper()})")
        log.info(f"  YouTube: {results['youtube_url'] or 'failed'}")
        log.info(f"  TikTok:  {results['tiktok_url'] or 'failed'}")
        log.info("=" * 65)

    except ElevenLabsQuotaError as exc:
        # ── TTS completely failed — HARD STOP ──────────────────────────────
        results["error"] = str(exc)
        results["voice_engine"] = "all_tts_failed"
        log.error("=" * 65)
        log.error("  ⛔ ALL TTS ENGINES FAILED — VIDEO PRODUCTION STOPPED")
        log.error(f"  {exc}")
        log.error("  Both ElevenLabs and Edge TTS failed. Check logs above.")
        log.error("=" * 65)

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
    parser.add_argument(
        "--pipeline",
        choices=["hybrid", "legacy"],
        help="Override the PIPELINE_MODE environment variable",
    )
    args = parser.parse_args()

    # Allow CLI override of NICHE
    if args.niche:
        import os
        os.environ["NICHE"] = args.niche
        config.ACTIVE_NICHE = args.niche

    # Allow CLI override of PIPELINE_MODE
    if args.pipeline:
        import os
        os.environ["PIPELINE_MODE"] = args.pipeline
        config.PIPELINE_MODE = args.pipeline

    results = run_pipeline(dry_run=args.dry_run)

    # Print JSON results for GitHub Actions step output
    print("\n── RESULTS ──")
    print(json.dumps(results, indent=2))

    sys.exit(0 if results["success"] else 1)


if __name__ == "__main__":
    main()
