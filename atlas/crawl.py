"""Ingestion engine: turn a public web source into a scored venue candidate.

This is the first working slice of the pipeline. Given a URL it:
  1. fetches the page (polite: identifies itself, respects a timeout),
  2. extracts visible text + metadata (name, description),
  3. approximates the rubric signals with transparent keyword heuristics,
  4. emits a candidate venue record (status "unconfirmed", low confidence)
     with the evidence snippets that drove each signal.

Design intent — the crawler NEVER invents a committed venue. It produces a
*candidate* with modest scores and low confidence, plus the evidence it saw,
for a human to verify and adjust. Curation quality comes from the human gate;
the crawler just does the legwork and the first-pass triage.

Re-crawl / update: `crawl_state.py` semantics are folded in here. Each crawl
records a content hash + timestamp in the candidate's provenance so a
re-crawler can detect "changed", "unchanged", or "gone" (HTTP error) and
refresh the active-this-year signal without a human re-reading every page.

The `requests` + `beautifulsoup4` deps are optional (extras: `crawl`). If they
are absent, `fetch()` raises a clear error but the rest of the toolkit runs.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field

from . import rubric

# --- Keyword lexicons (transparent, editable heuristics) --------------------
# These are deliberately simple and inspectable. They are a triage aid, not a
# judgement. Tune them in the open.
STRONG_TERMS = [
    "free jazz", "free improvisation", "free improvised", "avant-garde",
    "avant garde", "experimental music", "improvised music", "creative music",
    "new music", "adventurous music", "non-idiomatic", "sound art",
    "noise", "outsound", "out jazz", "spontaneous music",
]
MISSION_TERMS = [
    "artist-run", "artist run", "member-owned", "member owned", "volunteer-run",
    "volunteer run", "nonprofit", "non-profit", "501(c)(3)", "501c3",
    "collective", "diy", "cooperative", "co-op", "curated",
]
SERIES_TERMS = [
    "series", "festival", "residency", "concert series", "presents",
    "every week", "weekly", "monthly", "wednesday nights", "thursday nights",
]
LISTENING_TERMS = [
    "listening room", "listening bar", "seated", "attentive listening",
    "without the typical distractions", "no talking", "concert setting",
]
COMMERCIAL_TERMS = [
    "no cover", "happy hour", "sports", "brunch", "tourist", "cocktail lounge",
    "dance floor", "bottle service", "full bar and kitchen",
]

USER_AGENT = (
    "FreeJazzAtlasBot/0.1 (+https://github.com/freejazz-atlas/freejazz-atlas; "
    "respectful ingestion for a non-commercial music directory)"
)


@dataclass
class Fetched:
    url: str
    status: int
    text: str
    title: str = ""
    description: str = ""
    fetched_at: str = ""
    content_hash: str = ""


def fetch(url: str, timeout: int = 20) -> Fetched:
    """Fetch and extract text. Requires the `crawl` extra."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "The crawler needs the 'crawl' extra. Install with:\n"
            "  pip install -e '.[crawl]'"
        ) from e

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    description = ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta and meta.get("content"):
        description = meta["content"].strip()

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return Fetched(
        url=url,
        status=resp.status_code,
        text=text,
        title=title,
        description=description,
        fetched_at=_dt.date.today().isoformat(),
        content_hash=content_hash,
    )


def _count_hits(haystack: str, terms: list) -> list:
    hits = []
    low = haystack.lower()
    for t in terms:
        if t in low:
            hits.append(t)
    return hits


