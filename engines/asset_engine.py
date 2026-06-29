"""
engines/asset_engine.py
─────────────────────────────────────────────────────────────────────────────
Downloads all media assets needed to assemble the video:
  1. Stock video clips — searched on Pexels using script keywords
  2. Background music  — procedurally generated ambient track (no API needed)
  3. Sound Effects     — procedurally generated SFX (no external files needed)
     • Hook SFX: jarring boom+whoosh played on frame 1 (pattern interrupt)
     • Inline SFX: creepy/thunder/heartbeat cues timed to narration sentences

All SFX are synthesised via numpy — zero external dependencies,
works offline on GitHub Actions.
"""

import math
import random
import struct
import wave
from pathlib import Path
from typing import TypedDict

import numpy as np
import requests

import config
from engines.script_engine import Script
from engines.trend_engine import Topic
from utils.logger import get_logger

log = get_logger(__name__)

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PEXELS_HEADERS = {"Authorization": config.PEXELS_API_KEY}

SAMPLE_RATE = 44100


class SfxCue(TypedDict):
    time_s: float    # when to play (seconds from video start)
    sfx_type: str    # which SFX to play
    volume: float    # mix volume


class Assets(TypedDict):
    video_clips:   list[Path]    # Downloaded .mp4 clip paths
    music_file:    Path          # Background music .wav path
    hook_sfx_file: Path          # Frame-1 jarring pattern-interrupt SFX
    sfx_cues:      list[SfxCue] # Inline SFX events timed to narration


# ── Pexels ─────────────────────────────────────────────────────────────────

