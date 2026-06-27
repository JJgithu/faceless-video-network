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
    duration when we have no word-level timing (e.g. ElevenLabs standard convert).
    Starts at CAPTION_OFFSET_MS to compensate for the brief silence ElevenLabs
    adds before speech begins, so captions don't appear before the voice.
    """
    OFFSET_MS = 300   # ms before first caption appears (voice latency compensation)
    words = narration.upper().split()
    if not words:
        return ""

    effective_ms = max((duration * 1000) - OFFSET_MS, 1)
    ms_per_word = effective_ms / len(words)
    timings = [
        {
            "word": w,
            "start_ms": int(OFFSET_MS + i * ms_per_word),
            "end_ms":   int(OFFSET_MS + (i + 1) * ms_per_word),
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
    Tries convert_with_timestamps first (gives real word timings for subtitle sync).
    Falls back to standard convert if timestamps endpoint fails.
    Raises on quota-exceeded or auth errors — no silent fallback.
    """
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings
    import base64

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
    vs = VoiceSettings(
        stability=config.ELEVENLABS_STABILITY,
        similarity_boost=config.ELEVENLABS_SIMILARITY,
        style=config.ELEVENLABS_STYLE,
        use_speaker_boost=config.ELEVENLABS_SPEAKER_BOOST,
    )

    # ── Try with timestamps (real word-level timing for subtitle sync) ──────
    try:
        resp = client.text_to_speech.convert_with_timestamps(
            voice_id=voice_id,
            text=text,
            model_id=config.ELEVENLABS_MODEL,
            voice_settings=vs,
        )
        audio_bytes = base64.b64decode(resp.audio_base64)
        audio_path.write_bytes(audio_bytes)

        alignment = getattr(resp, "alignment", None)
        if alignment and getattr(alignment, "characters", None):
            word_timings = _chars_to_word_timings(
                alignment.characters,
                alignment.character_start_times_seconds,
                alignment.character_end_times_seconds,
            )
            log.info(f"ElevenLabs: audio + {len(word_timings)} word timings (timestamp API)")
            return word_timings

        log.info("ElevenLabs: audio written (timestamp API returned no alignment)")
        return []

    except Exception as ts_exc:
        log.warning(f"ElevenLabs with_timestamps failed ({ts_exc}), trying standard convert")

    # ── Fallback: standard streaming convert ────────────────────────────────
    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=config.ELEVENLABS_MODEL,
        voice_settings=vs,
    )
    with open(audio_path, "wb") as fh:
        for chunk in audio_generator:
            if chunk:
                fh.write(chunk)

    log.info(f"ElevenLabs: audio written (standard convert, no word timings)")
    return []


def _chars_to_word_timings(
    chars: list[str],
    starts: list[float],
    ends: list[float],
) -> list[dict]:
    """Convert ElevenLabs character-level alignment to word-level timings."""
    word_timings: list[dict] = []
    current_word = ""
    word_start_s: float | None = None

    for ch, t_start, t_end in zip(chars, starts, ends):
        if ch in (" ", "\n", "\t"):
            if current_word:
                word_timings.append({
                    "word": current_word,
                    "start_ms": int(word_start_s * 1000),
                    "end_ms":   int(t_start * 1000),
                })
            current_word = ""
            word_start_s = None
        else:
            if not current_word:
                word_start_s = t_start
            current_word += ch

    if current_word and word_start_s is not None:
        word_timings.append({
            "word": current_word,
            "start_ms": int(word_start_s * 1000),
            "end_ms":   int(ends[-1] * 1000) if ends else int(word_start_s * 1000) + 500,
        })

    return word_timings


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

    # ── Require ElevenLabs (quality policy — no fallback TTS) ──────────────
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ElevenLabs API key not configured. "
            "Set ELEVENLABS_API_KEY in GitHub Secrets to enable video production."
        )

    voice_id = niche.get("elevenlabs_voice_id") or "pNInz6obpgDQGcFmaJgB"
    log.info(f"Using ElevenLabs voice: {voice_id}")
    try:
        word_timings = _elevenlabs_generate(clean_text, voice_id, audio_path)
        engine_used = "elevenlabs"
    except Exception as exc:
        # Quota exceeded, auth error, etc. — abort immediately, no fallback
        raise RuntimeError(
            f"ElevenLabs failed: {exc}\n"
            "Video production aborted (quality policy: ElevenLabs voice required)."
        ) from exc

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
