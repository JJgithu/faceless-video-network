"""
engines/video_engine.py
─────────────────────────────────────────────────────────────────────────────
Assembles the final portrait-mode video using FFmpeg.

Pipeline:
  1. Convert each stock clip to portrait 1080×1920 with blurred background
  2. Trim & loop clips to exactly match narration duration
  3. Render title card (intro) and CTA card (outro) as static images → video
  4. Concatenate: [intro] + [b-roll] + [outro]
  5. Mix audio: narration at 100% + background music at MUSIC_VOLUME
  6. Burn in SRT captions with styled font
  7. Export final H.264 .mp4 ready for upload

All FFmpeg calls use subprocess for maximum compatibility on GitHub Actions.
"""

import subprocess
import textwrap
from pathlib import Path
from typing import TypedDict

from PIL import Image, ImageDraw, ImageFont

import config
from engines.asset_engine import Assets
from engines.script_engine import Script
from engines.voice_engine import VoiceResult
from utils.logger import get_logger

log = get_logger(__name__)

W, H = config.VIDEO_WIDTH, config.VIDEO_HEIGHT   # 1080 × 1920
FPS = config.VIDEO_FPS


# ── FFmpeg helpers ─────────────────────────────────────────────────────────

def _run_ff(args: list[str], label: str = "") -> None:
    """Run an FFmpeg command, logging stderr on failure."""
    cmd = ["ffmpeg", "-y"] + args
    log.debug(f"FFmpeg {label}: {' '.join(cmd[:6])}…")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"FFmpeg {label} failed:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"FFmpeg error ({label})")


