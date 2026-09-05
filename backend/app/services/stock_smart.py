"""Quran-friendly Smart Search for online background VIDEO queries.

Keeps the user's exact query first, then adds a small set of cinematic /
peaceful variations. Scoring prefers calm nature/sky/architecture footage
and deprioritizes busy/people-heavy clips without dropping them.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Exact-match topics → extra queries (exact user text is always prepended).
# Keep this list short: search() only fires a few API requests.
TOPIC_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "ocean": ("cinematic ocean", "peaceful sea", "moody coastline"),
    "sea": ("cinematic ocean", "peaceful sea", "calm shoreline"),
    "waves": ("slow ocean waves", "peaceful sea", "calm shoreline"),
    "sunset": ("cinematic sunset", "ocean sunset", "peaceful sunset landscape"),
    "sunrise": ("cinematic sunrise", "mountains sunrise", "peaceful sunrise"),
    "clouds": ("moody clouds", "cinematic cloudy sky", "overcast landscape"),
    "sky": ("cinematic cloudy sky", "moody clouds", "overcast landscape"),
    "night sky": ("starry night sky", "stars timelapse", "peaceful night sky"),
    "stars": ("starry night sky", "stars timelapse", "cinematic night sky"),
    "moon": ("moon clouds", "peaceful night sky", "cinematic moon"),
    "mountains": ("cinematic mountains", "foggy mountains", "mountain lake"),
    "cliffs": ("cinematic cliffs", "coastal cliffs", "foggy mountains"),
    "lake": ("cinematic lake", "mountain lake", "peaceful lake"),
    "coast": ("moody coastline", "calm shoreline", "cinematic ocean"),
    "shore": ("calm shoreline", "moody coastline", "peaceful sea"),
    "aerial": ("cinematic aerial landscape", "aerial mountains", "aerial coastline"),
    "fog": ("foggy mountains", "misty forest", "misty valley"),
    "forest": ("peaceful forest", "misty forest", "cinematic forest"),
    "rain": ("gentle rain", "cinematic rain", "overcast landscape"),
    "waterfall": ("cinematic waterfall", "peaceful waterfall", "forest waterfall"),
    "desert": ("cinematic desert", "desert sunset", "peaceful dunes"),
    "valley": ("peaceful valley", "foggy mountains", "cinematic valley"),
    "nature": ("cinematic nature", "peaceful nature landscape", "aerial scenery"),
    "space": ("earth from space", "cinematic galaxy", "earth from space night"),
    "earth": ("earth from space", "cinematic earth", "earth from space night"),
    "mosque": ("mosque exterior", "mosque sunset", "mosque architecture"),
    "masjid": ("mosque exterior", "mosque sunset", "mosque architecture"),
    "islamic architecture": ("mosque architecture", "mosque exterior", "mosque sunset"),
}

# Custom-query extras that keep the user's modifiers (never collapse to the topic).
_STORMY = ("storm", "stormy", "dark", "rough", "angry", "violent", "dramatic")

POSITIVE_TERMS = (
    "peaceful", "calm", "slow", "gentle", "cinematic", "aerial", "drone",
    "sunset", "sunrise", "mist", "misty", "fog", "foggy", "starry", "stars",
    "moon",     "mosque", "islamic", "architecture", "ocean", "sea", "wave",
    "clouds", "sky", "mountain", "forest", "rain", "waterfall", "desert",
    "dune", "nature", "space", "earth", "landscape", "timelapse", "time-lapse",
    "night", "silhouette", "ambient", "serene", "tranquil", "smooth",
    "milky way", "galaxy", "horizon", "lake", "river", "coast", "shore",
    "valley", "cliff", "overcast",
)

NEGATIVE_TERMS = (
    "crowd", "crowded", "people", "person", "talking", "interview", "dance",
    "dancing", "party", "sport", "soccer", "football", "basketball", "action",
    "war", "protest", "traffic", "street", "urban", "logo", "vlog", "selfie",
    "workout", "fight", "boxing", "concert", "festival", "laughing", "speaking",
    "portrait", "tourist", "shopping", "cooking", "explosion",
    "race", "running", "city street", "close up", "close-up",
    "drive", "driving", "neon", "hiker", "hiking", "camping", "reading",
)

MAX_QUERIES = 4


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _find_topic(q: str) -> str | None:
    for topic in sorted(TOPIC_EXPANSIONS, key=len, reverse=True):
        if topic == q:
            return topic
        if re.search(rf"(^|[\s-]){re.escape(topic)}([\s-]|$)", q):
            return topic
    return None


def _has_word(q: str, word: str) -> bool:
    return bool(re.search(rf"(^|[\s-]){re.escape(word)}([\s-]|$)", q))


def _prefix(q: str, word: str) -> str:
    if _has_word(q, word):
        return q
    return f"{word} {q}"


def _custom_extra(q: str, topic: str | None) -> str:
    stormy = any(_has_word(q, w) for w in _STORMY)
    if topic in ("ocean", "sea", "waves"):
        if stormy:
            return "dark ocean waves" if q != "dark ocean waves" else "dramatic sea"
        return "slow ocean waves" if "wave" not in q else "peaceful sea"
    if topic in ("clouds", "sky"):
        return "slow moving clouds"
    if topic == "mountains":
        return "misty mountains"
    if topic in ("night sky", "stars", "moon"):
        return "starry night sky" if "star" not in q else "stars timelapse"
    if topic == "rain":
        return "gentle rain" if not stormy else "rain on window"
    if topic in ("mosque", "masjid", "islamic architecture"):
        return "mosque sunset" if "sunset" not in q else "mosque silhouette"
    if topic == "forest":
        return "misty forest"
    if topic == "desert":
        return "desert dunes" if "dune" not in q else "desert sunset"
    if topic == "sunset":
        return "cinematic sunset"
    if topic == "sunrise":
        return "cinematic sunrise"
    if topic in ("space", "earth"):
        return "earth from space"
    if topic == "nature":
        return "peaceful nature landscape"
    if topic == "waterfall":
        return "peaceful waterfall"
    if topic == "fog":
        return "misty mountains"
    if "peaceful" not in q and "calm" not in q:
        return _prefix(q, "peaceful")
    return _prefix(q, "slow")


def expand_video_queries(query: str, max_queries: int = MAX_QUERIES) -> list[str]:
    """Return the exact user query first, then up to max_queries-1 variations."""
    q = _norm(query)
    if not q:
        return []

    out: list[str] = []

    def add(text: str) -> None:
        text = _norm(text)
        if text and text not in out:
            out.append(text)

    add(q)
    if len(out) >= max_queries:
        return out[:max_queries]

    topic = _find_topic(q)
    if topic and topic == q:
        for extra in TOPIC_EXPANSIONS[topic]:
            add(extra)
            if len(out) >= max_queries:
                break
        return out[:max_queries]

    # Custom / modified query: never replace or reduce to the bare topic.
    add(_prefix(q, "cinematic"))
    if len(out) >= max_queries:
        return out[:max_queries]
    add(_custom_extra(q, topic))
    return out[:max_queries]


def tags_from_pexels_video(video: dict[str, Any]) -> str:
    """Derive searchable words from the Pexels video page slug."""
    url = video.get("url") or ""
    path = urlparse(str(url)).path.strip("/")
    if not path:
        return ""
    slug = path.split("/")[-1]
    slug = re.sub(r"-?\d+$", "", slug).replace("-", " ").strip()
    return slug


def suitability_bucket(item: dict[str, Any], user_query: str = "") -> int:
    """0 = preferred Quran background, 1 = neutral, 2 = deprioritize.

    Never filters items out.
    """
    blob = " ".join(
        str(item.get(k) or "")
        for k in ("tags", "name")
    ).lower()
    qn = _norm(user_query)

    def count(terms: tuple[str, ...]) -> int:
        n = 0
        for term in terms:
            if qn and (term == qn or _has_word(qn, term)):
                continue  # don't penalize/reward the user's own words twice
            if " " in term:
                if term in blob:
                    n += 1
            elif re.search(rf"\b{re.escape(term)}\b", blob):
                n += 1
        return n

    pos = count(POSITIVE_TERMS)
    neg = count(NEGATIVE_TERMS)
    if neg >= 2 or (neg >= 1 and pos == 0):
        return 2
    if pos >= 1 and neg == 0:
        return 0
    return 1


def resolution_score(item: dict[str, Any]) -> int:
    w = item.get("width") or 0
    h = item.get("height") or 0
    try:
        return int(w) * int(h)
    except (TypeError, ValueError):
        return 0
