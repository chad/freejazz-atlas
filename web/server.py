"""Avant Atlas — the web service.

Serves the generated multi-page static site and adds the parts a static site
cannot do: a contribution endpoint, a public moderation queue, and JSON APIs.

Two design decisions worth knowing:

1. **The site is built, not rendered per request.** `atlas build` produces every
   page as a file; this process just serves them. That means the public site is
   fast, cacheable, survives this process dying, and can be published anywhere
   (object storage, a CDN, a USB stick) without the server.

2. **Submissions must outlive the container.** A queue in a local file is fine
   on a workstation and useless on ephemeral infrastructure, where a redeploy
   silently eats every contribution. So when a GitHub token is configured, each
   submission is filed as an issue in the repo — durable, public, and already
   the place review happens. The local JSONL is kept as a mirror/fallback.

Run:  uvicorn web.server:app --host 0.0.0.0 --port ${PORT:-8000}
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

from fastapi import FastAPI, Form, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atlas import site as site_mod  # noqa: E402  (needs ROOT on the path)

SITE = ROOT / "site"
SUBMISSIONS = ROOT / "data" / "submissions"
PENDING = SUBMISSIONS / "pending.jsonl"

BASE_URL = os.environ.get("ATLAS_BASE_URL", site_mod.DEFAULT_BASE_URL).rstrip("/")
GITHUB_TOKEN = os.environ.get("ATLAS_GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("ATLAS_GITHUB_REPO", "")  # e.g. "chad/freejazz-atlas"

app = FastAPI(title="Avant Atlas", docs_url="/api/docs", redoc_url=None)


# --- startup ----------------------------------------------------------------
def ensure_site_built() -> None:
    """Build the site if it is missing, so a fresh checkout just works."""
    if (SITE / "index.html").exists():
        return
    from atlas import build as build_mod
    print("site/ not found — building it now...", flush=True)
    result = build_mod.build_all(base_url=BASE_URL)
    print(f"built {result['pages']} pages", flush=True)


@app.on_event("startup")
def _startup() -> None:
    ensure_site_built()
    try:
        SUBMISSIONS.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"warning: cannot create {SUBMISSIONS}: {e}", flush=True)
    if not (GITHUB_TOKEN and GITHUB_REPO):
        print("NOTE: no ATLAS_GITHUB_TOKEN/ATLAS_GITHUB_REPO configured — venue "
              "submissions will only be written to the local queue file. On "
              "ephemeral infrastructure they will be lost on redeploy.", flush=True)


def load_directory() -> dict:
    p = SITE / "directory.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"venues": [], "musicians": [], "venue_count": 0, "musician_count": 0}


# --- APIs -------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    d = load_directory()
    return {"ok": True, "venues": d.get("venue_count", 0),
            "musicians": d.get("musician_count", 0),
            "generated_at": d.get("generated_at")}


@app.get("/api/venues")
def api_venues(min_score: int = 0, country: str = "", tier: str = "",
               q: str = "", limit: int = 500):
    """Filtered venue list. Everything is already in memory; keep it simple."""
    out = []
    ql = q.lower().strip()
    for v in load_directory().get("venues", []):
        loc = v.get("location") or {}
        if v.get("score", 0) < min_score:
            continue
        if country and (loc.get("country") or "").upper() != country.upper():
            continue
        if tier and v.get("tier") != tier:
            continue
        if ql:
            hay = " ".join(str(x) for x in
                           (v.get("name"), loc.get("city"), loc.get("region"),
                            loc.get("country"), v.get("type"))).lower()
            if ql not in hay:
                continue
        out.append(v)
        if len(out) >= limit:
            break
    return JSONResponse(out)


@app.get("/api/venues/{venue_id}")
def api_venue(venue_id: str):
    for v in load_directory().get("venues", []):
        if v.get("id") == venue_id:
            return JSONResponse(v)
    return JSONResponse({"error": "not found", "id": venue_id}, status_code=404)


@app.get("/api/artists")
def api_artists():
    return JSONResponse(load_directory().get("musicians", []))


@app.get("/api/stats")
def api_stats():
    d = load_directory()
    venues = d.get("venues", [])
    tiers, countries = {}, {}
    for v in venues:
        tiers[v.get("tier")] = tiers.get(v.get("tier"), 0) + 1
        cc = (v.get("location") or {}).get("country")
        countries[cc] = countries.get(cc, 0) + 1
    return {
        "venue_count": d.get("venue_count"),
        "musician_count": d.get("musician_count"),
        "generated_at": d.get("generated_at"),
        "tiers": tiers,
        "countries": countries,
        "link_health": _link_health(venues),
    }


def _link_health(venues: list) -> dict:
    out = {}
    for v in venues:
        st = ((v.get("provenance") or {}).get("link_check") or {}).get("status", "unchecked")
        out[st] = out.get(st, 0) + 1
    return out


@app.get("/api/submissions")
def api_submissions():
    """Public, read-only view of the moderation queue. Transparency by default."""
    if not PENDING.exists():
        return []
    out = []
    for line in PENDING.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        rec.pop("submitter_contact", None)  # never republish contact details
        out.append(rec)
    return out


# --- submission form --------------------------------------------------------
def _page(title: str, body: str, path: str) -> str:
    return site_mod.page(base=BASE_URL, path=path, title=f"{title} | Avant Atlas",
                         description=("Add or correct a venue in Avant Atlas — the weighted "
                                      "directory of venues committed to free jazz, free "
                                      "improvisation and avant-garde music."),
                         body=body, nav_here="Add a venue")


FORM_CSS = """<style>
form.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:1.2rem 1.3rem;max-width:640px}
form.card label{display:block;margin:1.05rem 0 .3rem;font-size:.88rem}
form.card label:first-child{margin-top:0}
form.card input,form.card textarea,form.card select{width:100%;background:var(--bg);
 border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:.55rem .7rem;
 font:inherit;font-size:.95rem}