def _search_pexels_videos(query: str, per_page: int = 10) -> list[dict]:
    """Search Pexels for videos matching the query. Returns raw video objects."""
    params = {
        "query": query,
        "per_page": per_page,
        "size": "medium",        # medium = ≤1080p, faster download
        "orientation": "portrait",
    }
    try:
        resp = requests.get(PEXELS_VIDEO_URL, headers=PEXELS_HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
        log.debug(f"Pexels '{query}': {len(videos)} results")
        return videos
    except Exception as exc:
        log.warning(f"Pexels search failed for '{query}': {exc}")
        return []


def _best_video_file(video: dict) -> str | None:
    """Pick the best quality MP4 file URL from a Pexels video object."""
    files = video.get("video_files", [])
    # Prefer HD portrait files; fall back to any MP4
    hd_files = [f for f in files if f.get("quality") in ("hd", "sd") and "mp4" in f.get("file_type", "")]
    if hd_files:
        # Pick closest to 1080×1920 or just the largest
        hd_files.sort(key=lambda f: f.get("height", 0), reverse=True)
        return hd_files[0]["link"]
    mp4_files = [f for f in files if "mp4" in f.get("file_type", "")]
    return mp4_files[0]["link"] if mp4_files else None


def _download_clip(url: str, dest: Path) -> bool:
    """Stream-download a video clip to dest. Returns True on success."""
    try:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        size_mb = dest.stat().st_size / 1_048_576
        log.debug(f"Downloaded {dest.name} ({size_mb:.1f} MB)")
        return True
    except Exception as exc:
        log.warning(f"Clip download failed: {exc}")
        if dest.exists():
            dest.unlink()
        return False


def download_video_clips(keywords: list[str], run_dir: Path) -> list[Path]:
    """
    Search Pexels with each keyword, collect candidate clips, download the best N.
    Downloads more clips (PEXELS_CLIPS_TARGET=10) to support fast 2–3s cuts.
    Falls back to broader queries if specific ones yield nothing.
    """
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    candidates: list[dict] = []

    # Try specific keywords first — use more keywords for variety
    for kw in keywords[:5]:
        results = _search_pexels_videos(kw, per_page=8)
        candidates.extend(results)

    # Fallback: use generic visually-appealing queries
    if len(candidates) < config.PEXELS_CLIPS_TARGET:
        for fallback in ["viral news", "trending world", "technology future", "dramatic sky", "city night"]:
            candidates.extend(_search_pexels_videos(fallback, per_page=5))

    # Deduplicate by video ID and shuffle for variety
    seen_ids: set[int] = set()
    unique: list[dict] = []
    for v in candidates:
        if v["id"] not in seen_ids:
            seen_ids.add(v["id"])
            unique.append(v)
    random.shuffle(unique)

    downloaded: list[Path] = []
    for i, video in enumerate(unique):
        if len(downloaded) >= config.PEXELS_CLIPS_TARGET:
            break
        url = _best_video_file(video)
        if not url:
            continue
        dest = clips_dir / f"clip_{i:02d}.mp4"
        if _download_clip(url, dest):
            downloaded.append(dest)

    log.info(f"Asset Engine: {len(downloaded)} clips downloaded")

    if not downloaded:
        raise RuntimeError("No video clips could be downloaded from Pexels.")

    return downloaded


# ── Background Music ────────────────────────────────────────────────────────

def generate_ambient_music(duration: float, run_dir: Path) -> Path:
    """
    Procedurally generate an atmospheric ambient music track using numpy.
    No external API or music file needed — works offline on GitHub Actions.

    The track uses layered sine waves tuned to an A minor chord with subtle
    vibrato and a soft fade-in/out envelope. Kept at 10% mix volume.
    """
    music_path = run_dir / "background_music.wav"

    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    # A minor chord: A3 + C4 + E4 + G4 (soft pad voicing)
    chord_freqs = [220.0, 261.63, 329.63, 392.0]
    # Add subtle octave layering
    bass_freqs = [110.0, 130.81]

    audio = np.zeros(n, dtype=np.float32)

    # Chord pad — with soft vibrato (0.3 Hz, ±2 Hz depth)
    vibrato = 2.0 * np.sin(2 * np.pi * 0.3 * t)
    for freq in chord_freqs:
        wave_data = np.sin(2 * np.pi * (freq + vibrato) * t)
        envelope = 1 - np.exp(-3 * t)
        audio += 0.12 * wave_data * envelope

    # Bass sub-layer
    for freq in bass_freqs:
        audio += 0.06 * np.sin(2 * np.pi * freq * t) * np.tanh(t * 2)

    # Fade in (0.5s) and fade out (last 2s)
    fade_in  = np.minimum(t / 0.5, 1.0)
    fade_out = np.minimum((duration - t) / 2.0, 1.0)
    audio *= fade_in * fade_out

    # Normalise to 25% amplitude (quiet background)
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.25

    _write_wav(audio, music_path)
    log.info(f"Ambient music generated: {duration:.1f}s → {music_path.name}")
    return music_path


# ── SFX Synthesiser ─────────────────────────────────────────────────────────

def _write_wav(audio: np.ndarray, path: Path) -> None:
    """Write a float32 numpy array as 16-bit mono WAV."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak  # normalise to 0 dBFS
    audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())


def _sfx_boom(duration: float = 0.8) -> np.ndarray:
    """
    Heavy cinematic boom — sub-bass thud with fast attack, slow decay.
    Instantly signals 'pay attention' to the viewer's nervous system.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    # Sub-bass punch: 60 Hz fundamental + 120 Hz harmonic
    boom = (
        0.7 * np.sin(2 * np.pi * 60 * t) +
        0.3 * np.sin(2 * np.pi * 120 * t) +
        0.15 * np.sin(2 * np.pi * 30 * t)   # rumble sub
    )
    # Pitch drop: frequency descends from 90 Hz → 40 Hz (classic cinematic boom)
    freq_sweep = 90 * np.exp(-3.0 * t) + 40
    boom += 0.4 * np.sin(2 * np.pi * np.cumsum(freq_sweep / SAMPLE_RATE))

    # Envelope: instant attack (1ms), exponential decay
    env = np.exp(-4.0 * t)
    env[:int(SAMPLE_RATE * 0.001)] = np.linspace(0, 1, int(SAMPLE_RATE * 0.001))
    return boom * env


def _sfx_whoosh(duration: float = 0.5) -> np.ndarray:
    """
    Fast air-cutting whoosh — filtered white noise with frequency sweep.
    Used to punctuate the boom for a cinematic 1-2 combo.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    noise = np.random.randn(n).astype(np.float32)
    # Frequency sweep: 2000 Hz → 200 Hz (falling whoosh)
    freq = 2000 * np.exp(-4 * t) + 200
    modulator = np.sin(2 * np.pi * np.cumsum(freq / SAMPLE_RATE))
    whoosh = noise * modulator * 0.5

    # Simple lowpass via convolution
    kernel_size = 64
    kernel = np.ones(kernel_size, dtype=np.float32) / kernel_size
    whoosh = np.convolve(whoosh, kernel, mode="same")

    # Envelope: fast rise, slow fall
    env = np.exp(-5.0 * t) * (1 - np.exp(-80.0 * t))
    return whoosh * env * 2.0


def _sfx_heartbeat(duration: float = 1.2) -> np.ndarray:
    """
    Organic heartbeat — two-pulse thud (lub-dub) with realistic timing.
    Great under body science / medical horror content.
    """
    n = int(SAMPLE_RATE * duration)
    audio = np.zeros(n, dtype=np.float32)

    def _pulse(t_arr: np.ndarray, start: float, freq: float = 80.0) -> np.ndarray:
        pulse_dur = 0.12
        mask = (t_arr >= start) & (t_arr < start + pulse_dur)
        if not np.any(mask):
            return np.zeros_like(t_arr)
        seg = t_arr[mask] - start
        env = np.sin(np.pi * seg / pulse_dur) ** 2
        out = np.zeros_like(t_arr)
        out[mask] = env * np.sin(2 * np.pi * freq * seg)
        return out

    t = np.linspace(0, duration, n, dtype=np.float32)
    audio += _pulse(t, 0.0, 80)    # LUB
    audio += _pulse(t, 0.18, 100)  # DUB (higher pitch, shorter)
    return audio


def _sfx_creepy_crawl(duration: float = 1.5) -> np.ndarray:
    """
    Unsettling insectoid scraping — multi-layer low-frequency noise with
    irregular amplitude modulation. Plays under spider/creature references.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    # Layered noise with irregular tremolo
    noise = np.random.randn(n).astype(np.float32) * 0.3
    tremolo_rate = 12.0 + 5.0 * np.sin(2 * np.pi * 0.7 * t)  # irregular
    tremolo = 0.5 + 0.5 * np.sin(2 * np.pi * tremolo_rate * t)

    # Low-freq raspy component
    rasp_freq = 180 + 40 * np.sin(2 * np.pi * 3.0 * t)
    rasp = np.sin(2 * np.pi * np.cumsum(rasp_freq / SAMPLE_RATE)) * 0.4

    audio = (noise + rasp) * tremolo
    env = np.minimum(t / 0.1, 1.0) * np.minimum((duration - t) / 0.3, 1.0)
    return audio * env


def _sfx_deep_rumble(duration: float = 1.5) -> np.ndarray:
    """
    Ominous sub-bass rumble — low-frequency drone with slow wobble.
    Perfect for ancient ruins, deep ocean, and alternate history reveals.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    lfo = 1.0 + 0.3 * np.sin(2 * np.pi * 0.5 * t)  # 0.5 Hz wobble
    rumble = (
        np.sin(2 * np.pi * 40 * t) * 0.6 +
        np.sin(2 * np.pi * 55 * t) * 0.3 +
        np.random.randn(n).astype(np.float32) * 0.08
    ) * lfo

    env = (1 - np.exp(-5 * t)) * np.minimum((duration - t) / 0.5, 1.0)
    return rumble * env


def _sfx_water_drop(duration: float = 0.8) -> np.ndarray:
    """
    Eerie water drop — resonant ping with long underwater reverb tail.
    Perfect for deep sea content.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    # High-freq ping with fast decay
    ping_freq = 800 * np.exp(-3 * t) + 400
    ping = np.sin(2 * np.pi * np.cumsum(ping_freq / SAMPLE_RATE)) * np.exp(-6 * t)

    # Underwater reverb: delayed + decayed copies
    reverb = np.zeros(n, dtype=np.float32)
    for delay_ms in [80, 160, 280]:
        delay_samp = int(SAMPLE_RATE * delay_ms / 1000)
        decay = 0.4 ** (delay_ms / 80)
        if delay_samp < n:
            reverb[delay_samp:] += ping[:n - delay_samp] * decay

    return (ping + reverb) * 0.8


def _sfx_thunder(duration: float = 1.2) -> np.ndarray:
    """
    Dramatic thunder crack — sharp transient with rolling rumble tail.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    # Crack: band-pass noise burst
    noise = np.random.randn(n).astype(np.float32)
    crack_env = np.exp(-15 * t)
    crack = noise * crack_env * 0.8

    # Roll: low-freq noise tail
    roll_env = np.exp(-2.5 * t) * (1 - np.exp(-10 * t))
    roll_noise = np.random.randn(n).astype(np.float32) * 0.5
    # Crude lowpass on roll
    kernel = np.ones(200, dtype=np.float32) / 200
    roll = np.convolve(roll_noise, kernel, mode="same") * roll_env

    return crack + roll


def _sfx_reveal(duration: float = 0.7) -> np.ndarray:
    """
    Rising revelation sting — ascending frequency sweep with shimmer.
    Plays at the moment a shocking truth is revealed.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, dtype=np.float32)

    # Ascending sine sweep: 300 Hz → 1200 Hz
    freq = 300 + 900 * (t / duration) ** 1.5
    sweep = np.sin(2 * np.pi * np.cumsum(freq / SAMPLE_RATE))

    # Shimmer: high-freq harmonics
    shimmer = (
        0.3 * np.sin(2 * np.pi * 2400 * t) +
        0.2 * np.sin(2 * np.pi * 3600 * t)
    ) * (t / duration)

    env = (t / duration) * np.minimum((duration - t) / 0.1, 1.0)
    return (sweep * 0.7 + shimmer) * env


