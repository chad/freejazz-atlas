"""Find where an artist publishes: their site, their socials, their dates.

The Atlas has 185 musicians and, for most of them, no way to learn anything new.
That is the bottleneck: without a URL there is nothing to re-check, nothing to
scrape, and no route from "this person exists" to "this person played here in
October". So before events can be ingested, every artist needs an address.

Bandcamp is the productive starting point for this music, because nearly every
release is there and artist profiles carry a `sites` block of the artist's own
outbound links — their website, Facebook, Instagram, and so on. Those links are
stated by the artist about themselves, which is the best provenance available.

A found website is then probed for the page that lists gigs. Working improvisers
label that page in a small number of predictable ways ("Coming Up", "Dates",
"Shows", "Calendar", "Tour"), and often just put it on the front page, which is
what `dates_url` records.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from . import linkcheck

# Social platforms worth recording, mapped to the key we store them under.
SOCIAL_HOSTS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "soundcloud.com": "soundcloud",
    "spotify.com": "spotify",
    "open.spotify.com": "spotify",
    "bandcamp.com": "bandcamp",
    "linktr.ee": "linktree",
    "patreon.com": "patreon",
    "tiktok.com": "tiktok",
    "bsky.app": "bluesky",
    "mastodon.social": "mastodon",
    "vimeo.com": "vimeo",
    "discogs.com": "discogs",
    "wikipedia.org": "wikipedia",
    "allaboutjazz.com": "allaboutjazz",
}

# Listing services. These are useful — sometimes they are the only place an
# artist's dates exist — but they are somebody else's site, so they must never be
# recorded as the artist's own website. Only their artist pages are dates
# sources; a link to one concert or one venue tells us nothing general.
AGGREGATOR_HOSTS = {
    "songkick.com": "songkick",
    "bandsintown.com": "bandsintown",
    "ra.co": "residentadvisor",
    "eventbrite.com": "eventbrite",
    "dice.fm": "dice",
    "ticketmaster.com": "ticketmaster",
    "setlist.fm": "setlistfm",
    "jambase.com": "jambase",
    "seetickets.com": "seetickets",
}
AGGREGATOR_ARTIST_PATH = re.compile(r"/(artists?|user)/", re.I)

# Paths that mean "this is one release on some site", not "this is a home page".
RELEASE_PATH = re.compile(r"/(album|track|releases?|product|merch|shop)/", re.I)

# Hosts that are never an artist's own presence.
IGNORE_HOSTS = re.compile(
    r"(bcbits|googleapis|gstatic|google\.|schema\.org|w3\.org|opengraphprotocol|"
    r"get\.bandcamp\.help|bandcamp\.com/help|paypal|apple\.com|amazon\.|"
    r"creativecommons|fonts\.|cdn\.|jquery|doubleclick|facebook\.com/tr)", re.I)

# Anchor text / URL fragments that mark a page listing gigs.
DATES_HINTS = [
    "coming up", "upcoming", "tour dates", "tourdates", "tour", "dates",
    "shows", "gigs", "calendar", "concerts", "performances", "live", "events",
    "schedule", "appearances",
]


def _host(url: str) -> str:
    try:
        h = urllib.parse.urlsplit(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except ValueError:
        return ""


def classify_link(url: str) -> tuple[str, str] | None:
    """Return ("social"|"aggregator"|"website", key), or None to ignore."""
    if not url or IGNORE_HOSTS.search(url):
        return None
    host = _host(url)
    if not host or "." not in host:
        return None
    for social_host, key in SOCIAL_HOSTS.items():
        if host == social_host or host.endswith("." + social_host):
            return ("social", key)
    if host.endswith(".bandcamp.com"):
        return ("social", "bandcamp")
    for agg_host, key in AGGREGATOR_HOSTS.items():
        if host == agg_host or host.endswith("." + agg_host):
            return ("aggregator", key)
    return ("website", host)


def links_from_bandcamp(html: str) -> dict:
    """Pull an artist's own outbound links out of their Bandcamp page.

    Bandcamp embeds the profile in a `data-blob` JSON attribute; the visible
    "sites" list is the fallback when that shape changes, which it periodically
    does.
    """
    found: dict = {"website": None, "socials": {}, "all": [], "website_note": ""}

    def offer(url: str):
        url = url.strip().rstrip("/,\"'")
        if not url.startswith("http"):
            return
        kind = classify_link(url)
        if not kind:
            return
        if url not in found["all"]:
            found["all"].append(url)
        if kind[0] == "social":
            found["socials"].setdefault(kind[1], url)
        elif kind[0] == "aggregator":
            # Keep only the artist's page on a listing service, and keep it as a
            # profile link — never as "their website".
            if AGGREGATOR_ARTIST_PATH.search(url):
                found["socials"].setdefault(kind[1], url)
        elif found["website"] is None:
            # A link to one album on a label's site is not the artist's home
            # page; fall back to that site's root, which usually is.
            if RELEASE_PATH.search(url):
                parts = urllib.parse.urlsplit(url)
                found["website"] = f"{parts.scheme}://{parts.netloc}/"
                found["website_note"] = f"derived from release link {url}"
            else:
                found["website"] = url

    # The data-blob holds the artist's configured site links.
    for blob in re.findall(r'data-blob="(.*?)"', html, re.S):
        import html as _html
        try:
            data = json.loads(_html.unescape(blob))
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("url", "uri", "href", "title_link"):
                    if isinstance(node.get(key), str):
                        offer(node[key])
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)

    for m in re.findall(r'href="(https?://[^"]+)"', html):
        offer(m)
    return found


def find_dates_url(html: str, base_url: str) -> tuple[str | None, str]:
    """Find the page on a site that lists gigs. Returns (url, why)."""
    # If the page we already have lists dates itself, that is the answer.
    from . import events as events_mod
    here = events_mod.extract_events(html, source_url=base_url, artist_id="")
    if len(here) >= 2:
        return base_url, f"this page already lists {len(here)} dated entries"

    best = None
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                                 html, re.S | re.I):
        label = re.sub(r"<[^>]+>", " ", text)
        label = re.sub(r"\s+", " ", label).strip().lower()
        target = href.lower()
        for hint in DATES_HINTS:
            if hint in label or hint in target:
                url = urllib.parse.urljoin(base_url, href)
                if _host(url) != _host(base_url):
                    continue  # off-site ticketing link, not their dates page
                rank = DATES_HINTS.index(hint)
                if best is None or rank < best[0]:
                    best = (rank, url, f'link labelled "{label or hint}"')
                break
    if best:
        return best[1], best[2]
    return None, "no dates page found"


def discover_for_artist(bandcamp_url: str, *, timeout: int = 20) -> dict:
    """Fetch a Bandcamp profile, then the artist's site, and report what exists."""
    out = {"bandcamp": bandcamp_url, "website": None, "socials": {},
           "dates_url": None, "dates_note": "", "errors": []}

    body = fetch_text(bandcamp_url, timeout=timeout)
    if body is None:
        out["errors"].append(f"could not fetch {bandcamp_url}")
        return out
    found = links_from_bandcamp(body)
    out["socials"] = found["socials"]
    out["socials"].setdefault("bandcamp", bandcamp_url)
    out["website"] = found["website"]

    if out["website"]:
        site = fetch_text(out["website"], timeout=timeout)
        if site is None:
            out["errors"].append(f"could not fetch {out['website']}")
        else:
            url, why = find_dates_url(site, out["website"])
            out["dates_url"], out["dates_note"] = url, why
    return out