form.card textarea{min-height:96px;resize:vertical}
form.card .hint{font-size:.78rem;color:var(--mut);margin-top:.25rem}
form.card button{margin-top:1.5rem;background:var(--accent);color:#fff;border:0;
 border-radius:8px;padding:.65rem 1.3rem;font:inherit;font-weight:600;cursor:pointer}
form.card button:hover{background:var(--accent2)}
.req{color:var(--accent)}
</style>"""


@app.get("/submit", response_class=HTMLResponse)
def submit_form():
    body = f"""{FORM_CSS}
<header class="hero"><div class="wrap">
  <h1>Add or correct a venue</h1>
  <p class="sub">Know a place that genuinely hosts free jazz, free improvisation or
  avant-garde music? Add it. Spot a score that is wrong? Say so — the whole point of an
  explainable score is that you can argue with it.</p>
  <p class="sub">Every submission is reviewed by a human against the
  <a href="/rubric/">rubric</a> before it appears. <strong>Evidence is what makes review
  fast:</strong> a calendar link showing a monthly series does more than a paragraph of
  enthusiasm.</p>
</div></header>
<main><div class="wrap">
<form method="post" action="/submit" class="card">
  <label>Venue name <span class="req">*</span></label>
  <input name="venue_name" required maxlength="200">

  <label>City <span class="req">*</span></label>
  <input name="city" required maxlength="120">

  <label>State / region <span class="hint">two-letter code for US states, e.g. MO</span></label>
  <input name="region" maxlength="80">

  <label>Country <span class="hint">ISO two-letter code; defaults to US</span></label>
  <input name="country" value="US" maxlength="2">

  <label>Website or listings link</label>
  <input name="website" maxlength="400" placeholder="https://">

  <label>Is this a correction to an existing entry?
    <span class="hint">paste the Atlas URL if so</span></label>
  <input name="corrects" maxlength="300" placeholder="https://atlas.run.garden/venues/...">

  <label>Why does it belong here — or what did we get wrong? <span class="req">*</span></label>
  <textarea name="why" required placeholder="What music happens here, how often, and who plays? A named recurring series and specific improvisers count for a lot. If you are correcting a score, say which signal is wrong and why."></textarea>

  <label>Evidence links <span class="hint">calendars, past lineups, festival pages, reviews — one per line</span></label>
  <textarea name="evidence" placeholder="https://..."></textarea>

  <label>Your name <span class="hint">optional; credited in the record's provenance</span></label>
  <input name="submitter" maxlength="120">

  <label>You are a…</label>
  <select name="submitter_role">
    <option value="">(prefer not to say)</option>
    <option>artist / musician</option>
    <option>venue staff / booker</option>
    <option>promoter / organizer</option>
    <option>listener / fan</option>
  </select>

  <button type="submit">Submit for review</button>
</form>
</div></main>"""
    return _page("Add a venue", body, "/submit")


THANKS_TEMPLATE = """
<header class="hero"><div class="wrap">
  <h1>Thank you.</h1>
  <p class="sub">Your submission is in the review queue. A human checks each one against the
  rubric before it joins the Atlas, so it may take a little while to appear. If you left
  evidence links, that speeds it up a lot.</p>
  {tracking}
  <p style="margin-top:1.2rem"><a class="cta" href="/submit">Submit another</a>
    <a href="/" style="margin-left:.8rem">Back to the map →</a></p>
</div></header>
<main><div class="wrap">
  <p class="muted" style="font-size:.88rem;max-width:62ch">The queue is public: you can watch
  it at <a href="/api/submissions">/api/submissions</a>. Curation quality is the entire point
  of this project, and that only works if the curation is inspectable.</p>
