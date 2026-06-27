"""
engines/video_engine.py
─────────────────────────────────────────────────────────────────────────────
Assembles the final portrait-mode video using FFmpeg.

Pipeline:
  1. Convert each stock clip to portrait 1080×1920 — max 2.5s per clip
     (constant visual dopamine: cuts every 2–3 seconds)
  2. Loop clips aggressively to fill narration duration (fixes freeze bug)
  3. Render CTA card as static PNG → overlaid at end only (NO intro card —
     video starts instantly in the action)
  4. Mix audio:
       - Narration at 100%
       - Background music at MUSIC_VOLUME (10%)
       - Hook SFX (boom+whoosh) at HOOK_SFX_VOLUME on frame 1
       - Inline SFX cues at SFX_VOLUME at their timestamps
  5. Burn Hormozi-style ASS captions (center-screen, 1–2 words, yellow, 88px)
  6. Export final H.264 .mp4 ready for upload

All FFmpeg calls use subprocess for maximum compatibility on GitHub Actions.
"""

import subprocess
import textwrap
from pathlib import Path
from typing import TypedDict

from PIL import Image, ImageDraw, ImageFont

import config
from engines.asset_engine import Assets, SfxCue
from engines.script_engine import Script
from engines.voice_engine import VoiceResult
from utils.logger import get_logger

log = get_logger(__name__)

W, H = config.VIDEO_WIDTH, config.VIDEO_HEIGHT   # 1080 × 1920
FPS  = config.VIDEO_FPS


# ── FFmpeg helpers ─────────────────────────────────────────────────────────

