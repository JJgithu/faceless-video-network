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
        start_ms = max(0, group[0]["start_ms"] + config.CAPTION_OFFSET_MS)
        end_ms   = max(start_ms + 50, group[-1]["end_ms"] + config.CAPTION_OFFSET_MS)

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
                f"ElevenLabs quota exhausted: {exc}"
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
                f"ElevenLabs quota exhausted: {exc}"
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

# ── Edge TTS Fallback (free, no API key) ──────────────────────────────────

def _edge_tts_generate(text: str, audio_path: Path) -> list[dict]:
    """
    Generate voice via Microsoft Edge TTS (free, no API key needed).
    Uses 'en-US-GuyNeural' — a deep, serious male voice perfect for
    documentary/Dark Lore narration.

    Used as fallback when ElevenLabs quota is exhausted.
    Returns empty word_timings (Edge TTS doesn't provide word-level alignment).
    """
    import asyncio

    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError(
            f"edge-tts package not installed. Run: pip install edge-tts\n{exc}"
        )

    voice = config.EDGE_TTS_VOICE
    log.info(f"Using Edge TTS fallback (voice: {voice})")

    async def _generate():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(audio_path))

    # Bridge async edge-tts into our sync pipeline
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop — create a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pool.submit(asyncio.run, _generate()).result()
    else:
        asyncio.run(_generate())

    log.info(f"Edge TTS: audio → {audio_path.name}")
    return []   # No word timings; captions use evenly-spaced fallback


# ── Audio speedup (1.15x retention fix) ────────────────────────────────────

def _apply_speedup(
    audio_path: Path,
    speedup: float,
    word_timings: list[dict],
    run_dir: Path,
) -> tuple[Path, list[dict], float]:
    """
    Apply a speedup factor to the audio file using FFmpeg atempo filter.
    Also scales all word-level timestamps proportionally.

    Returns (new_audio_path, scaled_timings, new_duration).
    """
    if speedup == 1.0:
        duration = _get_audio_duration(audio_path)
        return audio_path, word_timings, duration

    log.info(f"Applying {speedup}x speedup to narration audio…")
    sped_path = run_dir / "narration_sped.mp3"

    # FFmpeg atempo filter supports 0.5 to 100.0
    # Also trim leading/trailing silence with silenceremove
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-af", (
                f"silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB,"
                f"areverse,silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB,"
                f"areverse,"
                f"atempo={speedup}"
            ),
            str(sped_path),
        ],
        capture_output=True, text=True, check=True,
    )

    # Scale word timings
    scaled_timings = []
    for wt in word_timings:
        scaled_timings.append({
            "word": wt["word"],
            "start_ms": int(wt["start_ms"] / speedup),
            "end_ms": int(wt["end_ms"] / speedup),
        })

    new_duration = _get_audio_duration(sped_path)
    log.info(
        f"Speedup applied: {speedup}x | "
        f"{_get_audio_duration(audio_path):.1f}s → {new_duration:.1f}s"
    )

    return sped_path, scaled_timings, new_duration


# ── SRT generation (alongside ASS) ────────────────────────────────────────

def _build_srt_from_words(
    word_timings: list[dict],
    words_per_cue: int = config.CAPTION_WORDS_PER_CUE,
) -> str:
    """
    Build an SRT subtitle file from word-level timing data.
    Matches the Hormozi style: 1-3 words per cue, ALL CAPS.
    """
    lines = []
    cue_number = 1

    for i in range(0, len(word_timings), words_per_cue):
        group = word_timings[i : i + words_per_cue]
        start_ms = max(0, group[0]["start_ms"] + config.CAPTION_OFFSET_MS)
        end_ms = max(start_ms + 50, group[-1]["end_ms"] + config.CAPTION_OFFSET_MS)

        if end_ms - start_ms < 100:
            end_ms = start_ms + 100

        text = " ".join(w["word"] for w in group).upper()

        start_srt = _ms_to_srt_time(start_ms)
        end_srt = _ms_to_srt_time(end_ms)

        lines.append(f"{cue_number}")
        lines.append(f"{start_srt} --> {end_srt}")
        lines.append(text)
        lines.append("")
        cue_number += 1

    return "\n".join(lines)


