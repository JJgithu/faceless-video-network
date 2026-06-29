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

Active niches: historical_mysteries, deep_sea, body_science, alternate_history
Removed:       stoic_philosophy, animal_pov, pause_bait
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

# ── Pipeline Mode ──────────────────────────────────────────────────────────
# "hybrid" = Claude 3.5 Sonnet + Kling AI (new pipeline)
# "legacy" = Gemini 2.5 Flash + Pexels stock footage (original pipeline)
PIPELINE_MODE = os.environ.get("PIPELINE_MODE", "hybrid")

# ── Global API Keys ────────────────────────────────────────────────────────
GEMINI_API_KEY       = os.environ.get("GEMINI_API_KEY", "")
PEXELS_API_KEY       = os.environ.get("PEXELS_API_KEY", "")
ELEVENLABS_API_KEY   = os.environ.get("ELEVENLABS_API_KEY", "")   # Primary voice

# ── Anthropic (Claude 3.5 Sonnet — Hybrid pipeline brain) ─────────────────
ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL         = "claude-sonnet-4-6"

# ── Edge TTS (free fallback when ElevenLabs quota exhausted) ───────────────
# No API key needed. Uses Microsoft's neural voices via edge-tts package.
EDGE_TTS_VOICE       = "en-US-GuyNeural"   # Deep, serious, male documentary-style

# ── Kling AI (AI video generation — Hybrid pipeline cinematographer) ───────
KLING_API_KEY        = os.environ.get("KLING_API_KEY", "")
KLING_API_BASE       = "https://api-singapore.klingai.com"
KLING_MODEL          = "kling-v1"   # Standard tier, NOT Pro
KLING_DURATION       = 5            # 5 seconds per clip
KLING_ASPECT_RATIO   = "9:16"      # CRITICAL: portrait for YouTube Shorts
KLING_POLL_INTERVAL  = 15           # seconds between status checks
KLING_TIMEOUT        = 600          # 10 minutes max wait per clip
KLING_CLIPS_COUNT    = 4            # exactly 4 clips per video

# YouTube OAuth 2.0 (one set of creds controls all channels via channel switching)
YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_SCOPES        = ["https://www.googleapis.com/auth/youtube.upload"]

# TikTok Content Posting API
TIKTOK_CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_ACCESS_TOKEN  = os.environ.get("TIKTOK_ACCESS_TOKEN", "")

# Affiliate tags (one tag covers all books/products)
# Sign up free at: affiliate-program.amazon.com (covers both Amazon & Audible)
AUDIBLE_AFFILIATE_TAG = os.environ.get("AUDIBLE_AFFILIATE_TAG", "") or os.environ.get("AMAZON_AFFILIATE_TAG", "")
AMAZON_AFFILIATE_TAG  = os.environ.get("AMAZON_AFFILIATE_TAG", "")

# ── Gemini ─────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"

# ── Video settings ─────────────────────────────────────────────────────────
VIDEO_WIDTH        = 1080
VIDEO_HEIGHT       = 1920
VIDEO_FPS          = 30
MAX_VIDEO_DURATION = 45    # seconds — keep videos tight and engaging
MIN_VIDEO_DURATION = 20
INTRO_DURATION     = 0.0   # NO intro card — video starts instantly in action
OUTRO_DURATION     = 3.0   # CTA card
MUSIC_VOLUME       = 0.10  # background music mix level

# ── Visual pacing ──────────────────────────────────────────────────────────
# Visuals MUST change every 2–3 seconds to maintain constant dopamine
CLIP_MAX_DURATION  = 2.5   # max seconds per clip before cutting to next
CLIP_FADE_DURATION = 0.08  # barely-perceptible cut (no slow cinematic fades)

# ── Hook SFX (frame 1 pattern interrupt) ───────────────────────────────────
HOOK_SFX_TYPE      = "boom_whoosh"  # jarring combo: heavy boom + whoosh
HOOK_SFX_VOLUME    = 0.85           # loud enough to wake the viewer up
SFX_VOLUME         = 0.65           # inline SFX mix level (under voice)

