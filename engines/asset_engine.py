"""
engines/asset_engine.py
─────────────────────────────────────────────────────────────────────────────
Downloads all media assets needed to assemble the video:
  1. Stock video clips — searched on Pexels using script keywords
  2. Background music  — procedurally generated ambient track (no API needed)

Returns local file paths ready for the Video Engine.
"""

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


class Assets(TypedDict):
    video_clips: list[Path]   # Downloaded .mp4 clip paths
    music_file: Path          # Background music .wav path


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
    Falls back to broader queries if specific ones yield nothing.
    """
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    candidates: list[dict] = []

    # Try specific keywords first
    for kw in keywords[:3]:
        results = _search_pexels_videos(kw, per_page=8)
        candidates.extend(results)

    # Fallback: use generic visually-appealing queries
    if len(candidates) < config.PEXELS_CLIPS_TARGET:
        for fallback in ["viral news", "trending world", "technology future"]:
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
    Procedurally generate a calming ambient music track using numpy.
    No external API or music file needed — works offline on GitHub Actions.

    The track uses layered sine waves tuned to an A minor chord with subtle
    vibrato and a soft fade-in/out envelope.
    """
    music_path = run_dir / "background_music.wav"

    sample_rate = 44100
    n = int(sample_rate * duration)
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
        # Soft attack using exponential envelope
        envelope = 1 - np.exp(-3 * t)
        audio += 0.12 * wave_data * envelope

    # Bass sub-layer
    for freq in bass_freqs:
        audio += 0.06 * np.sin(2 * np.pi * freq * t) * np.tanh(t * 2)

    # Fade in (0.5s) and fade out (last 2s)
    fade_in = np.minimum(t / 0.5, 1.0)
    fade_out = np.minimum((duration - t) / 2.0, 1.0)
    audio *= fade_in * fade_out

    # Normalise to 25% amplitude (quiet background)
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.25

    # Write WAV (16-bit PCM mono)
    audio_int16 = (audio * 32767).astype(np.int16)
    with wave.open(str(music_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())

    log.info(f"Ambient music generated: {duration:.1f}s → {music_path.name}")
    return music_path


# ── Public API ─────────────────────────────────────────────────────────────

def gather_assets(topic: Topic, script: Script, run_dir: Path) -> Assets:
    """
    Download all assets required to build the video.
    Returns an Assets dict with local file paths.
    """
    log.info("═══ Asset Engine: gathering stock footage & music ═══")

    # Use keywords from the topic + extra terms for better Pexels results
    search_keywords = topic["keywords"] + [topic["topic"]]

    video_clips = download_video_clips(search_keywords, run_dir)

    # Music length = narration + intro + outro + a little buffer
    music_duration = config.MAX_VIDEO_DURATION + 5
    music_file = generate_ambient_music(music_duration, run_dir)

    return Assets(video_clips=video_clips, music_file=music_file)