class RateLimited(RuntimeError):
    """A host asked us to slow down.

    This is a fact about our behaviour, not about the artist being looked up.
    Reporting it as "no links found" would write our rudeness into the corpus as
    if it were a finding, so it propagates and stops the sweep instead.
    """


# Politeness. Guessing addresses means issuing several requests per artist, and
# 185 artists is enough traffic to be a nuisance to a service run for musicians.
# One request per host per interval, plus an on-disk cache so a re-run costs
# nothing, is the difference between research and abuse.
MIN_INTERVAL = 1.5          # seconds between requests to the same host
CACHE_TTL = 24 * 3600       # a day is plenty for "where does this artist live?"
_last_request: dict = {}
_host_lock = __import__("threading").Lock()


def _cache_path(url: str):
    """Where a fetched page is cached on disk."""
    import hashlib

    from . import storage
    d = storage.ROOT / ".atlas-cache" / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ".html")


def _lax_ssl():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _throttle(url: str) -> None:
    """Never hit the same host twice inside MIN_INTERVAL."""
    import time
    host = _host(url)
    with _host_lock:
        last = _last_request.get(host, 0.0)
        wait = MIN_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.time()


def fetch_text(url: str, timeout: int = 20, *, use_cache: bool = True) -> str | None:
    """Fetch a URL as text: cached, throttled, and loud about rate limits.

    Returns None when the page genuinely cannot be read, and raises
    `RateLimited` when the host is telling us to back off — those two outcomes
    mean completely different things and must not be collapsed.
    """
    import time
    import urllib.error
    import urllib.request

    cache = _cache_path(url)
    if use_cache and cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_TTL:
        return cache.read_text(encoding="utf-8", errors="replace")

    req = urllib.request.Request(url, headers={
        "User-Agent": linkcheck.BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,text/calendar,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Purpose": linkcheck.CONTACT_HEADER,
    })
    _throttle(url)
    last_exc = None
    for ctx in (None, _lax_ssl()):
        try:
            opener = linkcheck._opener_for(ctx)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read(1_500_000)
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, "replace")
                if use_cache:
                    try:
                        cache.write_text(text, encoding="utf-8")
                    except OSError:
                        pass
                return text
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimited(
                    f"{_host(url)} returned HTTP 429 (too many requests). "
                    f"Nothing was learned about this artist — back off and retry "
                    f"later; cached pages make the retry cheap.") from e
            last_exc = e
            break  # a 404 will not become a 200 by relaxing TLS
        except Exception as e:
            last_exc = e
            continue
    return None