# ── TTS Speedup (Hybrid pipeline retention fix) ───────────────────────────
# 1.15x speedup makes narration sound fast and urgent — zero gaps of silence
TTS_SPEEDUP        = 1.15

# ── First Clip Trim (Hybrid pipeline retention fix) ───────────────────────
# Kling AI videos often start with a frozen frame. Chop 0.5s off clip 1
# to drop the viewer instantly into motion.
FIRST_CLIP_TRIM_START = 0.5

# ── ElevenLabs ─────────────────────────────────────────────────────────────
# Model: eleven_turbo_v2_5 is fast + high-quality, perfect for automation
ELEVENLABS_MODEL         = "eleven_turbo_v2_5"
ELEVENLABS_STABILITY     = 0.50
ELEVENLABS_SIMILARITY    = 0.80
ELEVENLABS_STYLE         = 0.20
ELEVENLABS_SPEAKER_BOOST = True

# ── Caption / subtitle settings (Hormozi style) ─────────────────────────────
# 1–2 words per cue, center screen, massive bold font — locks eyes to screen
CAPTION_WORDS_PER_CUE   = 2      # 1–2 words per pop-in
CAPTION_FADE_MS         = 80     # fast snap-in (not a slow fade)
CAPTION_FONT_SIZE       = 88     # large and dominant
CAPTION_MARGIN_BOTTOM   = 0      # not used — captions are center-screen (Alignment=5)
CAPTION_PRIMARY_COLOR   = "&H0000FFFF"   # bright yellow (ASS BGR format)
CAPTION_OUTLINE_COLOR   = "&H00000000"   # black outline
CAPTION_BACK_COLOR      = "&HAA000000"   # semi-transparent dark shadow box

