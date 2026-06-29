"""
engines/publisher.py
─────────────────────────────────────────────────────────────────────────────
Uploads the finished video to YouTube Shorts and TikTok.

YouTube upload uses the official google-api-python-client with OAuth 2.0
(refresh token flow — works headlessly on GitHub Actions).

TikTok upload uses the TikTok Content Posting API v2.
"""

import json
import time
from pathlib import Path
from typing import TypedDict

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import config
from engines.script_engine import Script
from utils.logger import get_logger

log = get_logger(__name__)


class PublishResult(TypedDict):
    youtube_url: str
    youtube_id: str
    tiktok_url: str
    tiktok_id: str


# ── YouTube ────────────────────────────────────────────────────────────────

def _get_youtube_service():
    """Build an authenticated YouTube API service using stored refresh token."""
    creds = Credentials(
        token=None,
        refresh_token=config.YOUTUBE_REFRESH_TOKEN,
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=config.YOUTUBE_SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_to_youtube(video_path: Path, script: Script) -> tuple[str, str]:
    """
    Upload the video to YouTube as a Short.
    Supports both hybrid (youtube_title) and legacy (title) script formats.
    Returns (youtube_id, youtube_url).
    """
    log.info("Uploading to YouTube Shorts…")

    # Support both hybrid and legacy script title fields
    title = script.get("youtube_title") or script.get("title", "Dark Lore #shorts")

    # Build description with hashtags — #Shorts triggers Shorts distribution
    hashtag_str = " ".join(script.get("hashtags", ["#Shorts"]))
    description = f"{script.get('description', '')}\n\n{hashtag_str}"

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": [h.lstrip("#") for h in script.get("hashtags", ["#Shorts"])],
            "categoryId": config.YOUTUBE_CATEGORY_ID,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": config.YOUTUBE_PRIVACY,
            "selfDeclaredMadeForKids": config.YOUTUBE_MADE_FOR_KIDS,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,  # 5 MB chunks
    )

    service = _get_youtube_service()
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            log.debug(f"YouTube upload: {pct}%")

    video_id = response["id"]
    url = f"https://www.youtube.com/shorts/{video_id}"
    log.info(f"✅ YouTube upload complete: {url}")
    return video_id, url


# ── TikTok ─────────────────────────────────────────────────────────────────

TIKTOK_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"


def _tiktok_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.TIKTOK_ACCESS_TOKEN}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def upload_to_tiktok(video_path: Path, script: Script) -> tuple[str, str]:
    """
    Upload the video to TikTok using the Content Posting API (direct post).
    Returns (publish_id, tiktok_url).
    """
    log.info("Uploading to TikTok…")

    file_size = video_path.stat().st_size
    title = script["title"][:150]  # TikTok title limit

    # ── Step 1: Initialise upload ─────────────────────────────────────────
    init_payload = {
        "post_info": {
            "title": title,
            "privacy_level": config.TIKTOK_PRIVACY,
            "disable_comment": config.TIKTOK_DISABLE_COMMENT,
            "disable_duet": config.TIKTOK_DISABLE_DUET,
            "disable_stitch": config.TIKTOK_DISABLE_STITCH,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,  # Single chunk
            "total_chunk_count": 1,
        },
    }

    resp = requests.post(
        TIKTOK_INIT_URL,
        headers=_tiktok_headers(),
        json=init_payload,
        timeout=30,
    )
    resp.raise_for_status()
    init_data = resp.json()

    if init_data.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok init failed: {init_data}")

    publish_id = init_data["data"]["publish_id"]
    upload_url = init_data["data"]["upload_url"]
    log.debug(f"TikTok publish_id: {publish_id}")

    # ── Step 2: Upload video bytes ────────────────────────────────────────
    with open(video_path, "rb") as fh:
        video_bytes = fh.read()

    upload_resp = requests.put(
        upload_url,
        data=video_bytes,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            "Content-Length": str(file_size),
        },
        timeout=300,
    )
    upload_resp.raise_for_status()
    log.debug(f"TikTok video upload HTTP {upload_resp.status_code}")

    # ── Step 3: Poll for processing completion ────────────────────────────
    for attempt in range(12):
        time.sleep(10)
        status_resp = requests.post(
            TIKTOK_STATUS_URL,
            headers=_tiktok_headers(),
            json={"publish_id": publish_id},
            timeout=15,
        )
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status = status_data.get("data", {}).get("status", "")
        log.debug(f"TikTok status (attempt {attempt + 1}): {status}")

        if status == "PUBLISH_COMPLETE":
            tiktok_id = status_data["data"].get("publicaly_available_post_id", [publish_id])[0]
            url = f"https://www.tiktok.com/@me/video/{tiktok_id}"
            log.info(f"✅ TikTok upload complete: {url}")
            return str(tiktok_id), url

        if status in ("FAILED", "PUBLISH_FAILED"):
            raise RuntimeError(f"TikTok processing failed: {status_data}")

    # If we never got PUBLISH_COMPLETE, return publish_id as best effort
    log.warning("TikTok processing timed out — video may still be processing")
    return publish_id, f"https://www.tiktok.com/ (publish_id={publish_id})"


# ── Public API ─────────────────────────────────────────────────────────────

def publish(video_path: Path, script: Script) -> PublishResult:
    """
    Publish the video to both YouTube Shorts and TikTok.
    Returns a PublishResult with all URLs.
    """
    log.info("═══ Publisher: uploading to YouTube + TikTok ═══")

    result = PublishResult(
        youtube_url="", youtube_id="",
        tiktok_url="", tiktok_id="",
    )

    # YouTube
    try:
        yt_id, yt_url = upload_to_youtube(video_path, script)
        result["youtube_id"] = yt_id
        result["youtube_url"] = yt_url
    except Exception as exc:
        log.error(f"YouTube upload failed: {exc}")

    # TikTok
    try:
        tt_id, tt_url = upload_to_tiktok(video_path, script)
        result["tiktok_id"] = tt_id
        result["tiktok_url"] = tt_url
    except Exception as exc:
        log.error(f"TikTok upload failed: {exc}")

    return result