# --- finding an artist's own Bandcamp page ----------------------------------
# A release URL is not an artist page. `mahakalamusic.bandcamp.com/album/sparks`
# belongs to the label, and following it for every credited musician would hand
# 150 artists the label's website and call it their own. Only a subdomain that
# actually corresponds to the artist's name is theirs.
LABEL_SUBDOMAINS = {"mahakalamusic"}


def _subdomain(url: str) -> str:
    host = _host(url)
    return host.split(".")[0] if host.endswith("bandcamp.com") else ""


def name_matches_subdomain(name: str, subdomain: str, cutoff: float = 0.8) -> bool:
    """Is this Bandcamp subdomain plausibly this artist's own?

    Artists name their pages after themselves in predictable ways: "Eri
    Yamamoto" -> eriyamamoto, "Dave Sewelson" -> sewelson (surname only),
    "Ava Mendoza" -> avamendozamusic (with a suffix).
    """
    import difflib

    if not subdomain or subdomain in LABEL_SUBDOMAINS:
        return False
    sub = re.sub(r"(music|official|band|sounds?|drums?)$", "", subdomain.lower())
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in name.split()]
    parts = [p for p in parts if p]
    if not parts:
        return False
    full = "".join(parts)
    if sub == full or sub == parts[-1]:
        return True
    # Surname plus initial, or first name plus surname in either order.
    variants = {full, parts[-1], "".join(reversed(parts)),
                (parts[0][0] + parts[-1]) if len(parts) > 1 else full}
    if sub in variants:
        return True
    return difflib.SequenceMatcher(None, sub, full).ratio() >= cutoff


def guess_bandcamp(musician: dict) -> str | None:
    """Find the artist's own Bandcamp page from their record, if it is there.

    Looks only at URLs already recorded on the artist \u2014 this proposes nothing
    and fetches nothing, so it cannot invent a page that does not exist.
    """
    name = musician.get("name") or ""
    urls = list((musician.get("provenance") or {}).get("source_urls") or [])
    urls += [musician.get("website") or ""]
    for u in urls:
        sub = _subdomain(u)
        if sub and name_matches_subdomain(name, sub):
            return f"https://{sub}.bandcamp.com"
    return None


def bandcamp_candidates(name: str) -> list:
    """Plausible Bandcamp subdomains for an artist name, best guess first."""
    parts = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in name.split()]
    parts = [p for p in parts if p]
    if not parts:
        return []
    full = "".join(parts)
    out = [full, full + "music"]
    if len(parts) > 1:
        out += [parts[-1], parts[-1] + "music", parts[0] + parts[-1] + "music"]
    seen, uniq = set(), []
    for s in out:
        if len(s) >= 4 and s not in seen and s not in LABEL_SUBDOMAINS:
            seen.add(s)
            uniq.append(s)
    return [f"https://{s}.bandcamp.com" for s in uniq[:4]]


def page_band_name(html: str) -> str:
    """The artist name Bandcamp itself puts on the page."""
    for pat in (r'<meta property="og:site_name" content="([^"]+)"',
                r'<meta name="title" content="([^"|]+)',
                r"<title>([^<|]+)"):
        m = re.search(pat, html, re.I)
        if m:
            return re.sub(r"\s*\|.*$", "", m.group(1)).strip()
    return ""


def probe_bandcamp(name: str, *, timeout: int = 15, cutoff: float = 0.86):
    """Guess an artist's Bandcamp page and *verify* it before believing it.

    Guessing a URL is cheap and often right; recording a guess without checking
    is how a directory ends up asserting that one musician is another. So each
    candidate is fetched and the name Bandcamp prints on the page is compared
    with the name we hold. Returns (url, evidence) or (None, reason).
    """
    import difflib

    for url in bandcamp_candidates(name):
        body = fetch_text(url, timeout=timeout)
        if body is None:
            continue
        printed = page_band_name(body)
        if not printed:
            continue
        ratio = difflib.SequenceMatcher(None, printed.lower(), name.lower()).ratio()
        if ratio >= cutoff:
            return url, f'page is titled "{printed}" (match {ratio:.2f})'
        # A page exists but belongs to somebody else; stop guessing this stem.
        return None, f'{url} exists but is "{printed}", not {name}'
    return None, "no Bandcamp page found at the obvious addresses"