def _run_ff(args: list[str], label: str = "") -> None:
    """Run an FFmpeg command, logging stderr on failure."""
    cmd = ["ffmpeg", "-y"] + args
    log.debug(f"FFmpeg {label}: {' '.join(cmd[:6])}…")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"FFmpeg {label} failed:\n{result.stderr[-3000:]}")
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

    Key changes vs original:
      - NO fade-in: clips start INSTANTLY (was 0.35s fade — too slow)
      - Fade-out only 0.08s: barely perceptible, just prevents hard flash
      - Duration capped at CLIP_MAX_DURATION (2.5s) for constant visual variety
    """
    # Cap clip duration to enforce visual change every 2–3 seconds
    duration = min(duration, config.CLIP_MAX_DURATION)
    fade_out_start = max(duration - config.CLIP_FADE_DURATION, 0.05)

    # Alternate pan directions for visual variety
    if pan_direction == 0:    # pan right-to-left
        crop_x = f"(iw-{W})*(1-t/{max(duration,0.1):.3f})"
    elif pan_direction == 1:  # pan left-to-right
        crop_x = f"(iw-{W})*t/{max(duration,0.1):.3f}"
    else:                     # static center crop (zoom variant)
        crop_x = f"(iw-{W})/2"

    vf = (
        # Scale to completely fill 1080x1920 (no letterboxing, no black bars)
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        # Center-crop vertically; pan horizontally for motion
        f"crop={W}:{H}:{crop_x}:(ih-{H})/2,"
        # NO fade-in — instant start. Tiny fade-out only.
        f"fade=t=out:st={fade_out_start:.3f}:d={config.CLIP_FADE_DURATION:.3f}"
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


# ── CTA card (outro only — NO intro card) ─────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load a system font; fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_cta_card(text: str, sub_text: str, dest: Path) -> None:
    """
    Render the CTA (outro) card as a PNG.
    NO intro card — we no longer render a title overlay.
    The video starts on frame 1 with b-roll + voice, no title screen.
    """
    bg_color     = (8, 10, 18)
    accent_color = (80, 220, 130)   # vibrant green for CTA

    img  = Image.new("RGB", (W, H), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Accent bars top and bottom
    draw.rectangle([0, 0, W, 12], fill=accent_color)
    draw.rectangle([0, H - 12, W, H], fill=accent_color)

    font_main = _load_font(68)
    font_sub  = _load_font(36)

    lines = textwrap.wrap(text, width=14) or [text]
    line_height = 88
    total_text_h = len(lines) * line_height
    y_start = (H - total_text_h) // 2 - (50 if sub_text else 0)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_main)
        tw = bbox[2] - bbox[0]
        x = max((W - tw) // 2, 40)
        y = y_start + i * line_height
        # Drop shadow
        draw.text((x + 4, y + 4), line, font=font_main, fill=(0, 0, 0))
        draw.text((x, y), line, font=font_main, fill=(255, 255, 255))

    if sub_text:
        sub_line = sub_text if len(sub_text) <= 48 else sub_text[:45] + "…"
        bbox = draw.textbbox((0, 0), sub_line, font=font_sub)
        tw = bbox[2] - bbox[0]
        x_sub = max((W - tw) // 2, 40)
        y_sub = y_start + len(lines) * line_height + 24
        draw.text((x_sub, y_sub), sub_line, font=font_sub, fill=accent_color)

    img.save(dest)


def _overlay_cta(broll: Path, outro_png: Path, total_duration: float, out: Path) -> None:
    """
    Overlay ONLY the CTA card for the last OUTRO_DURATION seconds.
    The intro is gone — b-roll plays from frame 0 with voice immediately.
    """
    outro_start = max(total_duration - config.OUTRO_DURATION, 0.5)

    _run_ff(
        [
            "-i", str(broll),
            "-loop", "1", "-i", str(outro_png),
            "-filter_complex",
            f"[1:v]scale={W}:{H}[outro_card];"
            f"[0:v][outro_card]overlay=x=0:y=0:"
            f"enable='between(t,{outro_start:.3f},{total_duration:.3f})'[vout]",
            "-map", "[vout]",
            "-t", f"{total_duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        label="overlay-cta",
    )


# ── Clip assembly — with guaranteed loop coverage ──────────────────────────

def _assemble_broll(
    portrait_clips: list[Path],
    target_duration: float,
    out: Path,
) -> None:
    """
    Concatenate portrait clips (looping aggressively) to fill target_duration.

    Bug fix: The original version could stall if clips didn't cover the target.
    Fix: Loop the clip pool at least 3× to guarantee coverage, then hard-trim.
    Also adds tpad safety net in FFmpeg in case the concat comes up short.
    """
    buffered = target_duration + 3.0   # generous overshoot
    clips_needed: list[tuple[Path, float]] = []
    total = 0.0
    pool = list(portrait_clips)

    # Loop the pool enough times to guarantee coverage (minimum 3 full passes)
    min_passes = max(3, math.ceil(buffered / max(sum(_safe_dur(c) for c in pool), 0.1)))
    extended_pool = pool * min_passes

    for clip in extended_pool:
        if total >= buffered:
            break
        dur = min(_safe_dur(clip), buffered - total)
        clips_needed.append((clip, dur))
        total += dur

    # Build concat file
    concat_file = out.parent / "concat.txt"
    with open(concat_file, "w") as fh:
        for clip, dur in clips_needed:
            fh.write(f"file '{clip.as_posix()}'\n")
            fh.write(f"duration {dur:.3f}\n")
        # Repeat last clip without duration — FFmpeg always has a final frame
        fh.write(f"file '{clips_needed[-1][0].as_posix()}'\n")

    _run_ff(
        [
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            # tpad clones last frame for up to 5s — prevents video freeze if concat comes up short
            "-vf", f"tpad=stop_mode=clone:stop_duration=5",
            "-t", f"{target_duration:.3f}",   # hard trim to exact target
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        label="broll-concat",
    )
    concat_file.unlink(missing_ok=True)


def _safe_dur(clip: Path) -> float:
    """Get clip duration safely, returning 2.5s as fallback."""
    try:
        return _video_duration(clip)
    except Exception:
        return 2.5


import math  # noqa: E402 — used in _assemble_broll above


# ── Audio mix with Hook SFX + Inline SFX ──────────────────────────────────

def _mix_audio(
    silent_video: Path,
    narration: Path,
    music: Path,
    hook_sfx: Path,
    sfx_cues: list[SfxCue],
    sfx_files: dict[str, Path],
    total_duration: float,
    out: Path,
) -> None:
    """
    Combine the silent video with:
      - Narration at 100%
      - Background music at MUSIC_VOLUME (10%)
      - Hook SFX (boom+whoosh) at t=0 with HOOK_SFX_VOLUME
      - Inline SFX cues at their timestamps with SFX_VOLUME

    The hook SFX plays on FRAME 1 — the jarring pattern interrupt that
    stops the thumb scroll before the viewer has time to decide to skip.
    """
    music_vol    = config.MUSIC_VOLUME
    hook_vol     = config.HOOK_SFX_VOLUME
    sfx_vol      = config.SFX_VOLUME

    # Build filter graph
    # Inputs: [0]=silent video, [1]=narration, [2]=music, [3]=hook_sfx, [4+]=inline sfx
    inputs = [
        "-i", str(silent_video),
        "-i", str(narration),
        "-stream_loop", "-1", "-i", str(music),
        "-i", str(hook_sfx),
    ]

    # Collect inline SFX inputs
    inline_inputs: list[tuple[int, SfxCue]] = []
    input_idx = 4
    for cue in sfx_cues:
        sfx_path = sfx_files.get(cue["sfx_type"])
        if sfx_path and sfx_path.exists():
            inputs += ["-i", str(sfx_path)]
            inline_inputs.append((input_idx, cue))
            input_idx += 1

    # Build the filter graph
    filter_parts: list[str] = []

    # Clone last video frame to prevent black screen if video ends before audio
    filter_parts.append(f"[0:v]tpad=stop_mode=clone:stop_duration=5[vpad]")

    # Narration: full volume + pad to total duration
    filter_parts.append(f"[1:a]volume=1.0,apad=whole_dur={total_duration:.3f}[narr]")

    # Music: loop, trim, quiet
    filter_parts.append(
        f"[2:a]volume={music_vol},atrim=0:{total_duration:.3f},"
        f"asetpts=PTS-STARTPTS[mus]"
    )

    # Hook SFX: plays at t=0, loud
    filter_parts.append(f"[3:a]volume={hook_vol},adelay=0:all=1[hook]")

    # Inline SFX: each delayed to its timestamp
    sfx_labels: list[str] = ["narr", "mus", "hook"]
    for out_idx, (inp_idx, cue) in enumerate(inline_inputs):
        delay_ms = int(cue["time_s"] * 1000)
        label = f"sfx{out_idx}"
        filter_parts.append(
            f"[{inp_idx}:a]volume={sfx_vol},adelay={delay_ms}:all=1[{label}]"
        )
        sfx_labels.append(label)

    # Mix all audio streams
    n_inputs = len(sfx_labels)
    all_labels = "".join(f"[{lbl}]" for lbl in sfx_labels)
    filter_parts.append(
        f"{all_labels}amix=inputs={n_inputs}:duration=longest:"
        f"dropout_transition=1:normalize=0[audio]"
    )

    filter_graph = ";".join(filter_parts)

    _run_ff(
        inputs + [
            "-filter_complex", filter_graph,
            "-map", "[vpad]",
            "-map", "[audio]",
            "-t", f"{total_duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            str(out),
        ],
        label="audio-mix",
    )


# ── Caption burn-in ────────────────────────────────────────────────────────

def _burn_captions(src: Path, ass: Path, out: Path) -> None:
    """
    Burn Hormozi-style ASS captions into the video.
    Center-screen, 88px bold yellow, 1-2 words per cue.
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

    New timeline (starts instantly — NO intro card, NO fade-in):

      t=0                                    t=narration_duration
      |──── b-roll (clips every 2–3s) ────|   video = audio length
      |BOOM|                                   hook SFX on frame 1
      [narration + music + inline SFX]         full audio track
                              |──outro──|      CTA overlay (last 3s)
      |── Hormozi captions (center) ──────|   1-2 words, yellow, 88px
    """
    log.info("═══ Video Engine: assembling final video ═══")

    narration_duration = voice["duration"]
    total_duration     = min(narration_duration, config.MAX_VIDEO_DURATION)
    broll_duration     = total_duration

    # ── Step 1: Convert clips to portrait (max 2.5s each) ──────────────────
    log.info("Step 1/5 — Converting clips to portrait 1080×1920 (max 2.5s each)…")
    portrait_clips: list[Path] = []
    for i, clip in enumerate(assets["video_clips"]):
        dst = run_dir / f"portrait_{i:02d}.mp4"
        clip_dur = min(_safe_dur(clip), config.CLIP_MAX_DURATION)
        pan = i % 3
        _to_portrait(clip, dst, clip_dur, pan_direction=pan)
        portrait_clips.append(dst)

    # ── Step 2: Assemble b-roll (loop-safe, guaranteed coverage) ────────────
    log.info("Step 2/5 — Assembling b-roll (loop-guaranteed)…")
    broll_path = run_dir / "broll.mp4"
    _assemble_broll(portrait_clips, broll_duration, broll_path)

    # ── Step 3: Render CTA card only (NO intro card) ─────────────────────────
    log.info("Step 3/5 — Rendering CTA card (no intro card)…")
    outro_png = run_dir / "outro_card.png"
    _render_cta_card(
        text="FOLLOW FOR MORE",
        sub_text=script["cta"],
        dest=outro_png,
    )
    silent_video = run_dir / "silent.mp4"
    _overlay_cta(broll_path, outro_png, total_duration, silent_video)

    # ── Step 4: Mix audio (narration + music + hook SFX + inline SFX) ───────
    log.info("Step 4/5 — Mixing audio (narration + music + SFX)…")
    mixed_video = run_dir / "mixed.mp4"

    # Rebuild inline SFX with actual voice duration for accurate timing
    from engines.asset_engine import build_inline_sfx_cues
    sfx_tags = script.get("sfx_tags", [])
    narration_text = script.get("narration", "")
    sfx_files, sfx_cues = build_inline_sfx_cues(
        narration=narration_text,
        voice_duration=narration_duration,
        sfx_tags=sfx_tags,
        run_dir=run_dir,
    )

    _mix_audio(
        silent_video=silent_video,
        narration=voice["audio_file"],
        music=assets["music_file"],
        hook_sfx=assets["hook_sfx_file"],
        sfx_cues=sfx_cues,
        sfx_files=sfx_files,
        total_duration=total_duration,
        out=mixed_video,
    )

    # ── Step 5: Burn Hormozi captions ────────────────────────────────────────
    log.info("Step 5/5 — Burning Hormozi captions (center-screen, 1–2 words)…")
    final_video = run_dir / "final.mp4"
    _burn_captions(mixed_video, voice["ass_file"], final_video)

    actual_duration = _video_duration(final_video)
    log.info(f"✅ Video assembled: {actual_duration:.1f}s → {final_video.name}")

    return VideoResult(video_file=final_video, duration=actual_duration)