def _sfx_boom_whoosh(duration: float = 0.9) -> np.ndarray:
    """
    The FRAME-1 PATTERN INTERRUPT — heavy boom + instant whoosh layered together.
    This is the 'thumb-stopper': a jarring combo that jolts the viewer awake
    at the very first millisecond of the video.
    """
    n = int(SAMPLE_RATE * duration)

    boom  = _sfx_boom(min(duration, 0.8))
    whoosh = _sfx_whoosh(min(duration, 0.5))

    # Pad shorter array to match
    if len(boom) < n:
        boom = np.pad(boom, (0, n - len(boom)))
    if len(whoosh) < n:
        whoosh = np.pad(whoosh, (0, n - len(whoosh)))

    # Layer: boom at full weight, whoosh at 70%
    combo = boom[:n] * 1.0 + whoosh[:n] * 0.7
    return combo


_SFX_GENERATORS = {
    "boom":         _sfx_boom,
    "whoosh":       _sfx_whoosh,
    "heartbeat":    _sfx_heartbeat,
    "creepy_crawl": _sfx_creepy_crawl,
    "deep_rumble":  _sfx_deep_rumble,
    "water_drop":   _sfx_water_drop,
    "thunder":      _sfx_thunder,
    "reveal":       _sfx_reveal,
    "boom_whoosh":  _sfx_boom_whoosh,
}

