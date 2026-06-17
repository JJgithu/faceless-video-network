"""
engines/voice_engine.py
─────────────────────────────────────────────────────────────────────────────
The Voice Engine — converts narration script to a hyper-realistic voiceover.

PRIMARY:  ElevenLabs API (eleven_turbo_v2_5) — different voice per niche channel
FALLBACK: Microsoft Edge TTS (free, no API key) — if no ElevenLabs key is set

Also produces timing data used to generate kinetic ASS subtitles.
"""

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import TypedDict

import config
from utils.logger import get_logger

log = get_logger(__name__)


class VoiceResult(TypedDict):
    audio_file: Path     # .mp3 narration audio
    ass_file: Path       # .ass subtitle file (kinetic captions)
    duration: float      # audio duration in seconds
    engine: str          # "elevenlabs" or "edge_tts"


# ── Audio helpers ──────────────────────────────────────────────────────────

def _get_audio_duration(path: Path) -> float:
    """Use ffprobe to get exact audio duration."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _clean_text(text: str) -> str:
    """Strip stage directions, asterisks, and extra whitespace."""
    return re.sub(r"\[.*?\]|\*+", "", text).strip()


# ── ASS subtitle generation ────────────────────────────────────────────────

def _ms_to_ass_time(ms: int) -> str:
    """Convert milliseconds to ASS time format H:MM:SS.cc"""
    cs = ms // 10       # centiseconds
    s, cs = divmod(cs, 100)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _build_ass_from_words(
    word_timings: list[dict],   # [{"word": str, "start_ms": int, "end_ms": int}]
    words_per_cue: int = config.CAPTION_WORDS_PER_CUE,
    fade_ms: int = config.CAPTION_FADE_MS,
) -> str:
    """
    Build an ASS subtitle file from word-level timing data.

    Uses fade-in/out tags (\fad) for the kinetic caption effect —
    each caption chunk pops in and fades out smoothly.
    """
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.VIDEO_WIDTH}
PlayResY: {config.VIDEO_HEIGHT}
Collisions: Normal
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,68,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,1,0,0,0,100,100,2,0,1,3,2,2,30,30,{config.CAPTION_MARGIN_BOTTOM},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [ass_header]

    for i in range(0, len(word_timings), words_per_cue):
        group = word_timings[i : i + words_per_cue]
        start_ms = group[0]["start_ms"]
        end_ms   = group[-1]["end_ms"]
        text     = " ".join(w["word"] for w in group).upper()  # ALL CAPS looks great

        start_ass = _ms_to_ass_time(start_ms)
        end_ass   = _ms_to_ass_time(end_ms)

        # \fad(fade_in_ms, fade_out_ms) — kinetic pop-in effect
        tagged_text = f"{{\\fad({fade_ms},{fade_ms})}}{text}"
        lines.append(
            f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{tagged_text}"
        )

    return "\n".join(lines)


def _build_simple_ass(narration: str, duration: float) -> str:
    """
    Fallback: build ASS captions by evenly distributing words across the audio
    duration when we have no word-level timing (edge-tts fallback path).
    """
    words = narration.upper().split()
    if not words:
        return ""

    ms_per_word = (duration * 1000) / len(words)
    timings = [
        {
            "word": w,
            "start_ms": int(i * ms_per_word),
            "end_ms": int((i + 1) * ms_per_word),
        }
        for i, w in enumerate(words)
    ]
    return _build_ass_from_words(timings)


# ── ElevenLabs voice generation ────────────────────────────────────────────

def _elevenlabs_generate(
    text: str,
    voice_id: str,
    audio_path: Path,
) -> list[dict]:
    """
    Generate voice via ElevenLabs API.
    Returns empty list (captions will use evenly-spaced fallback).
    Word-level timestamps are not used because the API changed —
    evenly-spaced captions look great anyway.
    """
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=config.ELEVENLABS_MODEL,
        voice_settings=VoiceSettings(
            stability=config.ELEVENLABS_STABILITY,
            similarity_boost=config.ELEVENLABS_SIMILARITY,
            style=config.ELEVENLABS_STYLE,
            use_speaker_boost=config.ELEVENLABS_SPEAKER_BOOST,
        ),
    )

    with open(audio_path, "wb") as fh:
        for chunk in audio_generator:
            if chunk:
                fh.write(chunk)

    log.info(f"ElevenLabs: audio written → {audio_path.name}")
    return []   # no word timings; captions use evenly-spaced fallback


# ── Edge TTS fallback ──────────────────────────────────────────────────────

async def _edge_tts_generate(text: str, audio_path: Path) -> list[dict]:
    """Fallback TTS using Microsoft Edge TTS. Returns word timings."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice=config.FALLBACK_TTS_VOICE)
    boundaries: list[dict] = []

    with open(audio_path, "wb") as fh:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset and duration are in 100-nanosecond ticks
                boundaries.append({
                    "word": chunk.get("text", ""),
                    "start_ms": chunk.get("offset", 0) // 10_000,
                    "end_ms": (chunk.get("offset", 0) + chunk.get("duration", 0)) // 10_000,
                })

    log.info(f"Edge TTS: {len(boundaries)} word boundaries, audio → {audio_path.name}")
    return boundaries


# ── Public API ─────────────────────────────────────────────────────────────

def generate_voiceover(narration: str, run_dir: Path) -> VoiceResult:
    """
    Generate the narration audio and matching kinetic ASS caption file.
    Tries ElevenLabs first; falls back to Edge TTS if no API key is set.
    """
    niche = config.get_niche()
    log.info(f"═══ Voice Engine: [{niche['display_name']}] synthesising narration ═══")

    audio_path = run_dir / "narration.mp3"
    ass_path   = run_dir / "captions.ass"
    clean_text = _clean_text(narration)

    word_timings: list[dict] = []
    engine_used = "edge_tts"

    # ── Try ElevenLabs ─────────────────────────────────────────────────────
    if config.ELEVENLABS_API_KEY:
        try:
            # Use 'or' so empty string from unset GitHub Secret also falls back to default
            voice_id = niche.get("elevenlabs_voice_id") or "pNInz6obpgDQGcFmaJgB"
            log.info(f"Using ElevenLabs voice: {voice_id}")
            word_timings = _elevenlabs_generate(clean_text, voice_id, audio_path)
            engine_used = "elevenlabs"
        except Exception as exc:
            log.warning(f"ElevenLabs failed ({exc}), falling back to Edge TTS")

    # ── Fallback: Edge TTS ─────────────────────────────────────────────────
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        log.info(f"Using Edge TTS voice: {config.FALLBACK_TTS_VOICE}")
        word_timings = asyncio.run(_edge_tts_generate(clean_text, audio_path))
        engine_used = "edge_tts"

    duration = _get_audio_duration(audio_path)

    # ── Build kinetic ASS captions ─────────────────────────────────────────
    if word_timings:
        ass_content = _build_ass_from_words(word_timings)
    else:
        log.warning("No word timings — generating evenly-spaced captions")
        ass_content = _build_simple_ass(clean_text, duration)

    ass_path.write_text(ass_content, encoding="utf-8")

    log.info(
        f"Voice done | engine={engine_used} | "
        f"duration={duration:.1f}s | captions={ass_path.name}"
    )

    return VoiceResult(
        audio_file=audio_path,
        ass_file=ass_path,
        duration=duration,
        engine=engine_used,
    )