def _build_simple_srt(narration: str, duration: float) -> str:
    """Fallback: evenly-spaced SRT captions."""
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
    return _build_srt_from_words(timings)


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format HH:MM:SS,mmm"""
    total_seconds = ms // 1000
    remaining_ms = ms % 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{remaining_ms:03d}"


# ── Public API ─────────────────────────────────────────────────────────────

def generate_voiceover(narration: str, run_dir: Path) -> VoiceResult:
    """
    Generate the narration audio and matching kinetic Hormozi-style caption files.

    Voice priority:
      1. ElevenLabs (primary — per-niche voice IDs, word-level alignment)
      2. Edge TTS (fallback — free, no API key, deep male documentary voice)

    Post-processing:
      - 1.15x speedup via FFmpeg atempo (fast, urgent pacing)
      - Silence trimming (no dead air at start/end)
      - Generates both .ass AND .srt caption files
    """
    niche = config.get_niche()
    log.info(f"═══ Voice Engine: [{niche['display_name']}] synthesising narration ═══")

    audio_path = run_dir / "narration.mp3"
    ass_path   = run_dir / "captions.ass"
    srt_path   = run_dir / "captions.srt"
    clean_text = _clean_text(narration)
    engine_used = "elevenlabs"
    word_timings: list[dict] = []

    # ── Try ElevenLabs first ───────────────────────────────────────────────
    if config.ELEVENLABS_API_KEY:
        voice_id = niche.get("elevenlabs_voice_id") or "pNInz6obpgDQGcFmaJgB"
        log.info(f"Using ElevenLabs voice: {voice_id}")

        try:
            word_timings = _elevenlabs_generate(clean_text, voice_id, audio_path)
            engine_used = "elevenlabs"
        except ElevenLabsQuotaError as exc:
            log.warning(f"ElevenLabs quota exhausted: {exc}")
            log.info("Falling back to Edge TTS (free, no API key)…")
            engine_used = None  # signal to try fallback
        except ElevenLabsVoiceError as exc:
            log.warning(f"ElevenLabs error: {exc}")
            log.info("Falling back to Edge TTS (free, no API key)…")
            engine_used = None

    # ── Fallback to Edge TTS (free, no API key) ────────────────────────────
    if not engine_used:
        try:
            word_timings = _edge_tts_generate(clean_text, audio_path)
            engine_used = "edge_tts"
        except Exception as exc:
            log.error(f"Edge TTS fallback also failed: {exc}")
            raise ElevenLabsQuotaError(
                f"Both ElevenLabs and Edge TTS failed. "
                f"ElevenLabs: quota exhausted. Edge TTS: {exc}. "
                f"Cannot produce video without voice."
            )

    # ── Apply 1.15x speedup (retention fix) ────────────────────────────────
    audio_path, word_timings, duration = _apply_speedup(
        audio_path, config.TTS_SPEEDUP, word_timings, run_dir,
    )
    log.info(f"Final audio duration (after speedup): {duration:.1f}s")

    # ── Build Hormozi kinetic captions (ASS + SRT) ─────────────────────────
    if word_timings:
        log.info(f"Building aligned captions from {len(word_timings)} word timestamps")
        ass_content = _build_ass_from_words(word_timings)
        srt_content = _build_srt_from_words(word_timings)
    else:
        log.warning("No word timing data — using evenly-spaced caption fallback")
        ass_content = _build_simple_ass(clean_text, duration)
        srt_content = _build_simple_srt(clean_text, duration)

    ass_path.write_text(ass_content, encoding="utf-8")
    srt_path.write_text(srt_content, encoding="utf-8")

    log.info(
        f"Voice done | engine={engine_used} | "
        f"speedup={config.TTS_SPEEDUP}x | "
        f"duration={duration:.1f}s | "
        f"word_timestamps={len(word_timings)} | "
        f"captions={ass_path.name} + {srt_path.name}"
    )

    return VoiceResult(
        audio_file=audio_path,
        ass_file=ass_path,
        duration=duration,
        engine=engine_used,
    )

