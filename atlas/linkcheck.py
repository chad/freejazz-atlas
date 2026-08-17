"""Link health: is the evidence still reachable?

A directory of real-world rooms rots. Venues close, domains lapse, a beloved
loft becomes a parking garage. The rubric's `active_this_year` claim is only
honest if *something* keeps checking, so this module checks the one thing that
is cheap to check automatically: whether the URLs we cite still resolve.

It deliberately distinguishes **dead** from **blocked**. A 403 from Cloudflare
or a 429 from a rate limiter tells us about the bot defences, not the venue —
treating those as "gone" would quietly delete real places from the Atlas. Only
404/410 and hard DNS failures are evidence of disappearance, and even then the
result is a flag for a human, never an automatic deletion.

Uses the standard library so the core toolkit keeps its one dependency.
"""

from __future__ import annotations

import concurrent.futures
import datetime as _dt
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Some venue sites sit behind bot defences that reject an honest crawler UA but
# serve a browser. We are checking liveness, not harvesting content, so we
# present a browser UA and identify the project in a custom header instead.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
CONTACT_HEADER = "AvantAtlas link-health check (non-commercial music directory)"

# Statuses, most to least reassuring.
OK = "ok"                    # 2xx
BLOCKED = "blocked"          # 401/403/405/429 — bot defence, venue probably fine
ERROR = "error"              # 5xx — site broken today, may be fine tomorrow
DEAD = "dead"                # 404/410 — the cited page is gone
UNREACHABLE = "unreachable"  # DNS/TLS/timeout — domain may be gone
SKIPPED = "skipped"          # no URL to check

# Platforms that deliberately cloak from non-browser clients, usually with a
# 400 or a login wall. A bad status from these says nothing about the venue, so
# it must not be read as "gone". Many DIY spaces have no site but a Facebook
# page, so this is a large slice of the corpus.
SOCIAL_HOSTS = {
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "x.com", "www.twitter.com", "www.x.com",
    "tiktok.com", "www.tiktok.com", "linktr.ee",
}


