"""
engines/trend_engine.py
─────────────────────────────────────────────────────────────────────────────
The Hook Researcher — finds the best story idea for the active niche channel.

Sources (in order of priority):
  1. Wikipedia "Unusual Articles" page (mind-bending, evergreen content)
  2. Reddit hot posts from niche-specific subreddits
  3. Google Trends daily searches (for viral/timely angles)

Gemini 2.5 Flash then acts as the editorial director — ranking all candidates
against the niche's style and selecting the single best story that hasn't
been covered recently.
"""

import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import requests
from bs4 import BeautifulSoup
from pytrends.request import TrendReq

import config
from utils.gemini_client import ask_json
from utils.logger import get_logger

log = get_logger(__name__)


class Topic(TypedDict):
    topic: str           # Short, catchy topic title
    angle: str           # The unique compelling angle
    hook: str            # Opening sentence (first 3 seconds of the video)
    keywords: list[str]  # Pexels search keywords for b-roll
    source: str          # Where the idea came from


# ── History helpers ────────────────────────────────────────────────────────

def _load_used_topics() -> set[str]:
    path: Path = config.TOPIC_HISTORY_FILE
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("topics", []))
    except Exception:
        return set()


def _save_used_topic(topic: str) -> None:
    path: Path = config.TOPIC_HISTORY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        topics: list[str] = data.get("topics", [])
        topics.append(f"{config.ACTIVE_NICHE}::{topic}")
        topics = topics[-config.MAX_TOPIC_HISTORY:]
        data["topics"] = topics
        data["last_updated"] = datetime.utcnow().isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning(f"Could not save topic history: {exc}")


# ── Data Sources ───────────────────────────────────────────────────────────

