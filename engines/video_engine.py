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


def _render_card_png(
    text: str,
    sub_text: str,
    dest: Path,
    bg_color: tuple = (10, 10, 20),
    accent_color: tuple = (255, 80, 80),
) -> None:
    """
    Render a title or CTA card as a PNG image (no video encoding).
    The PNG is overlaid on the b-roll via FFmpeg filter, not concatenated.
    This ensures perfect audio/video sync — no separate silent segments.
    """
    img = Image.new("RGB", (W, H), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Accent bars
    draw.rectangle([0, 0, W, 10], fill=accent_color)
    draw.rectangle([0, H - 10, W, H], fill=accent_color)

    font_main = _load_font(60)
    font_sub  = _load_font(32)

    lines = textwrap.wrap(text, width=16) or [text]
    line_height = 78
    total_text_h = len(lines) * line_height
    y_start = (H - total_text_h) // 2 - (40 if sub_text else 0)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_main)
        tw = bbox[2] - bbox[0]
        x = max((W - tw) // 2, 40)
        y = y_start + i * line_height
        draw.text((x + 3, y + 3), line, font=font_main, fill=(0, 0, 0))
        draw.text((x, y), line, font=font_main, fill=(255, 255, 255))

    if sub_text:
        sub_line = sub_text if len(sub_text) <= 42 else sub_text[:39] + "…"
        bbox = draw.textbbox((0, 0), sub_line, font=font_sub)
        tw = bbox[2] - bbox[0]
        x_sub = max((W - tw) // 2, 40)
        y_sub = y_start + len(lines) * line_height + 20
        draw.text((x_sub, y_sub), sub_line, font=font_sub, fill=accent_color)

    img.save(dest)


def _overlay_cards(
    broll: Path,
    intro_png: Path,
    outro_png: Path,
    total_duration: float,
    out: Path,
) -> None:
    """
    Overlay the title card for the first INTRO_DURATION seconds and the CTA card
    for the last OUTRO_DURATION seconds, directly on top of the b-roll.

    The b-roll plays for the ENTIRE video — no separate silent intro/outro
    segments means perfect audio/video sync and no black screen gaps.
    """
    intro_end   = config.INTRO_DURATION
    outro_start = max(total_duration - config.OUTRO_DURATION, intro_end)

    _run_ff(
        [
            "-i", str(broll),
            "-loop", "1", "-i", str(intro_png),
            "-loop", "1", "-i", str(outro_png),
            "-filter_complex",
            # Scale PNGs to exact frame size, then overlay with time gates
            f"[1:v]scale={W}:{H}[intro_card];"
            f"[2:v]scale={W}:{H}[outro_card];"
            f"[0:v][intro_card]overlay=x=0:y=0:"
            f"enable='between(t,0,{intro_end:.3f})'[v1];"
            f"[v1][outro_card]overlay=x=0:y=0:"
            f"enable='between(t,{outro_start:.3f},{total_duration:.3f})'[vout]",
            "-map", "[vout]",
            "-t", f"{total_duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        label="overlay-cards",
    )



# ── Clip assembly ──────────────────────────────────────────────────────────

def _assemble_broll(
    portrait_clips: list[Path],
    target_duration: float,
    out: Path,
) -> None:
    """
    Concatenate portrait clips (looping if needed) to fill target_duration.
    Generates 2s extra buffer so the hard -t trim always has content to cut.
    """
    buffered = target_duration + 2.0   # always overshoot slightly
    clips_needed: list[tuple[Path, float]] = []
    total = 0.0
    pool = list(portrait_clips)

    while total < buffered:
        for clip in pool:
            dur = min(_video_duration(clip), buffered - total)
            clips_needed.append((clip, dur))
            total += dur
            if total >= buffered:
                break

    # Build concat file
    concat_file = out.parent / "concat.txt"
    with open(concat_file, "w") as fh:
        for clip, dur in clips_needed:
            fh.write(f"file '{clip.as_posix()}'\n")
            fh.write(f"duration {dur:.3f}\n")
        # Repeat last clip without duration so FFmpeg always has a final frame
        fh.write(f"file '{clips_needed[-1][0].as_posix()}'\n")

    _run_ff(
        [
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-t", f"{target_duration:.3f}",   # hard trim to exact target
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
    sfx: Path,
    total_duration: float,
    out: Path,
) -> None:
    """
    Combine the silent video with narration (100%) + background music (quiet)
    + hook SFX at t=0.
    Uses tpad to clone the last video frame if the video stream is shorter than
    the audio, so there is never a black screen gap.
    """
    music_vol = config.MUSIC_VOLUME
    _run_ff(
        [
            "-i", str(silent_video),
            "-i", str(narration),
            "-stream_loop", "-1", "-i", str(music),
            "-i", str(sfx),
            "-filter_complex",
            # Clone last video frame for up to 5s so video never ends before audio
            f"[0:v]tpad=stop_mode=clone:stop_duration=5[vpad];"
            # Hook SFX: pad to full duration then mix at 80% into narration
            f"[3:a]volume=0.8,apad=whole_dur={total_duration:.3f}[sfx_padded];"
            # Narration: pad with silence to full duration
            f"[1:a]volume=1.0,apad=whole_dur={total_duration:.3f}[narr];"
            # Mix narration + SFX first
            f"[narr][sfx_padded]amix=inputs=2:duration=longest:dropout_transition=0[narr_sfx];"
            # Then mix with background music
            f"[2:a]volume={music_vol},atrim=0:{total_duration:.3f},"
            f"asetpts=PTS-STARTPTS[mus];"
            f"[narr_sfx][mus]amix=inputs=2:duration=longest:dropout_transition=1[audio]",
            "-map", "[vpad]",
            "-map", "[audio]",
            "-t", f"{total_duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
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

    New timeline (overlay-based — no sync gaps, no black screen):

      t=0                          t=narration_duration
      |-------- b-roll (full) ---------|    video = audio length
      |--intro--|                           title card overlay (first 2.5s)
                          |---outro--|       CTA overlay (last 3s)
      |---- narration + music ----------|   audio = video length
    """
    log.info("═══ Video Engine: assembling final video ═══")

    # Video = audio = narration length (no added silent segments)
    narration_duration = voice["duration"]
    total_duration     = min(narration_duration, config.MAX_VIDEO_DURATION)
    broll_duration     = total_duration   # b-roll fills the WHOLE video

    # ── Step 1: Convert clips to portrait ──────────────────────────────────
    log.info("Step 1/5 — Converting clips to portrait 1080×1920…")
    portrait_clips: list[Path] = []
    for i, clip in enumerate(assets["video_clips"]):
        dst = run_dir / f"portrait_{i:02d}.mp4"
        clip_dur = min(_video_duration(clip), 12.0)
        pan = i % 3
        _to_portrait(clip, dst, clip_dur, pan_direction=pan)
        portrait_clips.append(dst)

    # ── Step 2: Assemble b-roll for FULL video duration ─────────────────────
    log.info("Step 2/5 — Assembling b-roll segment…")
    broll_path = run_dir / "broll.mp4"
    _assemble_broll(portrait_clips, broll_duration, broll_path)

    # ── Step 3: Render card PNGs and overlay on b-roll ──────────────────────
    log.info("Step 3/5 — Rendering title + CTA cards…")
    intro_png = run_dir / "intro_card.png"
    outro_png = run_dir / "outro_card.png"
    _render_card_png(
        text=script["thumbnail_text"],
        sub_text="",
        dest=intro_png,
    )
    _render_card_png(
        text="FOLLOW FOR MORE",
        sub_text=script["cta"],
        dest=outro_png,
        accent_color=(80, 200, 120),
    )
    silent_video = run_dir / "silent.mp4"
    _overlay_cards(broll_path, intro_png, outro_png, total_duration, silent_video)

    # ── Step 4: Mix audio (narration + music, full video length) ────────────
    log.info("Step 4/5 — Mixing narration + background music…")
    mixed_video = run_dir / "mixed.mp4"
    _mix_audio(
        silent_video,
        voice["audio_file"],
        assets["music_file"],
        total_duration,
        mixed_video,
    )

    # ── Step 5: Burn captions ────────────────────────────────────────────────
    log.info("Step 5/5 — Burning kinetic captions…")
    final_video = run_dir / "final.mp4"
    _burn_captions(mixed_video, voice["ass_file"], final_video)

    actual_duration = _video_duration(final_video)
    log.info(f"✅ Video assembled: {actual_duration:.1f}s → {final_video.name}")

    return VideoResult(video_file=final_video, duration=actual_duration)
