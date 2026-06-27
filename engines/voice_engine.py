"""
engines/voice_engine.py
─────────────────────────────────────────────────────────────────────────────
The Voice Engine — converts narration script to a hyper-realistic voiceover.

PRIMARY:  ElevenLabs API (eleven_turbo_v2_5) — different voice per niche channel
FALLBACK: NONE — if ElevenLabs quota is exhausted, production STOPS.
          We never use a fallback voice. ElevenLabs or nothing.

Quota Guard:
  If ElevenLabs returns a 429 or any quota/billing error, this engine raises
  ElevenLabsQuotaError, which propagates to main.py and aborts the run cleanly.

Subtitle Sync:
  Uses ElevenLabs word-level alignment (with_timestamps=True) to get
  real character/word-level timestamps for frame-accurate subtitles.
  Falls back to evenly-spaced approximation only if the API doesn't return timing.
"""

import re
import subprocess
from pathlib import Path
from typing import TypedDict

import config
from utils.logger import get_logger

log = get_logger(__name__)


# ── Custom Exceptions ──────────────────────────────────────────────────────

class ElevenLabsQuotaError(RuntimeError):
    """Raised when ElevenLabs API returns a quota/billing limit error."""
    pass


class ElevenLabsVoiceError(RuntimeError):
    """Raised for any non-quota ElevenLabs API error."""
    pass


class VoiceResult(TypedDict):
    audio_file: Path     # .mp3 narration audio
    ass_file: Path       # .ass subtitle file (kinetic Hormozi-style captions)
    duration: float      # audio duration in seconds
    engine: str          # always "elevenlabs" (no fallback)


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