def _video_duration(path: Path) -> float:
    """Return the duration of a video file in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


# ── Portrait conversion ────────────────────────────────────────────────────

def _to_portrait(src: Path, dst: Path, duration: float, pan_direction: int = 0) -> None:
    """
    Convert any clip to portrait 1080x1920 — true full-bleed (no black bars).

    Scale to FILL the frame (at least 1080 wide AND 1920 tall) then center-crop
    the excess. Adds a slow horizontal pan and smooth fade in/out for a
    cinematic motion feel between clips.
    """
    fade_out_start = max(duration - 0.35, 0.1)

    # Alternate pan directions for visual variety
    if pan_direction == 0:    # pan right-to-left (x starts at max, moves toward 0)
        crop_x = f"(iw-{W})*(1-t/{max(duration,0.1):.3f})"
    elif pan_direction == 1:  # pan left-to-right (x starts at 0, moves toward max)
        crop_x = f"(iw-{W})*t/{max(duration,0.1):.3f}"
    else:                     # static center crop
        crop_x = f"(iw-{W})/2"

    vf = (
        # Scale to completely fill 1080x1920 (no letterboxing, no black bars)
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        # Center-crop vertically; pan horizontally for motion
        f"crop={W}:{H}:{crop_x}:(ih-{H})/2,"
        # Smooth fade in/out between clips
        f"fade=t=in:st=0:d=0.35,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.35"
    )
    _run_ff(
        [
            "-i", str(src),
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",   # drop audio from clips — narration added later
            str(dst),
        ],
        label="portrait",
    )



# ── Title / CTA cards ──────────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load a system font; fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_card(
    text: str,
    sub_text: str,
    duration: float,
    dest: Path,
    bg_color: tuple = (10, 10, 20),
    accent_color: tuple = (255, 80, 80),
) -> None:
    """
    Render a full-bleed title or CTA card as a silent video clip.
    Uses Pillow to create the frame, then FFmpeg to make it a video.
    """
    img = Image.new("RGB", (W, H), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Accent bar at the top
    draw.rectangle([0, 0, W, 12], fill=accent_color)
    draw.rectangle([0, H - 12, W, H], fill=accent_color)

    # Main text — wrap at ~18 chars for large font
    font_main = _load_font(60)
    font_sub  = _load_font(32)

    lines = textwrap.wrap(text, width=16) or [text]
    line_height = 78
    total_text_h = len(lines) * line_height
    y_start = (H - total_text_h) // 2 - (40 if sub_text else 0)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_main)
        tw = bbox[2] - bbox[0]
        x = max((W - tw) // 2, 40)   # at least 40px from edge
        y = y_start + i * line_height
        # Drop shadow
        draw.text((x + 3, y + 3), line, font=font_main, fill=(0, 0, 0))
        draw.text((x, y), line, font=font_main, fill=(255, 255, 255))

    # Sub-text — one line only, truncated to 42 chars
    if sub_text:
        sub_line = sub_text if len(sub_text) <= 42 else sub_text[:39] + "…"
        bbox = draw.textbbox((0, 0), sub_line, font=font_sub)
        tw = bbox[2] - bbox[0]
        x_sub = max((W - tw) // 2, 40)
        y_sub = y_start + len(lines) * line_height + 20
        draw.text((x_sub, y_sub), sub_line, font=font_sub, fill=accent_color)

    frame_path = dest.parent / f"{dest.stem}_frame.png"
    img.save(frame_path)

    _run_ff(
        [
            "-loop", "1", "-i", str(frame_path),
            "-t", str(duration),
            "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(dest),
        ],
        label="card",
    )
    frame_path.unlink(missing_ok=True)


# ── Clip assembly ──────────────────────────────────────────────────────────

def _assemble_broll(
    portrait_clips: list[Path],
    target_duration: float,
    out: Path,
) -> None:
    """
    Concatenate portrait clips (looping if needed) to fill target_duration.
    Writes a silent video segment.
    """
    clips_needed: list[Path] = []
    total = 0.0
    pool = list(portrait_clips)

    while total < target_duration:
        for clip in pool:
            dur = min(_video_duration(clip), target_duration - total)
            clips_needed.append((clip, dur))
            total += dur
            if total >= target_duration:
                break

    # Build concat file
    concat_file = out.parent / "concat.txt"
    with open(concat_file, "w") as fh:
        for clip, dur in clips_needed:
            fh.write(f"file '{clip.as_posix()}'\n")
            fh.write(f"duration {dur:.3f}\n")

    _run_ff(
        [
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        label="broll-concat",
    )
    concat_file.unlink(missing_ok=True)


# ── Segment concat ─────────────────────────────────────────────────────────

def _concat_segments(segments: list[Path], out: Path) -> None:
    """Concatenate intro + broll + outro into one silent video."""
    concat_file = out.parent / "segments.txt"
    with open(concat_file, "w") as fh:
        for seg in segments:
            fh.write(f"file '{seg.as_posix()}'\n")

    _run_ff(
        [
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        label="concat-segments",
    )
    concat_file.unlink(missing_ok=True)


# ── Audio mix ──────────────────────────────────────────────────────────────

def _mix_audio(
    silent_video: Path,
    narration: Path,
    music: Path,
    total_duration: float,
    out: Path,
) -> None:
    """
    Combine the silent video with narration (100%) + background music (quiet).
    The music loops/trims to match total_duration.
    """
    music_vol = config.MUSIC_VOLUME
    _run_ff(
        [
            "-i", str(silent_video),
            "-i", str(narration),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex",
            f"[1:a]volume=1.0[narr];"
            f"[2:a]volume={music_vol},atrim=0:{total_duration},asetpts=PTS-STARTPTS[mus];"
            f"[narr][mus]amix=inputs=2:duration=first:dropout_transition=2[audio]",
            "-map", "0:v",
            "-map", "[audio]",
            "-t", str(total_duration),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            str(out),
        ],
        label="audio-mix",
    )


# ── Caption burn-in ────────────────────────────────────────────────────────

def _burn_captions(src: Path, ass: Path, out: Path) -> None:
    """
    Burn kinetic ASS captions into the video.
    ASS supports per-cue fade-in/out (\fad tag) for the pop-in animation effect
    that's the hallmark of viral faceless channels.
    """
    if not ass.exists() or ass.stat().st_size < 50:
        log.warning("ASS file missing or empty — skipping captions")
        import shutil; shutil.copy(src, out)
        return

    # Escape path for FFmpeg filter graph
    ass_escaped = str(ass).replace("\\", "/").replace(":", "\\:")

    _run_ff(
        [
            "-i", str(src),
            "-vf", f"ass={ass_escaped}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            str(out),
        ],
        label="ass-captions",
    )


# ── Public API ─────────────────────────────────────────────────────────────

class VideoResult(TypedDict):
    video_file: Path   # Final .mp4 ready for upload
    duration: float    # Actual video duration


def assemble_video(
    script: Script,
    assets: Assets,
    voice: VoiceResult,
    run_dir: Path,
) -> VideoResult:
    """
    Orchestrate all FFmpeg steps to produce the final portrait video.
    """
    log.info("═══ Video Engine: assembling final video ═══")

    narration_duration = voice["duration"]
    total_duration = (
        config.INTRO_DURATION + narration_duration + config.OUTRO_DURATION
    )
    total_duration = min(total_duration, config.MAX_VIDEO_DURATION)
    broll_duration = total_duration - config.INTRO_DURATION - config.OUTRO_DURATION

    # ── Step 1: Convert clips to portrait ──────────────────────────────────
    log.info("Step 1/6 — Converting clips to portrait 1080×1920…")
    portrait_clips: list[Path] = []
    for i, clip in enumerate(assets["video_clips"]):
        dst = run_dir / f"portrait_{i:02d}.mp4"
        # Cap individual clips at 12s; alternate pan direction for variety
        clip_dur = min(_video_duration(clip), 12.0)
        pan = i % 3   # 0=pan-right, 1=pan-left, 2=static-center
        _to_portrait(clip, dst, clip_dur, pan_direction=pan)
        portrait_clips.append(dst)

    # ── Step 2: Assemble b-roll ────────────────────────────────────────────
    log.info("Step 2/6 — Assembling b-roll segment…")
    broll_path = run_dir / "broll.mp4"
    _assemble_broll(portrait_clips, broll_duration, broll_path)

    # ── Step 3: Title card (intro) ─────────────────────────────────────────
    log.info("Step 3/6 — Rendering title card…")
    intro_path = run_dir / "intro.mp4"
    _render_card(
        text=script["thumbnail_text"],  # 2-3 words ALL CAPS — stays clean
        sub_text="",                     # no sub-text on title card
        duration=config.INTRO_DURATION,
        dest=intro_path,
    )

    # ── Step 4: CTA card (outro) ───────────────────────────────────────────
    log.info("Step 4/6 — Rendering CTA card…")
    outro_path = run_dir / "outro.mp4"
    _render_card(
        text="FOLLOW",
        sub_text=script["cta"],
        duration=config.OUTRO_DURATION,
        dest=outro_path,
        accent_color=(80, 200, 120),
    )

    # ── Step 5: Concatenate all segments ──────────────────────────────────
    log.info("Step 5/6 — Concatenating segments…")
    silent_video = run_dir / "silent.mp4"
    _concat_segments([intro_path, broll_path, outro_path], silent_video)

    # ── Step 6: Mix audio ──────────────────────────────────────────────────
    log.info("Step 6a/6 — Mixing narration + background music…")
    mixed_video = run_dir / "mixed.mp4"
    _mix_audio(
        silent_video,
        voice["audio_file"],
        assets["music_file"],
        total_duration,
        mixed_video,
    )

    # ── Step 7: Burn captions ──────────────────────────────────────────────
    log.info("Step 6b/6 — Burning kinetic captions…")
    final_video = run_dir / "final.mp4"
    _burn_captions(mixed_video, voice["ass_file"], final_video)

    actual_duration = _video_duration(final_video)
    log.info(f"✅ Video assembled: {actual_duration:.1f}s → {final_video.name}")

    return VideoResult(video_file=final_video, duration=actual_duration)