class _AllRedirects(urllib.request.HTTPRedirectHandler):
    """Follow 307/308 as well as the classic 301/302/303.

    Python's stdlib handler ignored 308 before 3.11, which made a permanently
    moved venue site look like an error. Several real venues in the corpus were
    mis-flagged for exactly this reason.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The stdlib whitelists 301/302/303/307 here and raises on anything
        # else, so 308 has to be normalised before it reaches that check.
        if code == 308:
            code = 307
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_307(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, code, msg, headers)

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, code, msg, headers)


_OPENER = urllib.request.build_opener(_AllRedirects())


def _opener_for(ctx):
    """An opener that follows 307/308 and uses the given TLS context."""
    if ctx is None:
        return _OPENER
    return urllib.request.build_opener(_AllRedirects(),
                                      urllib.request.HTTPSHandler(context=ctx))


def _alternates(url: str) -> list:
    """Plausible variants of a URL, for when the exact form fails.

    Small-venue hosting is inconsistent: bare domains that only answer on www,
    www domains that only answer bare, sites still on plain HTTP, and servers
    whose TLS an older client cannot negotiate. Trying the obvious variants
    turns a lot of false "unreachable" verdicts into a correct final_url.
    """
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return []
    if not p.netloc:
        return []
    out = []
    host = p.netloc
    swapped = host[4:] if host.startswith("www.") else "www." + host
    for scheme in (p.scheme or "https", "http" if (p.scheme or "https") == "https" else "https"):
        for h in (host, swapped):
            cand = urllib.parse.urlunsplit((scheme, h, p.path, p.query, ""))
            if cand != url and cand not in out:
                out.append(cand)
    return out


@dataclass
class LinkResult:
    url: str
    status: str
    http: int = 0
    final_url: str = ""
    detail: str = ""

    @property
    def needs_attention(self) -> bool:
        return self.status in (DEAD, UNREACHABLE, ERROR)


def _classify(code: int, url: str = "") -> str:
    if 200 <= code < 300:
        return OK
    host = ""
    if url:
        try:
            host = urllib.parse.urlsplit(url).netloc.lower()
        except ValueError:
            host = ""
    if host in SOCIAL_HOSTS:
        # Anything short of a 2xx from a cloaking platform is a bot defence.
        return BLOCKED
    if code in (401, 403, 405, 429):
        return BLOCKED
    if code in (404, 410):
        return DEAD
    if code >= 500:
        return ERROR
    return ERROR


def _fetch_once(url: str, timeout: int, ctx) -> LinkResult:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Purpose": CONTACT_HEADER,
        },
    )
    with _opener_for(ctx).open(req, timeout=timeout) as resp:
        resp.read(2048)  # touch the body; some servers only then commit
        final = resp.geturl()
        return LinkResult(url=url, status=_classify(resp.status, final),
                          http=resp.status,
                          final_url=final if final != url else "")


def _try(url: str, timeout: int, insecure_retry: bool) -> LinkResult:
    """One URL, with a TLS-relaxed second attempt. No variant guessing."""
    try:
        return _fetch_once(url, timeout, None)
    except urllib.error.HTTPError as e:
        return LinkResult(url=url, status=_classify(e.code, url), http=e.code,
                          detail=f"HTTP {e.code}")
    except Exception as e:
        # A surprising number of small-venue sites have expired, misissued, or
        # simply old-protocol certificates. That is a TLS problem, not a
        # closure, so retry unverified purely to answer "is anything there?".
        if insecure_retry:
            lax = ssl.create_default_context()
            lax.check_hostname = False
            lax.verify_mode = ssl.CERT_NONE
            try:
                r = _fetch_once(url, timeout, lax)
                r.detail = "reachable only with TLS verification disabled"
                return r
            except urllib.error.HTTPError as e2:
                return LinkResult(url=url, status=_classify(e2.code, url), http=e2.code,
                                  detail=f"HTTP {e2.code} (TLS verification off)")
            except Exception as e2:
                e = e2

    # A TLS *negotiation* failure means this checker is too old for the server,
    # not that the venue vanished. Saying "unreachable" there would put a false
    # closure warning on a perfectly healthy venue page, so it is reported as
    # "we could not check" instead.
        msg = str(e)
        if any(t in msg for t in ("ALERT_PROTOCOL_VERSION", "UNSUPPORTED_PROTOCOL",
                                  "ALERT_INTERNAL_ERROR", "ALERT_HANDSHAKE_FAILURE",
                                  "SSLV3_ALERT_HANDSHAKE_FAILURE", "NO_PROTOCOLS_AVAILABLE")):
            return LinkResult(url=url, status=BLOCKED,
                              detail="TLS negotiation failed — this checker's TLS stack is "
                                     "older than the server requires; not evidence of closure")
        return LinkResult(url=url, status=UNREACHABLE,
                          detail=f"{type(e).__name__}: {msg[:120]}")


def check_url(url: str, timeout: int = 15, insecure_retry: bool = True) -> LinkResult:
    """Fetch just enough of a URL to know whether it is still there.

    If the exact URL fails, try the obvious host variants before declaring it
    unreachable, and report the variant that worked as `final_url` so the record
    can be corrected rather than merely flagged.
    """
    if not url:
        return LinkResult(url="", status=SKIPPED, detail="no URL")

    first = _try(url, timeout, insecure_retry)
    if first.status in (OK, BLOCKED, DEAD):
        return first

    for alt in _alternates(url):
        r = _try(alt, timeout, insecure_retry)
        if r.status == OK:
            r.url = url
            r.final_url = r.final_url or alt
            r.detail = f"original URL failed ({first.detail or first.status}); " \
                       f"this variant works"
            return r
    return first


def check_many(urls: list, workers: int = 16, timeout: int = 15) -> dict:
    """Check many URLs concurrently. Returns {url: LinkResult}."""
    uniq = [u for u in dict.fromkeys(urls) if u]
    out = {}
    if not uniq:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_url, u, timeout): u for u in uniq}
        for fut in concurrent.futures.as_completed(futures):
            u = futures[fut]
            try:
                out[u] = fut.result()
            except Exception as e:  # pragma: no cover - defensive
                out[u] = LinkResult(url=u, status=UNREACHABLE, detail=str(e)[:120])
    return out


def record_on_venue(venue: dict, result: LinkResult) -> None:
    """Write the check into the venue's provenance (no score side effects).

    Link health never silently rewrites a score or a status. A dead link raises
    `needs_human_review`, which is what puts the venue in front of a person.
    """
    prov = venue.setdefault("provenance", {})
    entry = {
        "checked": _dt.date.today().isoformat(),
        "status": result.status,
    }
    if result.http:
        entry["http"] = result.http
    if result.final_url:
        entry["final_url"] = result.final_url
    if result.detail:
        entry["detail"] = result.detail
    prov["link_check"] = entry
    if result.status in (DEAD, UNREACHABLE):
        prov["needs_human_review"] = True