# Keywords that trigger each SFX type (used by the inline SFX matcher)
SFX_TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "creepy_crawl": [
        "spider", "insect", "centipede", "worm", "parasite", "larvae",
        "crawl", "creature", "slither", "mite", "tick", "leech",
    ],
    "heartbeat": [
        "heart", "pulse", "blood", "alive", "beating", "survive",
        "breathe", "body", "organ", "artery", "vein", "lung",
    ],
    "water_drop": [
        "ocean", "sea", "deep", "underwater", "dive", "abyss",
        "water", "trench", "depth", "pressure", "drown", "wet",
    ],
    "thunder": [
        "struck", "lightning", "storm", "war", "battle", "explosion",
        "bomb", "collapse", "disaster", "catastrophe", "eruption",
    ],
    "deep_rumble": [
        "ancient", "buried", "hidden", "secret", "underground", "cave",
        "pyramid", "lost", "forgotten", "sealed", "vault",
    ],
    "reveal": [
        "discovered", "revealed", "uncovered", "found", "truth",
        "actually", "reality", "turns out", "secretly", "classified",
    ],
    "boom": [
        "crash", "impact", "force", "speed", "massive", "enormous",
        "destroyed", "instant", "immediately", "sudden",
    ],
}


def generate_sfx(sfx_type: str, run_dir: Path, suffix: str = "") -> Path:
    """
    Generate a single SFX WAV file of the given type.
    Returns the path to the generated WAV.
    """
    generator = _SFX_GENERATORS.get(sfx_type, _sfx_boom)
    audio = generator()
    fname = f"sfx_{sfx_type}{suffix}.wav"
    path = run_dir / fname
    _write_wav(audio, path)
    log.debug(f"SFX generated: {sfx_type} → {path.name}")
    return path


def generate_hook_sfx(run_dir: Path) -> Path:
    """
    Generate the frame-1 pattern interrupt SFX.
    This is the jarring boom+whoosh that plays on the VERY FIRST FRAME.
    Always used regardless of niche.
    """
    audio = _sfx_boom_whoosh(duration=0.9)
    path = run_dir / "sfx_hook.wav"
    _write_wav(audio, path)
    log.info(f"Hook SFX generated (boom+whoosh) → {path.name}")
    return path


