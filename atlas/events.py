"""Events: the gigs, and the artist-to-room edges they reveal.

Why this module is the important one
------------------------------------
Two of the rubric's seven signals carry 40 of its 100 points — `show_frequency`
("how often does this music actually happen here?") and `artist_roster` ("what
share of the booked artists are recognized improvisers?") — and until now both
were human guesses, because the Atlas held no record of a single gig. Venues are
the nouns; gigs are the verbs.

Scraping venue calendars is the obvious way in and the worse one: a probe of 60
venue sites in this corpus found machine-readable events on 4% of them. Artist
pages are the better door. A working improviser keeps a tour list because it is
how they get an audience, that list names *other people's* rooms, and every line
of it is simultaneously evidence about a venue (something happened there) and an
artist-to-venue edge (this person played there). One scrape, two signals.

How it reads a page, most to least reliable
-------------------------------------------
1. **schema.org JSON-LD** `Event` / `MusicEvent` — unambiguous, so trusted.
2. **iCalendar** feeds — also structured.
3. **Text lines** like ``Oct 15: Elastic Arts, Chicago`` — how most working
   musicians actually publish dates. Heuristic, and labelled as such.

What it refuses to do
---------------------
* It does not invent a year. A line reading "Oct 15" does not say which October,
  so the year is inferred from context and the guess is recorded as
  `year_inferred: true` rather than presented as fact.
* It does not silently create venue links. A gig is matched to a venue in the
  corpus only on strong evidence, the evidence is stored, and anything weaker
  becomes a review candidate for a human.
* It never edits a score. Measured show frequency is offered as a comparison
  against the human estimate, never written over it.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}

# US state codes and a few common spellings, for pulling a region out of a
# free-text location like "Springfield, IL".
US_REGION_RE = re.compile(r",\s*([A-Z]{2})\b\s*$")

# Lines that look like dates but are not gigs.
NOT_A_GIG = re.compile(
    r"\b(master ?class|workshop|clinic|residency application|deadline|"
    r"out now|coming|release|released|available|pre-?order|album|record store)\b",
    re.I)


@dataclass
class Event:
    """One gig, as read from a source. `venue_id` is filled only on good evidence."""
    date: str | None                 # ISO yyyy-mm-dd when known
    raw: str                         # the source text, kept verbatim
    venue_name: str = ""
    city: str = ""
    region: str = ""
    country: str = ""
    lineup: str = ""
    source_url: str = ""
    artist_id: str = ""
    method: str = ""                 # jsonld | ics | text
    year_inferred: bool = False
    venue_id: str | None = None
    match_score: float = 0.0
    match_note: str = ""

    @property
    def id(self) -> str:
        key = f"{self.artist_id}|{self.date}|{self.venue_name}|{self.city}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


# --- date handling ----------------------------------------------------------
def infer_year(month: int, day: int, today: _dt.date | None = None,
               window_months: int = 3) -> tuple[str, bool]:
    """Turn a year-less date into ISO, guessing the year from context.

    Tour lists are written in the present tense: an undated "Oct 15" on a page
    read in August means this October, while "Feb 3" probably means next
    February. A short backward window keeps a gig that happened last week from
    jumping eleven months into the future.
    """
    today = today or _dt.date.today()
    for year in (today.year, today.year + 1, today.year - 1):
        try:
            cand = _dt.date(year, month, day)
        except ValueError:
            continue
        if cand >= today - _dt.timedelta(days=window_months * 30):
            return cand.isoformat(), True
    return f"{today.year:04d}-{month:02d}-{day:02d}", True


def parse_date_prefix(text: str, today: _dt.date | None = None):
    """Parse a leading date. Returns (iso, inferred, rest) or None."""
    t = text.strip()
    # 2026-10-15 ...
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s*[:\u2013\-]?\s*(.*)$", t)
    if m:
        y, mo, d, rest = m.groups()
        try:
            return _dt.date(int(y), int(mo), int(d)).isoformat(), False, rest
        except ValueError:
            return None
    # Oct 15, 2026: ... / Oct. 15 2026 - ... / October 15: ...
    m = re.match(
        r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s*,?\s*(\d{4}))?\s*[:\u2013\-]\s*(.*)$", t)
    if m:
        mon, day, year, rest = m.groups()
        mnum = MONTHS.get(mon.lower())
        if not mnum:
            return None
        day = int(day)
        if year:
            try:
                return _dt.date(int(year), mnum, day).isoformat(), False, rest
            except ValueError:
                return None
        iso, inferred = infer_year(mnum, day, today)
        return iso, inferred, rest
    return None


# --- location handling ------------------------------------------------------
def split_place(rest: str) -> tuple[str, str, str, str]:
    """Split "Elastic Arts, Chicago" into venue / city / region / lineup.

    Real-world shapes this has to survive:
        Elastic Arts, Chicago
        Dumb Records, Springfield, IL
        Front Yard (1346 Van Buren, St Paul): Nathan Hanson, Steve Hirsh
        The Backdoor, Quezon City
        Eau Claire, WI                      <- city only, no venue named
    """
    text = rest.strip().strip(".")
    lineup = ""

    # A colon after the location introduces the line-up.
    # Parentheses usually hold an address, so protect them from the split.
    protected = re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).replace(":", "\u0000") + ")", text)
    if ":" in protected:
        head, _, tail = protected.partition(":")
        text, lineup = head.strip(), tail.replace("\u0000", ":").strip()

    # Pull out a parenthetical: an address, and often the city too.
    paren = ""
    pm = re.search(r"\(([^)]*)\)", text)
    if pm:
        paren = pm.group(1).strip()
        text = (text[:pm.start()] + text[pm.end():]).strip().strip(",")

    region = ""
    rm = US_REGION_RE.search(text)
    if rm:
        region = rm.group(1)
        text = text[:rm.start()].strip()

    parts = [p.strip() for p in text.split(",") if p.strip()]
    venue = city = ""
    if len(parts) >= 2:
        venue, city = parts[0], parts[-1]
    elif len(parts) == 1:
        venue = parts[0]

    # If the venue name was followed only by an address parenthetical, the city
    # is usually the last component inside it.
    if paren and not city:
        pieces = [p.strip() for p in paren.split(",") if p.strip()]
        if pieces:
            city = pieces[-1]
    if not region:
        rm2 = US_REGION_RE.search(city)
        if rm2:
            region = rm2.group(1)
            city = city[:rm2.start()].strip()

    # "Eau Claire, WI" names a city with no venue: do not pretend otherwise.
    if venue and not city and region:
        city, venue = venue, ""

    return venue, city, region, lineup


# --- extraction strategies --------------------------------------------------
def events_from_jsonld(html: str, *, source_url: str, artist_id: str) -> list:
    out = []
    for block in re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            stack.extend(v for v in node.values() if isinstance(v, (list, dict)))
            types = node.get("@type") or ""
            types = types if isinstance(types, list) else [types]
            if not any(str(t).endswith("Event") for t in types):
                continue
            start = str(node.get("startDate") or "")[:10]
            loc = node.get("location") or {}
            loc = loc[0] if isinstance(loc, list) and loc else loc
            addr = (loc or {}).get("address") or {}
            if isinstance(addr, str):
                city, region, country = addr, "", ""
            else:
                city = addr.get("addressLocality") or ""
                region = addr.get("addressRegion") or ""
                country = addr.get("addressCountry") or ""
            out.append(Event(
                date=start or None, raw=json.dumps(node)[:300],
                venue_name=(loc or {}).get("name") or "",
                city=city, region=region, country=country,
                lineup=node.get("name") or "", source_url=source_url,
                artist_id=artist_id, method="jsonld"))
    return out


def events_from_ics(text: str, *, source_url: str, artist_id: str) -> list:
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        def field_of(name):
            m = re.search(rf"^{name}[^:]*:(.*)$", block, re.M)
            return m.group(1).strip() if m else ""
        raw_date = field_of("DTSTART")
        m = re.search(r"(\d{4})(\d{2})(\d{2})", raw_date)
        iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
        summary = field_of("SUMMARY")
        location = field_of("LOCATION").replace("\\,", ",")
        venue, city, region, _ = split_place(location) if location else ("", "", "", "")
        out.append(Event(date=iso, raw=f"{raw_date} {summary} {location}"[:300],
                         venue_name=venue or location, city=city, region=region,
                         lineup=summary, source_url=source_url,
                         artist_id=artist_id, method="ics"))
    return out


def visible_lines(html: str) -> list:
    """Strip tags, keeping one line per block element."""
    h = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6]|tr|section)>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    import html as _html
    h = _html.unescape(h)
    return [re.sub(r"\s+", " ", ln).strip() for ln in h.splitlines() if ln.strip()]


def events_from_text(html: str, *, source_url: str, artist_id: str,
                     today: _dt.date | None = None) -> list:
    """Read "Oct 15: Elastic Arts, Chicago" style listings."""
    out = []
    for line in visible_lines(html):
        if len(line) > 220:
            continue
        parsed = parse_date_prefix(line, today)
        if not parsed:
            continue
        iso, inferred, rest = parsed
        if not rest or len(rest) < 3:
            continue
        if NOT_A_GIG.search(rest):
            continue
        venue, city, region, lineup = split_place(rest)
        if not (venue or city):
            continue
        out.append(Event(date=iso, raw=line, venue_name=venue, city=city,
                         region=region, lineup=lineup, source_url=source_url,
                         artist_id=artist_id, method="text",
                         year_inferred=inferred))
    return out


def extract_events(body: str, *, source_url: str, artist_id: str,
                   today: _dt.date | None = None) -> list:
    """Try every strategy, best first, and stop at the first that finds gigs."""
    if "BEGIN:VCALENDAR" in body[:2000] or source_url.endswith(".ics"):
        return events_from_ics(body, source_url=source_url, artist_id=artist_id)
    found = events_from_jsonld(body, source_url=source_url, artist_id=artist_id)
    if found:
        return found
    return events_from_text(body, source_url=source_url, artist_id=artist_id,
                            today=today)


# --- matching gigs to venues in the corpus ----------------------------------
STOPWORDS = {"the", "a", "an", "at", "cafe", "café", "bar", "club", "gallery",
             "arts", "art", "center", "centre", "space", "theater", "theatre",
             "studios", "studio", "records", "record", "music", "hall", "room"}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def name_key(s: str) -> str:
    """Comparable form of a venue name, minus the words every venue shares."""
    words = [w for w in normalize(s).split() if w not in STOPWORDS]
    return " ".join(words) or normalize(s)


def match_venue(ev: Event, venues: list, *, threshold: float = 0.82) -> Event:
    """Attach a venue id when the evidence is strong enough, and say why.

    Name similarity alone is not enough — "The Bridge" exists in more than one
    city — so a city agreement is what turns a plausible name into a match.
    """
    if not ev.venue_name:
        ev.match_note = "no venue named in the listing"
        return ev

    target = name_key(ev.venue_name)
    ev_city = normalize(ev.city)
    best, best_score, best_why = None, 0.0, ""

    for v in venues:
        loc = v.get("location") or {}
        names = [v.get("name", "")] + list(v.get("aliases") or [])
        sim = max(difflib.SequenceMatcher(None, target, name_key(n)).ratio()
                  for n in names if n)
        v_city = normalize(loc.get("city") or "")
        city_ok = bool(ev_city and v_city and (
            ev_city == v_city or ev_city in v_city or v_city in ev_city))
        region_ok = bool(ev.region and (loc.get("region") or "").upper() == ev.region.upper())

        score = sim
        why = f"name similarity {sim:.2f}"
        if city_ok:
            score = min(1.0, sim + 0.15)
            why += f"; city matches ({loc.get('city')})"
        elif region_ok:
            score = min(1.0, sim + 0.05)
            why += f"; region matches ({loc.get('region')})"
        elif ev_city and v_city:
            # A confident name in the wrong city is usually a different room.
            score = sim * 0.6
            why += f"; city differs ({ev.city} vs {loc.get('city')})"

        if score > best_score:
            best, best_score, best_why = v, score, why

    ev.match_score = round(best_score, 3)
    if best and best_score >= threshold:
        ev.venue_id = best["id"]
        ev.match_note = best_why
    else:
        ev.match_note = (f"no confident match (best: "
                         f"{best.get('name') if best else 'none'}, {best_why})")
    return ev


def match_all(events: list, venues: list, **kw) -> list:
    return [match_venue(e, venues, **kw) for e in events]


# --- what the events tell us about a venue ----------------------------------
def observed_frequency(events: list, venue_id: str,
                       today: _dt.date | None = None,
                       months: int = 12) -> dict:
    """Count gigs we have actually observed at a venue in a window.

    This is the beginning of a *measured* `show_frequency`. It is deliberately
    returned as an observation, not written into the record: the Atlas currently
    watches only a handful of artists, so a low count means "we are not looking
    at much yet", not "little happens here". Reading it the other way round
    would let a sparse crawl quietly demote real venues.
    """
    today = today or _dt.date.today()
    start = today - _dt.timedelta(days=months * 30)
    seen = [e for e in events
            if e.venue_id == venue_id and e.date
            and start.isoformat() <= e.date <= (today + _dt.timedelta(days=365)).isoformat()]
    per_month = (len(seen) / months) if months else 0.0
    return {
        "venue_id": venue_id,
        "observed_events": len(seen),
        "window_months": months,
        "events_per_month": round(per_month, 2),
        "artists_seen": sorted({e.artist_id for e in seen if e.artist_id}),
        "caveat": ("Counts only gigs the Atlas has ingested, from a small number "
                   "of artist pages. A low count is a gap in our coverage, not "
                   "evidence against the venue."),
    }
