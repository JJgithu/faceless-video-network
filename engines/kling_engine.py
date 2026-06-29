"""
engines/kling_engine.py
─────────────────────────────────────────────────────────────────────────────
The Kling AI Cinematographer — generates AI video clips from text prompts.

Uses the Kling AI Standard API to generate 4 × 5-second portrait (9:16) video
clips from the visual prompts produced by Claude 3.5 Sonnet.

CRITICAL IMPLEMENTATION DETAILS:
  - Model: kling-v1 Standard (NOT Pro) — cost-effective for daily automation
  - Aspect Ratio: ALWAYS 9:16 — portrait mode for YouTube Shorts
  - Duration: ALWAYS 5 seconds per clip
  - Async Polling: Kling takes 2-4 minutes to render. We submit all 4 clips
    simultaneously and poll the status endpoint every 15s until SUCCESS.
  - Timeout: 10 minutes max per clip. After timeout, skip that clip.
  - Fallback: If ALL Kling clips fail, the pipeline stops with an error.

API Reference:
  - Base URL: https://api-singapore.klingai.com
  - Auth: Bearer token in Authorization header
  - POST /v1/videos/text2video → returns task_id
  - GET /v1/videos/text2video/{task_id} → returns status + video URL
"""

import time
from pathlib import Path
from typing import TypedDict

import httpx

import config
from utils.logger import get_logger

log = get_logger(__name__)


class KlingResult(TypedDict):
    video_clips: list[Path]     # Downloaded .mp4 clip paths
    failed_clips: list[int]     # Clip numbers that failed
    all_succeeded: bool         # True if all 4 clips generated


# ── API Helpers ────────────────────────────────────────────────────────────

def _kling_headers() -> dict:
    """Build authentication headers for Kling API."""
    return {
        "Authorization": f"Bearer {config.KLING_API_KEY}",
        "Content-Type": "application/json",
    }


def _submit_text2video(prompt: str, clip_number: int) -> str | None:
    """
    Submit a text-to-video generation task to Kling AI.

    Returns the task_id on success, None on failure.
    """
    payload = {
        "model": config.KLING_MODEL,
        "prompt": prompt,
        "aspect_ratio": config.KLING_ASPECT_RATIO,
        "duration": config.KLING_DURATION,
    }

    log.info(
        f"Kling: submitting clip {clip_number} | "
        f"model={config.KLING_MODEL} | "
        f"ratio={config.KLING_ASPECT_RATIO} | "
        f"duration={config.KLING_DURATION}s"
    )
    log.debug(f"Kling prompt: {prompt[:120]}…")

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{config.KLING_API_BASE}/v1/videos/text2video",
                json=payload,
                headers=_kling_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        # Handle different response formats from Kling API
        task_id = (
            data.get("task_id")
            or data.get("data", {}).get("task_id")
            or data.get("id")
            or data.get("data", {}).get("id")
        )

        if task_id:
            log.info(f"Kling clip {clip_number}: task_id={task_id}")
            return str(task_id)
        else:
            log.error(f"Kling clip {clip_number}: no task_id in response: {data}")
            return None

    except httpx.HTTPStatusError as exc:
        log.error(
            f"Kling clip {clip_number} submission failed: "
            f"HTTP {exc.response.status_code} — {exc.response.text[:500]}"
        )
        return None
    except Exception as exc:
        log.error(f"Kling clip {clip_number} submission error: {exc}")
        return None


def _poll_task_status(task_id: str, clip_number: int) -> str | None:
    """
    Poll the Kling API for task completion.

    Polls every KLING_POLL_INTERVAL seconds until:
      - Status is SUCCESS/completed → return the video URL
      - Status is FAILED → return None
      - Timeout exceeded → return None

    Returns the video download URL on success, None on failure.
    """
    poll_interval = config.KLING_POLL_INTERVAL
    timeout = config.KLING_TIMEOUT
    elapsed = 0

    log.info(
        f"Kling clip {clip_number}: polling every {poll_interval}s "
        f"(timeout: {timeout}s)…"
    )

    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{config.KLING_API_BASE}/v1/videos/text2video/{task_id}",
                    headers=_kling_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            # Handle nested response format
            task_data = data.get("data", data)
            status = (
                task_data.get("status", "")
                or task_data.get("task_status", "")
            ).lower()

            log.debug(
                f"Kling clip {clip_number}: status={status} "
                f"({elapsed}s / {timeout}s)"
            )

            # ── Success ────────────────────────────────────────────────────
            if status in ("success", "completed", "succeed"):
                # Extract video URL from various response formats
                video_url = None

                # Format 1: task_data.video_url
                video_url = task_data.get("video_url")

                # Format 2: task_data.videos[0].url
                if not video_url:
                    videos = task_data.get("videos", [])
                    if videos and isinstance(videos, list):
                        video_url = videos[0].get("url") or videos[0].get("video_url")

                # Format 3: task_data.output.video_url
                if not video_url:
                    output = task_data.get("output", {})
                    if isinstance(output, dict):
                        video_url = output.get("video_url") or output.get("url")

                # Format 4: task_data.result.videos[0].url
                if not video_url:
                    result = task_data.get("result", {})
                    if isinstance(result, dict):
                        result_videos = result.get("videos", [])
                        if result_videos:
                            video_url = result_videos[0].get("url")

                # Format 5: task_data.task_result.videos[0].url
                # (confirmed real Kling API format as of June 2026)
                if not video_url:
                    task_result = task_data.get("task_result", {})
                    if isinstance(task_result, dict):
                        tr_videos = task_result.get("videos", [])
                        if tr_videos:
                            video_url = tr_videos[0].get("url")

                if video_url:
                    log.info(
                        f"✅ Kling clip {clip_number}: completed in {elapsed}s"
                    )
                    return video_url
                else:
                    log.error(
                        f"Kling clip {clip_number}: status=success but no video URL "
                        f"in response: {data}"
                    )
                    return None

            # ── Failed ─────────────────────────────────────────────────────
            if status in ("failed", "error", "cancelled"):
                error_msg = task_data.get("error", task_data.get("message", "unknown"))
                log.error(
                    f"Kling clip {clip_number}: generation FAILED — {error_msg}"
                )
                return None

            # ── Still processing ───────────────────────────────────────────
            # Status is "processing", "pending", "queued", etc. — keep polling

        except Exception as exc:
            log.warning(
                f"Kling clip {clip_number}: poll error at {elapsed}s — {exc}"
            )
            # Don't break — transient errors happen, keep polling

    # ── Timeout ────────────────────────────────────────────────────────────
    log.error(
        f"Kling clip {clip_number}: TIMEOUT after {timeout}s "
        f"(task_id={task_id})"
    )
    return None


