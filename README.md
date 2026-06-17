# 🎬 Faceless Video Network

> **Fully autonomous AI video channel network** — Gemini 2.5 Flash finds trending stories,
> ElevenLabs narrates them, FFmpeg assembles portrait videos, and the system publishes
> to YouTube Shorts + TikTok automatically. Twice a day. Zero human effort.

---

## 📺 Channel Niches

| Niche | Style | Content Source |
|---|---|---|
| 🏛️ **Historical Mysteries** | Dramatic documentary narrator | Wikipedia Unusual Articles + Reddit r/history |
| 🧘 **Stoic Wisdom** | Calm philosophical voice | Reddit r/Stoicism + philosophy |
| 🌊 **Ocean Mysteries** | Awe-struck marine biologist | Wikipedia + Reddit r/marinebiology |
| 🧩 **Mind Benders** | Playful puzzle master | Reddit r/riddles + r/puzzles |

---

## 🏗️ System Architecture

```
[Gemini 2.5 Flash]  ←── Google Trends + Reddit + Wikipedia
       │
       ▼ (story selection + script)
[ElevenLabs TTS]    ──► hyper-realistic narration .mp3
       │
       ▼
[Pexels API]        ──► royalty-free portrait b-roll clips
       │
       ▼
[FFmpeg Assembler]
  ├─ Blurred-background portrait conversion (1080×1920)
  ├─ Title card + CTA card
  ├─ Narration + ambient music mix
  └─ Kinetic ASS captions (word-by-word fade pop)
       │
       ▼
[YouTube Data API]  ──► YouTube Shorts (public, auto-tagged #Shorts)
[TikTok API]        ──► TikTok (public, title + hashtags)
       │
       ▼
[GitHub Actions]    ──► runs automatically 9am ET + 9pm ET, every day
```

---

## 🚀 Quick Setup (30 minutes)

### Step 1 — Fork & Clone

```bash
git clone https://github.com/YOUR_USERNAME/faceless-video-network.git
cd faceless-video-network
pip install -r requirements.txt
```

### Step 2 — Get API Keys

