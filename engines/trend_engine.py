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
    result: Topic = ask_json(prompt)
    log.info(f"Gemini selected: '{result['topic']}' (source: {result['source']})")
    return result


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
    # ── Historical Mysteries ────────────────────────────────────────────────
    # Cross-domain: history + body horror of death/survival + alternate outcomes
    "historical_mysteries": [
        "The Voynich Manuscript: The Book No One Can Read",
        "The Lost Colony of Roanoke: 100 People Vanished Without a Trace",
        "The Dyatlov Pass Incident: 9 Hikers, Exploded Eyes, No Explanation",
        "The Antikythera Mechanism: A Computer Built 2,000 Years Before Its Time",
        "The Dancing Plague of 1518: A Town Danced Itself to Death",
        "The Taos Hum: A Sound Only 2% of People Can Hear — and It's Driving Them Mad",
        "The Wow! Signal: The Only Possible Alien Transmission Ever Recorded",
        "The Baghdad Battery: Someone Generated Electricity 2,000 Years Before Edison",
        "The Mary Celeste: 10 Crew Members Vanished From a Perfectly Intact Ship",
        "The Green Children of Woolpit: Two Children Appeared Speaking No Known Language",
        "Göbekli Tepe: A Temple Built 7,000 Years Before Stonehenge",
        "The Black Death Doctors Wore Bird Masks Stuffed With Dead Flowers to Survive",
        "In 1908, 2,000 Square Miles of Siberian Forest Exploded With No Impact Crater",
        "The Piri Reis Map Shows Antarctica 300 Years Before It Was Discovered",
        "Egyptian Mummies Contain Trace Amounts of Cocaine — Only Found in the Americas",
    ],

    # ── Deep Sea ───────────────────────────────────────────────────────────
    # Cross-domain: ocean + body horror of pressure + medical mysteries
    "deep_sea": [
        "Past 1,000 Feet Your Lungs Will Literally Crush Themselves",
        "The Mariana Trench Is So Deep That Everest Would Disappear Inside It",
        "The Bloop: An Underwater Sound Louder Than a Nuclear Bomb Was Never Explained",
        "Zombie Worms Dissolve Whale Bones With Pure Acid to Eat Them From Inside",
        "The Giant Squid Was Considered a Myth Until 2004 When One Was Photographed Alive",
        "Barreleye Fish Has a Completely Transparent Head With Rotating Eyes Inside",
        "The Immortal Jellyfish Literally Reverts to a Baby When It Gets Old",
        "Anglerfish: The Male Bites the Female and His Body Fuses Into Hers Forever",
        "Mantis Shrimp Can Punch With the Force of a Bullet and See Colors Humans Cannot",
        "An Octopus Held Its Breath for 4.5 Years Without Moving to Guard Her Eggs",
        "There Are More Undiscovered Species in the Deep Sea Than Stars in the Milky Way",
        "The Pressure at Mariana Trench Depths Would Crush a Human to Half Their Size",
        "There Is a Lake at the Bottom of the Ocean That Is So Dense Fish Die If They Touch It",
        "Deep Sea Fish Have Eyes That Work Like Telescopes to See in Total Darkness",
        "The Black Seadevil Lures Prey With a Light Produced by Bacteria Living Inside Its Head",
    ],

    # ── Body Science ───────────────────────────────────────────────────────
    # Cross-domain: medical horror + extreme survival + biological countdown
    "body_science": [
        "Your Body Starts Dissolving Itself Exactly 4 Minutes After Your Heart Stops",
        "The Human Eye Can Detect a Single Photon — The Smallest Particle of Light",
        "Your Stomach Lining Replaces Itself Completely Every 4 Days or It Would Digest Itself",
        "You Generate Enough Electricity in One Day to Power a Smartphone for 24 Hours",
        "The Appendix Is Not Useless — It Reboots Your Entire Gut Bacteria After an Infection",
        "Your Bones Are Being Dissolved and Rebuilt 24 Hours a Day Your Entire Life",
        "You Have More Bacterial Cells in Your Body Than Human Cells",
        "Your Brain Uses 20% of All Oxygen Despite Being Only 2% of Body Weight",
        "A Single Sneeze Fires at 100 MPH and Contains Enough Virus to Infect 150 People",
        "The Naegleria fowleri Amoeba Enters Your Nose and Eats Your Brain in 3 Days",
        "At 35,000 Feet the Outside Air Is So Thin Your Blood Would Boil Without a Pressurized Cabin",
        "The Human Body Produces Enough Heat in 30 Minutes to Boil Half a Liter of Water",
        "Cotard's Delusion Is a Real Condition Where Patients Are Convinced They Are Already Dead",
        "Exploding Head Syndrome Is a Real Medical Condition That Causes a Loud Boom in Your Sleep",
        "Your Body Replaces Every Single Atom You Are Made of Every 7 to 10 Years",
    ],

    # ── Alternate History ──────────────────────────────────────────────────
    # Cross-domain: cover-ups + impossible historical facts + dark what-ifs
    "alternate_history": [
        "In 1908, the US Government Classified This Discovery and No One Knows Why",
        "The Nazi Bell: Hitler Had Scientists Building a Machine That Bent Time",
        "The Phantom Time Hypothesis: 297 Years of History Were Simply Invented",
        "Tesla's Death Ray Was Real — the FBI Seized All His Research the Day He Died",
        "The Tartaria Conspiracy: A Global Empire Erased From Every History Book",
        "The Great Mud Flood: Entire Cities Were Built Over an Older Underground Civilization",
        "What If Rome Never Fell — We Would Have Landed on the Moon in 1000 AD",
        "The Library of Alexandria Wasn't Burned Down — It Was Dismantled on Purpose",
        "Operation Sea Spray: The US Government Secretly Sprayed Biological Agents on San Francisco",
        "MKUltra Was Real: The CIA Dosed US Citizens With LSD Without Their Knowledge for 20 Years",
        "The Tunguska Event in 1908 Flattened 2,000 Square Miles — and Left No Crater",
        "The Roanoke Colony Had One Clue Left: a Single Word Carved Into a Tree",
        "There Are 400+ Underground Cities in Turkey — One Housed 20,000 People Below Ground",
        "The Philadelphia Experiment: The US Navy Allegedly Made a Ship Invisible in 1943",
        "What If the Mongol Invasion of Europe Had Succeeded — We Would Still Be in the Dark Ages",
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
