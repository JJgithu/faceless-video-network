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
FALLBACK_TTS_VOICE = "en-US-GuyNeural"        # male fallback when ElevenLabs quota runs out


# ── Caption / subtitle settings ─────────────────────────────────────────────
CAPTION_WORDS_PER_CUE   = 3    # words per caption bubble
CAPTION_FADE_MS         = 120  # ASS fade-in/out in milliseconds
CAPTION_MARGIN_BOTTOM   = 280  # pixels from bottom (higher = subtitles move up)

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
        "key": "historical_mysteries",
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
        "key": "stoic_philosophy",
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
        "key": "deep_sea",
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

    "body_science": {
        "key": "body_science",
        "display_name": "Body Science",
        "emoji": "🧬",
        "style": (
            "fast-paced medical toxicologist delivering shocking biological facts — "
            "speak with clinical precision about exactly what happens to the human body, "
            "second by second, with specific numbers and scientific details that make viewers gasp"
        ),
        "pexels_keywords": ["human anatomy", "medical microscope", "cell biology", "dna strand", "science laboratory"],
        "reddit_subs": ["mildlyinteresting", "todayilearned", "science", "medicine"],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_BODY", "pNInz6obpgDQGcFmaJgB"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_BODY", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_BODY", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_BODY", ""),
        "affiliate_cta": "🧬 Explore the science:",
    },

    "alternate_history": {
        "key": "alternate_history",
        "display_name": "Alternate History",
        "emoji": "🕰️",
        "style": (
            "cinematic storyteller revealing lost history and impossible what-ifs — "
            "speak like a historian who just found classified documents, mixing real facts "
            "with chilling alternate scenarios that force viewers to question everything they know"
        ),
        "pexels_keywords": ["old photograph vintage", "historical war ruins", "ancient civilization dark", "abandoned building", "dramatic storm sky"],
        "reddit_subs": ["AlternateHistory", "history", "todayilearned", "interestingasfuck"],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_ALTHISTORY", "ErXwobaYiN019PkySvjV"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_ALTHISTORY", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_ALTHISTORY", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_ALTHISTORY", ""),
        "affiliate_cta": "📜 Uncover the truth:",
    },

    "animal_pov": {
        "key": "animal_pov",
        "display_name": "Animal POV",
        "emoji": "🐾",
        "style": (
            "thrilling first-person animal narrator with a frantic inner monologue — "
            "voice the animal's raw thoughts, fears, and survival instincts as if you ARE the creature. "
            "Fast-paced, dramatic, and visceral — make the viewer feel every heartbeat"
        ),
        "pexels_keywords": ["macro insect closeup", "wildlife predator hunt", "bird eye view aerial", "spider web nature", "animal eye closeup"],
        "reddit_subs": ["NatureIsFuckingLit", "AnimalsBeingBros", "interestingasfuck", "wildlifephotography"],
        "wikipedia_unusual": True,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_ANIMAL", "onwK4e9ZLuTAKqWW03F9"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_ANIMAL", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_ANIMAL", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_ANIMAL", ""),
        "affiliate_cta": "🐾 More wild POVs:",
    },

    "pause_bait": {
        "key": "pause_bait",
        "display_name": "Pause Bait",
        "emoji": "👁️",
        "style": (
            "high-energy challenge host turning every video into a must-win game — "
            "use urgent countdown language, impossible-sounding claims, and cliffhangers that force "
            "viewers to pause, rewind, and flood the comments. Make it feel like a game show"
        ),
        "pexels_keywords": ["optical illusion", "crowd people hidden", "magic trick", "visual paradox", "brain puzzle light"],
        "reddit_subs": ["mildlyinteresting", "Damnthatsinteresting", "interestingasfuck", "woahdude"],
        "wikipedia_unusual": False,
        "elevenlabs_voice_id": os.environ.get("EL_VOICE_PAUSE", "onwK4e9ZLuTAKqWW03F9"),
        "youtube_channel_id": os.environ.get("YT_CHANNEL_ID_PAUSE", ""),
        "tiktok_access_token": os.environ.get("TIKTOK_TOKEN_PAUSE", TIKTOK_ACCESS_TOKEN),
        "affiliate_link": os.environ.get("AFFILIATE_PAUSE", ""),
        "affiliate_cta": "🧠 Test your brain:",
        "use_ai_image": True,    # Phase 2: use Gemini Imagen instead of Pexels
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