# ── Asset settings ──────────────────────────────────────────────────────────
PEXELS_CLIPS_TARGET     = 10   # more clips = more variety for fast cutting
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
# Four active niches — all share the "dark curiosity" mega-theme:
#   historical mysteries + alternate history + deep sea + bizarre body science
#
# Each niche keeps its own channel ID + voice for brand consistency,
# but all four draw from the same universe of content and style.
# ──────────────────────────────────────────────────────────────────────────
NICHES: dict[str, dict] = {

    "historical_mysteries": {
        "key": "historical_mysteries",
        "display_name": "Historical Mysteries",
        "emoji": "🏛️",
        # Combined mega-style: history + alternate history + body horror + deep sea
        "style": (
            "cinematic historian and investigative journalist uncovering impossible truths — "
            "mix verified shocking historical facts with dark alternate scenarios, bizarre "
            "biological facts about people in history, and deep-time discoveries that rewrite "
            "what we thought we knew. Sound like a documentary host who just found classified documents. "
            "Every sentence must be a revelation."
        ),
        # Broad keyword pool covering all four domains
        "pexels_keywords": [
            "ancient ruins dramatic", "history documentary dark", "archaeology discovery",
            "medieval castle dramatic", "old photograph vintage", "historical war ruins",
            "ancient civilization dark", "abandoned building",
        ],
        "reddit_subs": [
            "history", "AskHistorians", "mildlyinteresting", "todayilearned",
            "AlternateHistory", "interestingasfuck", "science",
        ],
        "wikipedia_unusual": True,
        # ElevenLabs voice — deep, authoritative male narrator
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_HISTORY", "pNInz6obpgDQGcFmaJgB"),
        # Channel IDs (set per-channel in GitHub Secrets)
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_HISTORY", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_HISTORY", TIKTOK_ACCESS_TOKEN),
        # Affiliate link appended to every description
        "affiliate_link": os.environ.get("AFFILIATE_HISTORY", ""),
        "affiliate_cta": "📚 Dive deeper — explore history:",
        # SFX palette for this niche
        "sfx_palette": ["boom", "thunder", "reveal", "deep_rumble"],
    },

    "deep_sea": {
        "key": "deep_sea",
        "display_name": "Ocean Mysteries",
        "emoji": "🌊",
        "style": (
            "awe-struck deep-sea researcher revealing the most terrifying and beautiful "
            "secrets from the ocean's abyss — combine real marine biology with alternate "
            "history of ocean exploration, bizarre body science of pressure and survival, "
            "and mysteries that have never been explained. "
            "Make every fact sound like it belongs in a horror-meets-nature documentary. "
            "Be specific: use real depths in feet, real species names, real biology. "
            "Start mid-sentence with the most disturbing fact first."
        ),
        "pexels_keywords": [
            "ocean underwater dark", "deep sea creature", "coral reef dramatic",
            "marine biology abyss", "underwater cave", "bioluminescent ocean",
            "submarine deep water", "ocean storm dramatic",
        ],
        "reddit_subs": [
            "marinebiology", "NatureIsFuckingLit", "science", "interestingasfuck",
            "todayilearned", "mildlyinteresting",
        ],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_OCEAN", "21m00Tcm4TlvDq8ikWAM"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_OCEAN", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_OCEAN", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_OCEAN", ""),
        "affiliate_cta": "🐙 Explore the deep:",
        "sfx_palette": ["water_drop", "deep_rumble", "creepy_crawl", "boom"],
    },

    "body_science": {
        "key": "body_science",
        "display_name": "Body Science",
        "emoji": "🧬",
        "style": (
            "fast-paced medical toxicologist and survival specialist delivering shocking "
            "biological facts — combine extreme medical mysteries, bizarre survival scenarios, "
            "deep-sea pressure effects on the human body, and historical cases of impossible "
            "human endurance. Speak with clinical precision: use exact numbers (mg, mmHg, °C, BPM). "
            "Use a countdown or sequence format to build dread second-by-second. "
            "Hook must name the exact horrifying thing that happens to the body — no buildup."
        ),
        "pexels_keywords": [
            "human anatomy dramatic", "medical emergency", "cell biology microscope",
            "dna strand science", "science laboratory", "x-ray scan dramatic",
            "heartbeat monitor", "survival extreme cold",
        ],
        "reddit_subs": [
            "mildlyinteresting", "todayilearned", "science", "medicine",
            "interestingasfuck", "NatureIsFuckingLit",
        ],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_BODY", "pNInz6obpgDQGcFmaJgB"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_BODY", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_BODY", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_BODY", ""),
        "affiliate_cta": "🧬 Explore the science:",
        "sfx_palette": ["heartbeat", "creepy_crawl", "boom", "reveal"],
    },

    "alternate_history": {
        "key": "alternate_history",
        "display_name": "Alternate History",
        "emoji": "🕰️",
        "style": (
            "cinematic storyteller and investigative journalist revealing lost history, "
            "cover-ups, and impossible what-ifs — mix verified shocking historical facts "
            "with chilling alternate scenarios, bizarre discoveries that were buried, "
            "and deep-sea or biological evidence that changes everything. "
            "Sound like a historian who just found classified documents. "
            "Open with a real historical fact that sounds impossible. "
            "Every sentence forces the viewer to question what they were taught."
        ),
        "pexels_keywords": [
            "old photograph vintage dramatic", "historical war ruins", "ancient civilization dark",
            "abandoned building dramatic", "dramatic storm sky", "classified document",
            "conspiracy board", "underground bunker",
        ],
        "reddit_subs": [
            "AlternateHistory", "history", "todayilearned", "interestingasfuck",
            "mildlyinteresting", "AskHistorians",
        ],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_ALTHISTORY", "ErXwobaYiN019PkySvjV"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_ALTHISTORY", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_ALTHISTORY", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_ALTHISTORY", ""),
        "affiliate_cta": "📜 Uncover the truth:",
        "sfx_palette": ["thunder", "boom", "reveal", "deep_rumble"],
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