def build_inline_sfx_cues(
    narration: str,
    voice_duration: float,
    sfx_tags: list[dict],    # [{sentence_index, sfx_type}] from script engine
    run_dir: Path,
) -> tuple[dict[str, Path], list[SfxCue]]:
    """
    Convert script-engine SFX tags into timed SFX cue events.

    sfx_tags come from the Gemini SFX tagging pass in script_engine.
    Each tag has a sentence_index; we map that to an approximate time_s
    by dividing the total duration evenly across sentences.

    Returns:
        sfx_files: {sfx_type -> Path} for all unique SFX types needed
        cues: list of SfxCue dicts ready for the video engine
    """
    # If no Gemini tags provided, do keyword-matching fallback
    if not sfx_tags:
        sfx_tags = _keyword_match_sfx(narration)

    sentences = [s.strip() for s in narration.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    n_sentences = max(len(sentences), 1)
    secs_per_sentence = voice_duration / n_sentences

    # Generate unique SFX files
    needed_types: set[str] = {tag["sfx_type"] for tag in sfx_tags}
    sfx_files: dict[str, Path] = {}
    for sfx_type in needed_types:
        if sfx_type in _SFX_GENERATORS:
            sfx_files[sfx_type] = generate_sfx(sfx_type, run_dir, suffix=f"_{sfx_type}")

    # Build timed cues
    cues: list[SfxCue] = []
    for tag in sfx_tags:
        idx = min(tag.get("sentence_index", 0), n_sentences - 1)
        # Offset by 1 second after the hook SFX to avoid collision
        time_s = max(1.0, idx * secs_per_sentence)
        sfx_type = tag.get("sfx_type", "boom")
        if sfx_type in sfx_files:
            cues.append(SfxCue(time_s=time_s, sfx_type=sfx_type, volume=config.SFX_VOLUME))

    log.info(f"SFX cues: {len(cues)} inline events")
    return sfx_files, cues


def _keyword_match_sfx(narration: str) -> list[dict]:
    """
    Keyword-based fallback SFX tagger when Gemini tagging is unavailable.
    Scans each sentence for trigger words and assigns the matching SFX.
    """
    sentences = [s.strip() for s in narration.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    tags = []
    for i, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        for sfx_type, keywords in SFX_TRIGGER_KEYWORDS.items():
            if any(kw in sentence_lower for kw in keywords):
                tags.append({"sentence_index": i, "sfx_type": sfx_type})
                break  # one SFX per sentence
    return tags


# ── Public API ─────────────────────────────────────────────────────────────

def gather_assets(topic: Topic, script: Script, run_dir: Path) -> Assets:
    """
    Download all assets required to build the video.
    Returns an Assets dict with local file paths including SFX.
    """
    log.info("═══ Asset Engine: gathering stock footage, music & SFX ═══")

    niche = config.get_niche()

    # ── Video clips ────────────────────────────────────────────────────────
    search_keywords = topic["keywords"] + [topic["topic"]] + niche.get("pexels_keywords", [])[:3]
    video_clips = download_video_clips(search_keywords, run_dir)

    # ── Background music ───────────────────────────────────────────────────
    music_duration = config.MAX_VIDEO_DURATION + 5
    music_file = generate_ambient_music(music_duration, run_dir)

    # ── Frame-1 hook SFX ───────────────────────────────────────────────────
    hook_sfx_file = generate_hook_sfx(run_dir)

    # ── Inline SFX cues ────────────────────────────────────────────────────
    # sfx_tags come from script engine Gemini tagging; fall back to keyword match
    sfx_tags = script.get("sfx_tags", [])
    narration = script.get("narration", "")
    # Duration unknown at asset time — use max duration as estimate
    # Video engine will refine timing after voice generation
    _sfx_files, sfx_cues = build_inline_sfx_cues(
        narration=narration,
        voice_duration=config.MAX_VIDEO_DURATION,
        sfx_tags=sfx_tags,
        run_dir=run_dir,
    )

    return Assets(
        video_clips=video_clips,
        music_file=music_file,
        hook_sfx_file=hook_sfx_file,
        sfx_cues=sfx_cues,
    )
