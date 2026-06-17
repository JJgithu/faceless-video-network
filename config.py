"""
config.py — Central configuration for the Faceless Video Network.

The system supports MULTIPLE NICHE CHANNELS. Each niche has its own:
  - Content style & script tone
  - Reddit subreddits & Wikipedia categories to mine
  - ElevenLabs voice ID (for brand consistency)
  - YouTube channel & TikTok account
  - Affiliate link (auto-injected in descriptions)

The active niche is chosen via the NICHE environment variable,
making GitHub Actions matrix jobs trivial.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR  = BASE_DIR / "data"

# On GitHub Actions use $RUNNER_TEMP; locally use /tmp or a local output dir
OUTPUT_DIR = Path(os.environ.get("RUNNER_TEMP", str(BASE_DIR / "output"))) / "faceless"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Global API Keys ────────────────────────────────────────────────────────
GEMINI_API_KEY       = os.environ.get("GEMINI_API_KEY", "")
PEXELS_API_KEY       = os.environ.get("PEXELS_API_KEY", "")
ELEVENLABS_API_KEY   = os.environ.get("ELEVENLABS_API_KEY", "")   # Primary voice

# YouTube OAuth 2.0 (one set of creds controls all channels via channel switching)
YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_SCOPES        = ["https://www.googleapis.com/auth/youtube.upload"]

# TikTok Content Posting API
TIKTOK_CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_ACCESS_TOKEN  = os.environ.get("TIKTOK_ACCESS_TOKEN", "")

# ── Gemini ─────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"

# ── Video settings ─────────────────────────────────────────────────────────
VIDEO_WIDTH        = 1080
VIDEO_HEIGHT       = 1920
VIDEO_FPS          = 30
MAX_VIDEO_DURATION = 55    # seconds — YouTube Shorts max is 60s
MIN_VIDEO_DURATION = 20
INTRO_DURATION     = 2.5   # title card
OUTRO_DURATION     = 3.0   # CTA card
MUSIC_VOLUME       = 0.10  # background music mix level

# ── ElevenLabs ─────────────────────────────────────────────────────────────
# Model: eleven_turbo_v2_5 is fast + high-quality, perfect for automation
ELEVENLABS_MODEL   = "eleven_turbo_v2_5"
ELEVENLABS_STABILITY     = 0.50
ELEVENLABS_SIMILARITY    = 0.80
ELEVENLABS_STYLE         = 0.20
ELEVENLABS_SPEAKER_BOOST = True

# Fallback TTS if no ElevenLabs key is set
FALLBACK_TTS_VOICE = "en-US-AriaNeural"

# ── Caption / subtitle settings ─────────────────────────────────────────────
CAPTION_WORDS_PER_CUE   = 3    # words per caption bubble
CAPTION_FADE_MS         = 120  # ASS fade-in/out in milliseconds
CAPTION_MARGIN_BOTTOM   = 90   # pixels from bottom

# ── Asset settings ──────────────────────────────────────────────────────────
PEXELS_CLIPS_TARGET     = 6    # number of clips to download
PEXELS_MAX_CLIP_DURATION = 20  # cap clips at 20s before trimming

# ── Topic history ───────────────────────────────────────────────────────────
MAX_TOPIC_HISTORY  = 400
TOPIC_HISTORY_FILE = DATA_DIR / "used_topics.json"

# ── YouTube defaults ────────────────────────────────────────────────────────
YOUTUBE_CATEGORY_ID    = "22"     # People & Blogs (works for all niches)
YOUTUBE_PRIVACY        = "public"
YOUTUBE_MADE_FOR_KIDS  = False

# ── TikTok defaults ─────────────────────────────────────────────────────────
TIKTOK_PRIVACY         = "PUBLIC_TO_EVERYONE"
TIKTOK_DISABLE_COMMENT = False
TIKTOK_DISABLE_DUET    = False
TIKTOK_DISABLE_STITCH  = False

# ──────────────────────────────────────────────────────────────────────────
# NICHE CHANNEL REGISTRY
# Add / remove niches here. Each niche maps to a distinct channel identity.
# ──────────────────────────────────────────────────────────────────────────
NICHES: dict[str, dict] = {

    "historical_mysteries": {
        "display_name": "Historical Mysteries",
        "emoji": "🏛️",
        # Script tone given to Gemini
        "style": (
            "mysterious and dramatic narrator uncovering hidden historical truths — "
            "speak like a documentary host who just found a shocking secret"
        ),
        # Pexels search terms for b-roll footage
        "pexels_keywords": ["ancient ruins", "history documentary", "archaeology", "medieval castle"],
        # Reddit subs to mine for story ideas
        "reddit_subs": ["history", "AskHistorians", "mildlyinteresting", "todayilearned"],
        # Wikipedia categories to scrape for weird facts
        "wikipedia_unusual": True,
        # ElevenLabs voice — deep, authoritative male narrator
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_HISTORY", "pNInz6obpgDQGcFmaJgB"),
        # Channel IDs (set per-channel in GitHub Secrets)
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_HISTORY", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_HISTORY", TIKTOK_ACCESS_TOKEN),
        # Affiliate link appended to every description
        "affiliate_link": os.environ.get("AFFILIATE_HISTORY", ""),
        "affiliate_cta": "📚 Dive deeper — explore history:",
    },

    "stoic_philosophy": {
        "display_name": "Stoic Wisdom",
        "emoji": "🧘",
        "style": (
            "calm, measured philosopher distilling timeless Stoic wisdom — "
            "speak slowly and deliberately, like Marcus Aurelius himself"
        ),
        "pexels_keywords": ["meditation", "nature sunrise", "philosophy calm", "mountain landscape"],
        "reddit_subs": ["Stoicism", "philosophy", "Meditation", "quotes"],
        "wikipedia_unusual": False,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_STOIC", "EXAVITQu4vr4xnSDxMaL"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_STOIC", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_STOIC", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_STOIC", ""),
        "affiliate_cta": "📖 Read more Stoic wisdom:",
    },

    "deep_sea": {
        "display_name": "Ocean Mysteries",
        "emoji": "🌊",
        "style": (
            "awe-struck marine biologist revealing terrifying and beautiful deep-sea secrets — "
            "make every fact sound like it belongs in a horror-meets-nature documentary"
        ),
        "pexels_keywords": ["ocean underwater", "deep sea fish", "coral reef", "marine biology"],
        "reddit_subs": ["marinebiology", "NatureIsFuckingLit", "science", "interestingasfuck"],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_OCEAN", "21m00Tcm4TlvDq8ikWAM"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_OCEAN", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_OCEAN", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_OCEAN", ""),
        "affiliate_cta": "🐙 Explore the deep:",
    },

    "riddles": {
        "display_name": "Mind Benders",
        "emoji": "🧩",
        "style": (
            "playful and teasing puzzle master challenging viewers with clever riddles — "
            "build suspense, pause for the answer, then reveal it dramatically"
        ),
        "pexels_keywords": ["puzzle brain", "thinking person", "question mark", "maze"],
        "reddit_subs": ["riddles", "puzzles", "brainteasers", "trivia"],
        "wikipedia_unusual": False,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_RIDDLES", "onwK4e9ZLuTAKqWW03F9"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_RIDDLES", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_RIDDLES", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_RIDDLES", ""),
        "affiliate_cta": "🧠 Train your brain:",
    },
}

# Active niche for this run (set via NICHE env var in GitHub Actions)
ACTIVE_NICHE = os.environ.get("NICHE", "historical_mysteries")

def get_niche() -> dict:
    """Return the config dict for the currently active niche."""
    niche = NICHES.get(ACTIVE_NICHE)
    if not niche:
        raise ValueError(
            f"Unknown niche '{ACTIVE_NICHE}'. "
            f"Valid options: {list(NICHES.keys())}"
        )
    return niche