# ── ASS subtitle generation — Hormozi style ────────────────────────────────

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
    Build Hormozi-style ASS subtitle file from word-level timing data.

    Design principles:
      - 1-2 words per cue: forces eyes to keep reading, creates dopamine loop
      - Center-screen (Alignment=5): locks gaze in middle of frame
      - Large bold yellow font (88px): unmissable, premium feel
      - Fast snap-in (80ms fade): energetic, not lazy
      - Black outline + shadow: readable on any background
    """
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.VIDEO_WIDTH}
PlayResY: {config.VIDEO_HEIGHT}
Collisions: Normal
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{config.CAPTION_FONT_SIZE},{config.CAPTION_PRIMARY_COLOR},&H000000FF,{config.CAPTION_OUTLINE_COLOR},{config.CAPTION_BACK_COLOR},1,0,0,0,100,100,3,0,1,4,2,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [ass_header]

    for i in range(0, len(word_timings), words_per_cue):
        group = word_timings[i : i + words_per_cue]
        start_ms = group[0]["start_ms"]
        end_ms   = group[-1]["end_ms"]

        # Ensure minimum cue duration (100ms) to avoid invisible flashes
        if end_ms - start_ms < 100:
            end_ms = start_ms + 100

        text = " ".join(w["word"] for w in group).upper()  # ALL CAPS — Hormozi standard

        start_ass = _ms_to_ass_time(start_ms)
        end_ass   = _ms_to_ass_time(end_ms)

        # \fad(fade_in_ms, fade_out_ms) — fast snap-in, not a slow dissolve
        # \b1 — bold (reinforced at cue level for safety)
        tagged_text = f"{{\\fad({fade_ms},{fade_ms})\\b1}}{text}"
        lines.append(
            f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{tagged_text}"
        )

    return "\n".join(lines)


def _build_simple_ass(narration: str, duration: float) -> str:
    """
    Fallback: build Hormozi ASS captions by evenly distributing words across
    the audio duration when we have no word-level timing.
    Used only if ElevenLabs alignment endpoint fails to return timestamps.
    """
    words = narration.upper().split()
    if not words:
        return ""

    ms_per_word = (duration * 1000) / len(words)
    timings = [
        {
            "word": w,
            "start_ms": int(i * ms_per_word),
            "end_ms":   int((i + 1) * ms_per_word),
        }
        for i, w in enumerate(words)
    ]
    return _build_ass_from_words(timings)


# ── ElevenLabs voice generation ────────────────────────────────────────────

def _is_quota_error(exc: Exception) -> bool:
    """
    Detect whether an exception is an ElevenLabs quota / billing limit error.
    Checks HTTP status codes and common error message substrings.
    """
    err_str = str(exc).lower()
    quota_signals = [
        "quota", "limit exceeded", "insufficient_credits",
        "rate limit", "429", "402", "billing", "credit",
        "character limit", "monthly limit",
    ]
    return any(signal in err_str for signal in quota_signals)


def _elevenlabs_generate(
    text: str,
    voice_id: str,
    audio_path: Path,
) -> list[dict]:
    """
    Generate voice via ElevenLabs API with word-level alignment timestamps.

    Uses the `with_timestamps` streaming endpoint to get character-level
    alignment data, which is converted to word-level timing for subtitle sync.

    Raises:
        ElevenLabsQuotaError: if quota/billing limit is hit → STOPS production
        ElevenLabsVoiceError: for any other API error
    """
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings
    except ImportError as exc:
        raise ElevenLabsVoiceError(f"elevenlabs package not installed: {exc}")

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
    word_timings: list[dict] = []

    try:
        # Try the alignment endpoint first (returns real word timestamps)
        response = client.text_to_speech.convert_with_timestamps(
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

        # Write audio bytes
        with open(audio_path, "wb") as fh:
            if hasattr(response, "audio"):
                # Single response object with audio + alignment
                fh.write(response.audio)
                alignment = getattr(response, "alignment", None) or getattr(response, "normalized_alignment", None)
                if alignment:
                    word_timings = _parse_alignment(alignment)
            else:
                # Streaming response — collect chunks
                for chunk in response:
                    if hasattr(chunk, "audio") and chunk.audio:
                        fh.write(chunk.audio)
                    if hasattr(chunk, "alignment") and chunk.alignment:
                        word_timings.extend(_parse_alignment(chunk.alignment))

        log.info(f"ElevenLabs (aligned): {len(word_timings)} word timestamps → {audio_path.name}")

    except Exception as exc:
        # Check for quota error FIRST — this must propagate up to stop production
        if _is_quota_error(exc):
            raise ElevenLabsQuotaError(
                f"ElevenLabs quota exhausted: {exc}. "
                "Stopping video production — no fallback TTS will be used."
            )

        # For non-quota errors: log and try the standard (non-aligned) endpoint
        log.warning(f"ElevenLabs aligned endpoint failed ({exc}), falling back to standard endpoint")
        word_timings = _elevenlabs_standard(text, voice_id, client, audio_path)

    return word_timings


def _elevenlabs_standard(
    text: str,
    voice_id: str,
    client,
    audio_path: Path,
) -> list[dict]:
    """
    Standard ElevenLabs endpoint (no alignment data).
    Returns empty list — captions will use evenly-spaced fallback.
    Raises ElevenLabsQuotaError if quota is hit here too.
    """
    from elevenlabs import VoiceSettings

    try:
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

        log.info(f"ElevenLabs (standard, no alignment): audio → {audio_path.name}")
        return []   # No word timings; captions use evenly-spaced fallback

    except Exception as exc:
        if _is_quota_error(exc):
            raise ElevenLabsQuotaError(
                f"ElevenLabs quota exhausted: {exc}. "
                "Stopping video production — no fallback TTS will be used."
            )
        raise ElevenLabsVoiceError(f"ElevenLabs standard endpoint failed: {exc}")


def _parse_alignment(alignment) -> list[dict]:
    """
    Parse ElevenLabs alignment object into word-timing dicts.

    ElevenLabs alignment has two formats depending on SDK version:
      Format A: .characters[], .character_start_times_seconds[], .character_end_times_seconds[]
      Format B: list of {character, start_time, end_time} dicts

    We reconstruct word boundaries by grouping characters until a space.
    """
    word_timings: list[dict] = []
    try:
        # Format A: attribute-based (most common in elevenlabs SDK >= 1.0)
        if hasattr(alignment, "characters"):
            chars     = list(alignment.characters)
            starts    = list(alignment.character_start_times_seconds)
            ends      = list(alignment.character_end_times_seconds)

            current_word = ""
            word_start   = 0.0
            word_end     = 0.0

            for char, start, end in zip(chars, starts, ends):
                if char == " " or char == "\n":
                    if current_word.strip():
                        word_timings.append({
                            "word":     current_word.strip(),
                            "start_ms": int(word_start * 1000),
                            "end_ms":   int(word_end * 1000),
                        })
                    current_word = ""
                else:
                    if not current_word:
                        word_start = start
                    current_word += char
                    word_end = end

            if current_word.strip():
                word_timings.append({
                    "word":     current_word.strip(),
                    "start_ms": int(word_start * 1000),
                    "end_ms":   int(word_end * 1000),
                })

        # Format B: list of dicts
        elif isinstance(alignment, list):
            current_word = ""
            word_start   = 0.0
            word_end     = 0.0
            for item in alignment:
                char  = item.get("character", "")
                start = item.get("start_time", 0.0)
                end   = item.get("end_time", 0.0)
                if char == " " or char == "\n":
                    if current_word.strip():
                        word_timings.append({
                            "word":     current_word.strip(),
                            "start_ms": int(word_start * 1000),
                            "end_ms":   int(word_end * 1000),
                        })
                    current_word = ""
                else:
                    if not current_word:
                        word_start = start
                    current_word += char
                    word_end = end
            if current_word.strip():
                word_timings.append({
                    "word":     current_word.strip(),
                    "start_ms": int(word_start * 1000),
                    "end_ms":   int(word_end * 1000),
                })

    except Exception as exc:
        log.warning(f"Alignment parsing failed ({exc}) — will use evenly-spaced fallback")
        return []

    log.info(f"Parsed {len(word_timings)} word timestamps from alignment data")
    return word_timings


# ── Public API ─────────────────────────────────────────────────────────────

def generate_voiceover(narration: str, run_dir: Path) -> VoiceResult:
    """
    Generate the narration audio and matching kinetic Hormozi-style ASS caption file.

    ONLY uses ElevenLabs. If quota is exhausted, raises ElevenLabsQuotaError
    and production stops immediately — no fallback TTS.

    Raises:
        ElevenLabsQuotaError: when ElevenLabs has no remaining quota
        ElevenLabsVoiceError: for other ElevenLabs failures
        RuntimeError: if ELEVENLABS_API_KEY is not set
    """
    niche = config.get_niche()
    log.info(f"═══ Voice Engine: [{niche['display_name']}] synthesising narration ═══")

    # Hard guard: no key = no production
    if not config.ELEVENLABS_API_KEY:
        raise ElevenLabsQuotaError(
            "ELEVENLABS_API_KEY is not set. "
            "Cannot produce video without ElevenLabs voice. "
            "Set the secret and retry."
        )

    audio_path = run_dir / "narration.mp3"
    ass_path   = run_dir / "captions.ass"
    clean_text = _clean_text(narration)

    # Use 'or' so empty string from unset GitHub Secret also triggers the default
    voice_id = niche.get("elevenlabs_voice_id") or "pNInz6obpgDQGcFmaJgB"
    log.info(f"Using ElevenLabs voice: {voice_id}")

    # This will raise ElevenLabsQuotaError if quota is hit — intentionally uncaught
    word_timings = _elevenlabs_generate(clean_text, voice_id, audio_path)

    duration = _get_audio_duration(audio_path)
    log.info(f"Audio duration: {duration:.1f}s")

    # ── Build Hormozi kinetic captions ──────────────────────────────────────
    if word_timings:
        log.info(f"Building aligned captions from {len(word_timings)} word timestamps")
        ass_content = _build_ass_from_words(word_timings)
    else:
        log.warning("No word timing data — using evenly-spaced caption fallback")
        ass_content = _build_simple_ass(clean_text, duration)

    ass_path.write_text(ass_content, encoding="utf-8")

    log.info(
        f"Voice done | engine=elevenlabs | "
        f"duration={duration:.1f}s | "
        f"word_timestamps={len(word_timings)} | "
        f"captions={ass_path.name}"
    )

    return VoiceResult(
        audio_file=audio_path,
        ass_file=ass_path,
        duration=duration,
        engine="elevenlabs",
    )