def _snippet(text: str, term: str, width: int = 120) -> str:
    low = text.lower()
    i = low.find(term)
    if i < 0:
        return ""
    start = max(0, i - width // 2)
    end = min(len(text), i + len(term) + width // 2)
    return ("..." if start else "") + text[start:end].strip() + ("..." if end < len(text) else "")


def signals_from_text(text: str, description: str = "") -> dict:
    """Approximate the rubric signals from page text. Transparent + capped.

    Every value is capped so the crawler alone can never mint a "cornerstone".
    Human verification is what unlocks the top of each signal's range.
    """
    body = (description + " " + text)
    strong = _count_hits(body, STRONG_TERMS)
    mission = _count_hits(body, MISSION_TERMS)
    series = _count_hits(body, SERIES_TERMS)
    listening = _count_hits(body, LISTENING_TERMS)
    commercial = _count_hits(body, COMMERCIAL_TERMS)

    def ev(terms_hit):
        for t in terms_hit:
            s = _snippet(body, t)
            if s:
                return f'matched "{t}": {s}'
        return f"matched terms: {', '.join(terms_hit)}" if terms_hit else ""

    # dedicated_series (cap 4 from crawler): needs both a series word AND a
    # strong genre term nearby to score above 1.
    ded = 0
    if strong and series:
        ded = min(4, 1 + len(strong))
    elif strong:
        ded = min(2, len(strong))
    ded = min(4, ded)

    # show_frequency (cap 3): weekly/monthly language bumps it.
    freq = 0
    if any(w in body.lower() for w in ("weekly", "every week", "nights")):
        freq = 3
    elif "monthly" in body.lower() or "series" in body.lower():
        freq = 2
    elif strong:
        freq = 1

    # artist_roster (cap 3): the crawler can't identify improvisers reliably
    # from one page, so it stays conservative.
    roster = min(3, len(strong)) if strong else 0

    # self_description (cap 5): straight from how many strong terms appear.
    selfdesc = min(5, len(strong))

    # operating_model (cap 5): mission terms up, commercial terms down.
    opmodel = min(5, len(mission)) - min(3, len(commercial))
    opmodel = max(0, opmodel)

    # community_reputation: crawler cannot judge this; leave for humans.
    reputation = 0

    # listening_room (cap 5).
    listen = min(5, 2 * len(listening)) if listening else 0

    return {
        "dedicated_series": {"value": ded, "evidence": ev(strong + series), "sources": []},
        "show_frequency": {"value": freq, "evidence": ev(series), "sources": []},
        "artist_roster": {"value": roster, "evidence": ev(strong), "sources": []},
        "self_description": {"value": selfdesc, "evidence": ev(strong), "sources": []},
        "operating_model": {"value": opmodel, "evidence": ev(mission + commercial), "sources": []},
        "community_reputation": {"value": reputation, "evidence": "requires human verification", "sources": []},
        "listening_room": {"value": listen, "evidence": ev(listening), "sources": []},
    }


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown-venue"


def candidate_from_fetch(f: Fetched, city: str = "", region: str = "",
                         country: str = "US") -> dict:
    """Build a venue candidate record from a fetch. Always low-confidence."""
    name = f.title.split("|")[0].split("—")[0].strip() or f.url
    signals = signals_from_text(f.text, f.description)
    score = rubric.score_from_signals(signals)
    tier = rubric.tier_for_score(score)
    return {
        "id": _slugify(name),
        "name": name,
        "status": "unconfirmed",
        "type": "dedicated_space",  # human should correct
        "location": {"city": city, "region": region, "country": country},
        "website": f.url,
        "active_this_year": None,
        "signals": signals,
        "score": score,
        "tier": tier.key,
        "confidence": 0.2,
        "provenance": {
            "added_by": "crawler:v0.1",
            "added_on": f.fetched_at,
            "source_urls": [f.url],
            "last_crawled": f.fetched_at,
            "last_content_hash": f.content_hash,
            "crawl_http_status": f.status,
            "needs_human_review": True,
        },
        "notes": (
            "AUTO-GENERATED CANDIDATE. Scores are a keyword-based first pass "
            "and are capped below 'cornerstone'. A human must verify the venue, "
            "correct type/operating_model, confirm the roster, and raise "
            "confidence before this is trusted."
        ),
    }


# --- Re-crawl / update -------------------------------------------------------
@dataclass
class RecrawlResult:
    url: str
    outcome: str  # "new" | "changed" | "unchanged" | "gone"
    old_hash: str = ""
    new_hash: str = ""
    http_status: int = 0
    notes: str = ""


def recrawl(existing: dict) -> RecrawlResult:
    """Re-fetch a venue's source and report what changed.

    Updates provenance in-place (last_crawled, last_content_hash) and flips
    status toward 'closed'/'dormant' hints when the page 404s. It does NOT
    silently rewrite the score — a content change flags the record for human
    re-review instead.
    """
    prov = existing.setdefault("provenance", {})
    url = (existing.get("website")
           or (prov.get("source_urls") or [None])[0])
    if not url:
        return RecrawlResult(url="", outcome="unchanged", notes="no source URL to re-crawl")

    old_hash = prov.get("last_content_hash", "")
    try:
        f = fetch(url)
    except Exception as e:  # network error, DNS gone, etc.
        prov["last_crawled"] = _dt.date.today().isoformat()
        prov["last_crawl_error"] = str(e)[:200]
        return RecrawlResult(url=url, outcome="gone", old_hash=old_hash,
                             http_status=0, notes=str(e)[:200])

    prov["last_crawled"] = f.fetched_at
    prov["last_content_hash"] = f.content_hash
    prov["crawl_http_status"] = f.status

    if f.status >= 400:
        existing.setdefault("_flags", []).append("source-returned-error")
        return RecrawlResult(url=url, outcome="gone", old_hash=old_hash,
                             new_hash=f.content_hash, http_status=f.status,
                             notes="page returned HTTP error; verify venue still exists")

    if not old_hash:
        return RecrawlResult(url=url, outcome="new", new_hash=f.content_hash,
                             http_status=f.status)
    if old_hash == f.content_hash:
        return RecrawlResult(url=url, outcome="unchanged", old_hash=old_hash,
                             new_hash=f.content_hash, http_status=f.status)

    prov["needs_human_review"] = True
    return RecrawlResult(url=url, outcome="changed", old_hash=old_hash,
                         new_hash=f.content_hash, http_status=f.status,
                         notes="content changed; flagged for human re-review")