def _download_video(url: str, dest: Path) -> bool:
    """Download a video file from the given URL. Returns True on success."""
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)

        size_mb = dest.stat().st_size / 1_048_576
        log.info(f"Downloaded Kling video: {dest.name} ({size_mb:.1f} MB)")
        return True

    except Exception as exc:
        log.error(f"Kling video download failed: {exc}")
        if dest.exists():
            dest.unlink()
        return False


# ── Public API ─────────────────────────────────────────────────────────────

def generate_kling_clips(
    video_clips: list[dict],
    run_dir: Path,
) -> KlingResult:
    """
    Generate AI video clips using Kling AI Standard.

    Takes the video_clips array from Claude's script output and:
      1. Submits all 4 clips simultaneously to Kling API
      2. Polls each task for completion
      3. Downloads the generated .mp4 files
      4. Returns a KlingResult with all downloaded clip paths

    If a clip fails, it is retried once. If it fails again, it is skipped.
    """
    log.info("═══ Kling Engine: generating AI video clips ═══")
    log.info(
        f"Model: {config.KLING_MODEL} | "
        f"Aspect: {config.KLING_ASPECT_RATIO} | "
        f"Duration: {config.KLING_DURATION}s | "
        f"Clips: {len(video_clips)}"
    )

    clips_dir = run_dir / "kling_clips"
    clips_dir.mkdir(exist_ok=True)

    downloaded: list[Path] = []
    failed: list[int] = []

    # ── Step 1: Submit all clips simultaneously ───────────────────────────
    tasks: list[tuple[int, str | None]] = []
    for clip in video_clips:
        clip_num = clip.get("clip_number", len(tasks) + 1)
        prompt = clip.get("kling_prompt", "")

        # Ensure portrait orientation keywords are in the prompt
        if "9:16" not in prompt and "vertical" not in prompt.lower():
            prompt += ", vertical portrait composition 9:16 aspect ratio"

        task_id = _submit_text2video(prompt, clip_num)
        tasks.append((clip_num, task_id))

    # ── Step 2: Poll each task for completion ─────────────────────────────
    for clip_num, task_id in tasks:
        if not task_id:
            log.warning(f"Kling clip {clip_num}: skipped (submission failed)")
            failed.append(clip_num)
            continue

        video_url = _poll_task_status(task_id, clip_num)

        if not video_url:
            # Retry once
            log.warning(f"Kling clip {clip_num}: retrying submission…")
            prompt = video_clips[clip_num - 1].get("kling_prompt", "")
            retry_task_id = _submit_text2video(prompt, clip_num)
            if retry_task_id:
                video_url = _poll_task_status(retry_task_id, clip_num)

        if not video_url:
            log.error(f"Kling clip {clip_num}: FAILED after retry")
            failed.append(clip_num)
            continue

        # ── Step 3: Download the video ────────────────────────────────────
        dest = clips_dir / f"kling_clip_{clip_num:02d}.mp4"
        if _download_video(video_url, dest):
            downloaded.append(dest)
        else:
            failed.append(clip_num)

    # ── Summary ───────────────────────────────────────────────────────────
    all_ok = len(downloaded) == len(video_clips)
    log.info(
        f"Kling Engine: {len(downloaded)}/{len(video_clips)} clips generated | "
        f"failed: {failed or 'none'}"
    )

    if not downloaded:
        log.error("ALL Kling clips failed — pipeline will stop (no fallback)")

    return KlingResult(
        video_clips=downloaded,
        failed_clips=failed,
        all_succeeded=all_ok,
    )