def _get_wikipedia_unusual_articles() -> list[str]:
    """
    Scrape Wikipedia's 'Unusual Articles' page — a goldmine of bizarre,
    mind-bending topics perfect for viral faceless content.
    https://en.wikipedia.org/wiki/Wikipedia:Unusual_articles
    """
    try:
        resp = requests.get(
            "https://en.wikipedia.org/wiki/Wikipedia:Unusual_articles",
            headers={"User-Agent": "FacelessVideoBot/1.0 (educational)"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        titles: list[str] = []
        # The page lists articles as links within the main content
        content_div = soup.find("div", {"id": "mw-content-text"})
        if content_div:
            for link in content_div.find_all("a", href=True):
                href = link.get("href", "")
                title = link.get("title", "").strip()
                # Only internal Wikipedia article links, not meta pages
                if (
                    href.startswith("/wiki/")
                    and title
                    and ":" not in href[6:]   # skip Wikipedia: File: etc.
                    and len(title) > 5
                    and len(title) < 100
                ):
                    titles.append(title)

        # Deduplicate and shuffle
        unique = list(dict.fromkeys(titles))
        random.shuffle(unique)
        log.info(f"Wikipedia Unusual Articles: {len(unique)} titles scraped")
        return unique[:40]

    except Exception as exc:
        log.warning(f"Wikipedia scraping failed: {exc}")
        return []


def _get_reddit_posts(subreddits: list[str]) -> list[str]:
    """Fetch top hot post titles from niche-specific subreddits."""
    posts: list[str] = []
    headers = {"User-Agent": "FacelessVideoBot/1.0"}

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10&t=day"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            for child in resp.json()["data"]["children"]:
                post = child["data"]
                if not post.get("stickied") and post.get("title"):
                    posts.append(post["title"])
            time.sleep(0.6)   # polite delay
        except Exception as exc:
            log.warning(f"Reddit r/{sub} failed: {exc}")

    log.info(f"Reddit: {len(posts)} titles from {len(subreddits)} subreddits")
    return posts[:30]


def _get_google_trends() -> list[str]:
    """Google Trends daily top searches — adds viral/timely angles."""
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        df = pytrends.trending_searches(pn=config.GOOGLE_TRENDS_GEO.lower()
                                        if hasattr(config, "GOOGLE_TRENDS_GEO")
                                        else "united_states")
        trends = df[0].tolist()[:15]
        log.info(f"Google Trends: {len(trends)} trends fetched")
        return trends
    except Exception as exc:
        log.warning(f"Google Trends failed: {exc}")
        return []


# ── Gemini Ranker ──────────────────────────────────────────────────────────

def _rank_with_gemini(
    candidates: list[str],
    niche: dict,
    used_topics: set[str],
) -> Topic:
    """
    Ask Gemini to pick the single best topic from candidates, matching
    the niche's editorial style and avoiding recently covered topics.
    """
    used_sample = [t.split("::")[-1] for t in list(used_topics)[-40:]]

    prompt = f"""
You are the editorial director for a viral short-form video channel called
"{niche['display_name']}" {niche['emoji']}.

Channel style: {niche['style']}

Your job: pick the ONE topic from the list below that will perform best
as a 50-second vertical video for this channel.

Selection criteria:
✅ Perfectly matches the channel's niche and tone
✅ Genuinely surprising, emotional, or mind-bending
✅ Can be explained compellingly in under 55 seconds
✅ Has strong visual b-roll potential (nature, cities, people, etc.)
✅ NOT in the "recently used" list

CANDIDATE TOPICS:
{chr(10).join(f'- {c}' for c in candidates)}

RECENTLY USED (avoid these):
{chr(10).join(f'- {t}' for t in used_sample) if used_sample else '(none yet — all topics are fresh)'}

Reply with ONE JSON object:
{{
  "topic": "Concise topic title (max 10 words)",
  "angle": "The specific surprising or dramatic angle that makes this perfect for this channel",
  "hook": "Opening narration sentence — max 15 words, must grab attention in 2 seconds",
  "keywords": ["pexels_keyword1", "pexels_keyword2", "pexels_keyword3", "pexels_keyword4"],
  "source": "wikipedia or reddit or google_trends"
}}
"""
    result: Topic | None = None
    try:
        result = ask_json(prompt)
        log.info(f"Gemini selected: '{result['topic']}' (source: {result['source']})")
        return result
    except Exception as exc:
        log.warning(f"Gemini ranker failed ({exc}) -- falling back to random pick from candidates")

    # -- Fallback: pick a random unused candidate and build a minimal Topic ----
    used_titles = {t.split("::")[-1].lower() for t in used_topics}
    fresh = [c for c in candidates if c.lower() not in used_titles] or candidates
    random.shuffle(fresh)
    chosen = fresh[0]

    # Build a basic Topic without Gemini (good enough to generate a script)
    niche_keywords = niche.get("pexels_keywords", ["nature", "science", "world"])[:4]
    fallback_topic: Topic = {
        "topic": chosen[:80],
        "angle": f"A fascinating and surprising look at: {chosen}",
        "hook": f"You won't believe this: {chosen[:60]}",
        "keywords": niche_keywords,
        "source": "fallback_random",
    }
    log.warning(f"Random fallback topic selected: '{fallback_topic['topic']}'")
    return fallback_topic


def _gemini_topic_fallback(niche: dict, used_topics: set[str]) -> list[str]:
    """
    When ALL external sources fail (Reddit blocked, Google 404, no Wikipedia),
    ask Gemini to brainstorm fresh topic ideas directly from its own knowledge.
    Returns a list of topic title strings ready for _rank_with_gemini.
    """
    log.warning("All external sources failed — using Gemini topic brainstorm as fallback")
    used_sample = [t.split("::")[-1] for t in list(used_topics)[-20:]]

    prompt = f"""
 You are a viral content researcher for a short-form video channel called
 "{niche['display_name']}" {niche['emoji']}.
 Channel style: {niche['style']}

 Generate 12 compelling, specific topic ideas for this channel.
 Each topic should be:
 ✅ Genuinely surprising, emotional, or mind-bending
 ✅ Based on real facts or well-known historical/philosophical events
 ✅ Explainable in under 60 seconds
 ✅ NOT in this recently covered list: {used_sample or '(none)'}

 Reply with ONLY a JSON array of 12 topic title strings:
 ["Topic 1", "Topic 2", ...]
 """
    try:
        topics = ask_json(prompt)
        if isinstance(topics, list) and topics:
            log.info(f"Gemini fallback generated {len(topics)} topic ideas")
            return [str(t) for t in topics[:12]]
    except Exception as exc:
        log.warning(f"Gemini fallback also failed: {exc}")
    return []


# -- Hardcoded evergreen topic bank (last-resort when ALL APIs fail) ----------
# These are high-quality, evergreen topics that never expire.
# Gemini still picks the best one and writes the script -- we just skip scraping.

TOPIC_BANK: dict[str, list[str]] = {
    "historical_mysteries": [
        "The Voynich Manuscript: The Book No One Can Read",
        "The Lost Colony of Roanoke: 100 People Vanished",
        "The Dyatlov Pass Incident: 9 Hikers, No Explanation",
        "The Antikythera Mechanism: Ancient Computer from 100 BC",
        "Oak Island: 200 Years of Searching for Hidden Treasure",
        "The Dancing Plague of 1518: Town Danced Itself to Death",
        "The Taos Hum: A Sound Only 2% of People Can Hear",
        "The Wow! Signal: The Only Possible Alien Transmission Ever Recorded",
        "The Baghdad Battery: Ancient Electricity from 250 BC",
        "The Mary Celeste: Ghost Ship Found Perfectly Intact",
    ],
    "stoic_philosophy": [
        "Marcus Aurelius Ruled an Empire While Fighting Depression",
        "The Stoic Exercise That Cures Anxiety in 5 Minutes",
        "What Seneca Said About Wasting Your Life That Still Hits Hard",
        "The Dichotomy of Control: The Only Stoic Rule You Need",
        "Epictetus Was a Slave Who Became the Most Powerful Man in Rome",
        "The Negative Visualization Technique Billionaires Use Daily",
        "Memento Mori: Why Thinking About Death Makes You Happier",
        "The Stoic Morning Routine That Marcus Aurelius Used Every Day",
        "Why the Stoics Said Anger Is Temporary Insanity",
        "Amor Fati: The Philosophy of Loving Everything That Happens to You",
    ],
    "deep_sea": [
        "The Mariana Trench Is Deeper Than Everest Is Tall",
        "The Bloop: The Loudest Underwater Sound Ever Recorded",
        "Zombie Worms That Dissolve Whale Bones With Acid",
        "The Giant Squid Was Considered a Myth Until 2004",
        "Barreleye Fish Has a Transparent Head and Rotating Eyes",
        "The Immortal Jellyfish That Resets Its Own Biological Age",
        "Anglerfish: The Female Literally Absorbs the Male's Body",
        "The Black Seadevil Lives in Total Darkness at 3,000 Feet",
        "Mantis Shrimp Can Punch With the Force of a Bullet",
        "Deep Sea Octopus Holds Its Breath for 4.5 Years to Guard Eggs",
    ],
    "body_science": [
        "Your Body Starts Digesting Itself Hours After You Die",
        "The Human Eye Can Detect a Single Photon of Light",
        "Your Stomach Gets a Completely New Lining Every 4 Days",
        "You Produce Enough Saliva in a Lifetime to Fill Two Swimming Pools",
        "The Appendix Is Not Useless -- It Reboots Your Gut Bacteria",
        "Your Bones Are Constantly Being Dissolved and Rebuilt",
        "The Human Body Contains More Bacterial Cells Than Human Cells",
        "You Lose Half Your Taste Buds by the Time You Are 60",
        "Your Brain Uses 20% of All Energy Despite Being 2% of Body Weight",
        "A Single Sneeze Travels at 100 MPH and Contains 100,000 Germs",
    ],
    "alternate_history": [
        "What If the Library of Alexandria Never Burned Down",
        "The Nazi Bell: Hitler's Secret Time-Travel Weapon",
        "What If the South Won the American Civil War",
        "The Phantom Time Hypothesis: 300 Years of History That Never Happened",
        "What If the Mongols Had Invaded Western Europe",
        "Tesla's Death Ray: The Weapon the Government Seized and Hid",
        "What If Rome Never Fell: Modern Civilization 1000 Years Ahead",
        "The Tartaria Conspiracy: Was There a Global Empire We Were Never Told About",
        "What If the Black Death Never Happened",
        "The Great Mud Flood Theory: Cities Were Built Over an Older Civilization",
    ],
    "animal_pov": [
        "POV: You Are an Ant Being Carried 1000 Times Your Body Weight",
        "POV: You Are a Mantis Shrimp Seeing 16 Colors Humans Cannot See",
        "POV: You Are a Dog Smelling a City From a Single Strand of Grass",
        "POV: You Are a Monarch Butterfly Navigating 3000 Miles Using the Sun",
        "POV: You Are a Bat Navigating Total Darkness at 60 MPH",
        "POV: You Are a Pistol Shrimp Creating a Flash Hotter Than the Sun",
        "POV: You Are a Tardigrade Surviving the Vacuum of Space",
        "POV: You Are a Crow Solving a 5-Step Puzzle for Food",
        "POV: You Are a Mimic Octopus Choosing Which Predator to Become",
        "POV: You Are a Salmon Swimming Against a Waterfall to Get Home",
    ],
    "pause_bait": [
        "99% of People Cannot Find the Hidden Animal in This Photo in 5 Seconds",
        "This Optical Illusion Reveals Your Dominant Brain Type",
        "Can You Spot the Difference Before the Timer Runs Out",
        "Only 1 in 1000 People See This Color Illusion Correctly",
        "This Image Has 12 Faces Hidden in It -- Most People Find 4",
        "What Do You See First? It Reveals Your Personality",
        "The Spinning Dancer: Does She Spin Left or Right",
        "How Many Legs Does This Elephant Have -- Most People Get It Wrong",
        "This Visual Illusion Bends Lines That Are Perfectly Straight",
        "Stare at This for 30 Seconds Then Look at Your Hand",
    ],
}


def _bank_fallback(niche_key: str, used_topics: set[str]) -> list[str]:
    """Return unused topics from the hardcoded bank for this niche."""
    bank = TOPIC_BANK.get(niche_key, [])
    if not bank:
        return []
    used_titles = {t.split("::")[-1].lower() for t in used_topics}
    fresh = [t for t in bank if t.lower() not in used_titles]
    if not fresh:
        # All bank topics used -- recycle them (better than crashing)
        fresh = list(bank)
    random.shuffle(fresh)
    log.warning(f"Using hardcoded topic bank ({len(fresh)} fresh topics available)")
    return fresh


def get_trending_topic() -> Topic:
    """
    Main entry point. Gathers story candidates from all sources,
    asks Gemini to pick the best one for the active niche, logs it, and returns.
    """
    niche = config.get_niche()
    log.info(f"═══ Trend Engine: [{niche['display_name']}] finding today's story ═══")

    used_topics = _load_used_topics()
    # Only filter topics used for THIS niche
    niche_used = {t for t in used_topics if t.startswith(f"{config.ACTIVE_NICHE}::")}

    candidates: list[str] = []

    # Source 1: Wikipedia Unusual Articles (when relevant to niche)
    if niche.get("wikipedia_unusual"):
        candidates.extend(_get_wikipedia_unusual_articles())

    # Source 2: Niche-specific Reddit posts
    candidates.extend(_get_reddit_posts(niche.get("reddit_subs", [])))

    # Source 3: Google Trends (for timely context)
    candidates.extend(_get_google_trends())

    # Remove previously used topics for this niche
    used_titles = {t.split("::")[-1].lower() for t in niche_used}
    candidates = [c for c in candidates if c.lower() not in used_titles]
    random.shuffle(candidates)
    candidates = candidates[:45]

    # Gemini fallback — if all external sources failed, generate ideas directly
    if not candidates:
        candidates = _gemini_topic_fallback(niche, niche_used)

    # Last-resort: hardcoded evergreen topic bank (survives Reddit 403 + Gemini 503)
    if not candidates:
        candidates = _bank_fallback(config.ACTIVE_NICHE, niche_used)

    if not candidates:
        raise RuntimeError(
            f"No fresh story candidates found for niche '{config.ACTIVE_NICHE}'. "
            "Check internet connectivity and API access."
        )

    topic = _rank_with_gemini(candidates, niche, niche_used)
    _save_used_topic(topic["topic"])

    return topic