| Secret | Where to Get | Cost |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | Free tier |
| `PEXELS_API_KEY` | [pexels.com/api](https://www.pexels.com/api/) | Free |
| `ELEVENLABS_API_KEY` | [elevenlabs.io](https://elevenlabs.io) | Free tier (10k chars/mo) |
| `YOUTUBE_*` | Google Cloud Console | Free |
| `TIKTOK_*` | [developers.tiktok.com](https://developers.tiktok.com) | Free |

### Step 3 — YouTube OAuth Setup (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create project → Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials → Desktop App → Download JSON
4. Run:
   ```bash
   python scripts/get_youtube_token.py --credentials path/to/client_secret.json
   ```
5. Copy the 3 printed values to GitHub Secrets

### Step 4 — TikTok Token Setup (one-time)

1. Go to [developers.tiktok.com](https://developers.tiktok.com) → Create App
2. Request access to **Content Posting API**
3. Add redirect URI: `http://localhost:8080/callback`
4. Run:
   ```bash
   python scripts/get_tiktok_token.py --client-key YOUR_KEY --client-secret YOUR_SECRET
   ```
5. Copy printed values to GitHub Secrets

### Step 5 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

```
GEMINI_API_KEY
PEXELS_API_KEY
ELEVENLABS_API_KEY
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_REFRESH_TOKEN
TIKTOK_CLIENT_KEY
TIKTOK_CLIENT_SECRET
TIKTOK_ACCESS_TOKEN
```

### Step 6 — Test Locally

```bash
# Test without uploading (dry run)
NICHE=historical_mysteries python main.py --dry-run

# Test a specific niche
NICHE=stoic_philosophy python main.py --dry-run
```

### Step 7 — Enable GitHub Actions

Push to `main` branch. The workflow runs automatically at:
- **9am ET** — morning video
- **9pm ET** — evening video

You can also trigger manually:
**Actions → Faceless Video Pipeline → Run workflow**

---

## 💰 Monetization Guide

### YouTube Partner Program (YPP)

You need **1,000 subscribers + 10 million Shorts views** in 90 days.

1. Go to YouTube Studio → **Earn** tab
2. Apply for the YouTube Partner Program
3. Connect a **Google AdSense** account (free at [adsense.google.com](https://adsense.google.com))
4. Enable monetization on each video (or auto-enable in channel settings)

**Payout**: ~$0.03–$0.06 per 1,000 Shorts views via YouTube Shorts ad revenue pool.

---

### TikTok Creator Rewards Program

You need **10,000 followers + 100,000 views in 30 days**.

1. Open TikTok app → Profile → Creator tools → **TikTok Creator Rewards**
2. Apply once you hit the threshold
3. Link your bank account or PayPal for payouts

**Payout**: ~$0.02–$0.04 per 1,000 views.

---

### Affiliate Links (Passive Income)

Set affiliate links per niche in GitHub Secrets:

```
AFFILIATE_HISTORY  = https://amzn.to/your-history-book-link
AFFILIATE_STOIC    = https://amzn.to/your-stoic-book-link
AFFILIATE_OCEAN    = https://amzn.to/your-ocean-book-link
AFFILIATE_RIDDLES  = https://amzn.to/your-puzzle-book-link
```

The system automatically appends the link to every video description.

**Best affiliate programs:**
- [Amazon Associates](https://affiliate-program.amazon.com) — books, products related to niche
- [Bookshop.org](https://bookshop.org/affiliates) — great for history/philosophy niches
- [Audible](https://www.amazon.com/audiblepartner) — audiobooks, great CTA ("Listen free")

**Earning estimate (100k views/month across all channels):**

| Source | Rate | Monthly @ 100k views |
|---|---|---|
| YouTube Shorts fund | $0.04/1k | ~$4 |
| TikTok Creator Rewards | $0.03/1k | ~$3 |
| Affiliate clicks (1% CTR, 5% conversion) | $5–15/sale | ~$25–75 |
| **Total** | | **~$30–80/month** |

> 📈 This scales linearly. At 1M views/month across 4 channels: **$300–800/month**.

---

## ⚙️ Configuration

All settings live in [`config.py`](config.py). Key things you can change:

| Setting | Default | Description |
|---|---|---|
| `VIDEO_WIDTH/HEIGHT` | 1080×1920 | Portrait format (don't change) |
| `MAX_VIDEO_DURATION` | 55s | Keep under 60s for Shorts |
| `CAPTION_WORDS_PER_CUE` | 3 | Words per caption bubble |
| `MUSIC_VOLUME` | 0.10 | Background music level (0=off, 1=full) |
| `PEXELS_CLIPS_TARGET` | 6 | Number of b-roll clips per video |
| `ELEVENLABS_MODEL` | eleven_turbo_v2_5 | Voice model (turbo=fast) |

To add a new niche channel, add an entry to the `NICHES` dict in `config.py`.

---

## 📁 Project Structure

```
faceless-video-network/
├── .github/workflows/
│   └── generate_video.yml    # GitHub Actions (runs 2x/day)
├── engines/
│   ├── trend_engine.py       # Wikipedia + Reddit + Google Trends scraper
│   ├── script_engine.py      # Gemini 2.5 Flash scriptwriter
│   ├── asset_engine.py       # Pexels downloader + ambient music generator
│   ├── voice_engine.py       # ElevenLabs TTS + kinetic ASS captions
│   ├── video_engine.py       # FFmpeg portrait video assembler
│   └── publisher.py          # YouTube Shorts + TikTok uploader
├── utils/
│   ├── gemini_client.py      # Gemini API wrapper with retry + JSON parsing
│   ├── logger.py             # Structured logging
│   └── file_manager.py       # Temp file cleanup
├── scripts/
│   ├── get_youtube_token.py  # One-time YouTube OAuth setup
│   └── get_tiktok_token.py   # One-time TikTok OAuth setup
├── data/
│   └── used_topics.json      # Topic deduplication history (auto-committed)
├── main.py                   # Pipeline orchestrator
├── config.py                 # All settings + niche definitions
├── requirements.txt
└── .env.example
```

---

## 🛠️ Troubleshooting

**FFmpeg not found**
→ `sudo apt-get install ffmpeg` (Linux) or download from [ffmpeg.org](https://ffmpeg.org)

**ElevenLabs quota exceeded**
→ The system automatically falls back to Microsoft Edge TTS (free, no key needed)

**YouTube upload fails with 403**
→ Your refresh token may have expired. Re-run `scripts/get_youtube_token.py`

**TikTok upload fails**
→ TikTok access tokens expire in 24h. Re-run `scripts/get_tiktok_token.py`

**No Pexels results**
→ The system falls back to broader keyword searches automatically

**Pytrends rate limit**
→ Google Trends occasionally blocks scrapers. The system continues using Reddit + Wikipedia as fallback

---

## 📄 License

MIT — do whatever you want with this. Build your empire. 🚀