</div></main>"""


def _file_github_issue(rec: dict) -> str:
    """File the submission as a GitHub issue. Returns the issue URL, or ''."""
    if not (GITHUB_TOKEN and GITHUB_REPO):
        return ""
    place = ", ".join(x for x in (rec["city"], rec["region"], rec["country"]) if x)
    lines = [
        f"**Venue:** {rec['venue_name']}",
        f"**Place:** {place}",
        f"**Website:** {rec['website'] or '_none given_'}",
    ]
    if rec.get("corrects"):
        lines.append(f"**Corrects:** {rec['corrects']}")
    lines += [
        "",
        "### Why it belongs / what is wrong",
        rec["why"],
    ]
    if rec.get("evidence"):
        lines += ["", "### Evidence", *[f"- {u}" for u in rec["evidence"]]]
    lines += [
        "",
        "---",
        f"Submitted via the web form at {rec['submitted_at']}"
        + (f" by {rec['submitter']}" if rec.get("submitter") else "")
        + (f" ({rec['submitter_role']})" if rec.get("submitter_role") else "")
        + ".",
        "",
        "_Reviewer checklist: verify the room exists and is active; set `type` and "
        "`operating_model`; rate the seven signals with evidence text and source URLs; "
        "set `confidence` honestly; run `atlas validate` and `atlas score --write`._",
    ]
    label = "correction" if rec.get("corrects") else "venue-submission"
    payload = json.dumps({
        "title": f"{'Correction' if rec.get('corrects') else 'New venue'}: "
                 f"{rec['venue_name']} ({place})",
        "body": "\n".join(lines),
        "labels": [label],
    }).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/issues",
        data=payload,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "AvantAtlas-submissions",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("html_url", "")
    except urllib.error.HTTPError as e:
        print(f"github issue failed: HTTP {e.code} {e.read()[:200]!r}", flush=True)
    except Exception as e:
        print(f"github issue failed: {type(e).__name__}: {e}", flush=True)
    return ""


@app.post("/submit", response_class=HTMLResponse)
def submit_post(
    venue_name: str = Form(...),
    city: str = Form(...),
    region: str = Form(""),
    country: str = Form("US"),
    website: str = Form(""),
    corrects: str = Form(""),
    why: str = Form(...),
    evidence: str = Form(""),
    submitter: str = Form(""),
    submitter_role: str = Form(""),
):
    rec = {
        "submitted_at": datetime.datetime.now(datetime.timezone.utc)
                                .isoformat(timespec="seconds"),
        "venue_name": venue_name.strip()[:200],
        "city": city.strip()[:120],
        "region": region.strip()[:80],
        "country": (re.sub(r"[^A-Za-z]", "", country)[:2] or "US").upper(),
        "website": website.strip()[:400],
        "corrects": corrects.strip()[:300],
        "why": why.strip()[:4000],
        "evidence": [e.strip() for e in evidence.splitlines() if e.strip()][:20],
        "submitter": submitter.strip()[:120],
        "submitter_role": submitter_role.strip()[:80],
        "status": "pending",
    }

    issue_url = _file_github_issue(rec)
    if issue_url:
        rec["issue_url"] = issue_url

    try:
        SUBMISSIONS.mkdir(parents=True, exist_ok=True)
        with PENDING.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        print(f"warning: could not append to local queue: {e}", flush=True)
        if not issue_url:
            # Both sinks failed: tell the truth rather than pretend it worked.
            return HTMLResponse(_page("Submission failed", """
<header class="hero"><div class="wrap"><h1>That did not save.</h1>
<p class="sub">Something went wrong on our side and your submission was not stored. Please
try again shortly, or open an issue on the repository directly — we would rather admit this
than quietly drop what you wrote.</p>
<p style="margin-top:1rem"><a class="cta" href="/submit">Try again</a></p>
</div></header><main><div class="wrap"></div></main>""", "/submit"), status_code=500)

    tracking = (f'<p class="sub">Tracked publicly as <a href="{issue_url}" target="_blank" '
                f'rel="noopener">an issue on GitHub</a> — follow it there.</p>'
                if issue_url else "")
    return _page("Thank you", THANKS_TEMPLATE.format(tracking=tracking), "/submit")


# --- static site ------------------------------------------------------------
@app.get("/DIRECTORY.md", response_class=PlainTextResponse)
def directory_md():
    p = ROOT / "DIRECTORY.md"
    if p.exists():
        return PlainTextResponse(p.read_text(), media_type="text/markdown; charset=utf-8")
    return PlainTextResponse("not built", status_code=404)


class SiteFiles(StaticFiles):
    """Static files plus a styled 404 that offers a way back in."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            notfound = SITE / "404.html"
            if notfound.exists():
                return FileResponse(str(notfound), status_code=404,
                                    media_type="text/html")
            raise


app.mount("/", SiteFiles(directory=str(SITE), html=True), name="site")
