"""The Free Jazz Atlas — web app.

Serves the interactive directory (the self-contained static site the build step
produces) and adds a real backend: a contribution endpoint so artists and venues
can submit venues/updates into a moderation queue, plus JSON APIs.

Run:  uvicorn web.server:app --host 0.0.0.0 --port 8000
"""
import json
import datetime
import pathlib

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SUBMISSIONS = ROOT / "data" / "submissions"
SUBMISSIONS.mkdir(parents=True, exist_ok=True)
PENDING = SUBMISSIONS / "pending.jsonl"

app = FastAPI(title="The Free Jazz Atlas")


def load_directory():
    p = SITE / "directory.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"venues": [], "venue_count": 0, "musician_count": 0}


@app.get("/healthz")
def healthz():
    return {"ok": True, "venues": load_directory().get("venue_count", 0)}


@app.get("/api/venues")
def api_venues():
    return JSONResponse(load_directory().get("venues", []))


@app.get("/api/stats")
def api_stats():
    d = load_directory()
    return {"venue_count": d.get("venue_count"), "musician_count": d.get("musician_count")}


@app.get("/api/submissions")
def api_submissions():
    """Public, read-only view of the moderation queue (transparency)."""
    if not PENDING.exists():
        return []
    out = []
    for line in PENDING.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


PAGE_HEAD = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title} · The Free Jazz Atlas</title>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{font-family:ui-monospace,'JetBrains Mono',Menlo,monospace;background:#0a0c12;color:#f4f4f5;margin:0;line-height:1.6}}
.wrap{{max-width:680px;margin:0 auto;padding:40px 22px 80px}}
a{{color:#e05a6d}}
h1{{font-size:1.5rem;margin:.2em 0}}
.sub{{color:#a1a1aa;margin:0 0 2rem}}
label{{display:block;margin:1.1rem 0 .3rem;font-size:.85rem;color:#d4d4d8}}
input,textarea,select{{width:100%;background:#12151e;border:1px solid #2a2f3a;color:#f4f4f5;border-radius:8px;padding:.6rem .7rem;font:inherit}}
textarea{{min-height:90px;resize:vertical}}
.req{{color:#e05a6d}}
button{{margin-top:1.6rem;background:#e05a6d;color:#0a0c12;border:0;border-radius:8px;padding:.7rem 1.4rem;font:inherit;font-weight:600;cursor:pointer}}
.hint{{font-size:.75rem;color:#71717a;margin-top:.25rem}}
.back{{display:inline-block;margin-bottom:1.5rem;color:#a1a1aa;text-decoration:none}}
.card{{background:#12151e;border:1px solid #2a2f3a;border-radius:12px;padding:1.4rem 1.6rem}}
</style></head><body><div class=wrap>
<a class=back href="/">&larr; the directory</a>
"""
PAGE_FOOT = "</div></body></html>"

SUBMIT_FORM = PAGE_HEAD.format(title="Submit a venue") + """
<h1>Add a venue to the Atlas</h1>
<p class=sub>Know a place that genuinely hosts free jazz, free improvisation, or avant-garde
music? Add it. Every submission is reviewed before it appears, and the more evidence you
give, the faster and more accurately it can be scored. Artists and venue staff both welcome.</p>
<form method=post action="/submit" class=card>
  <label>Venue name <span class=req>*</span></label>
  <input name=venue_name required maxlength=200>
  <label>City <span class=req>*</span></label>
  <input name=city required maxlength=120>
  <label>State / region <span class=hint>(2-letter for US, e.g. MO)</span></label>
  <input name=region maxlength=80>
  <label>Country <span class=hint>(ISO code, default US)</span></label>
  <input name=country value=US maxlength=2>
  <label>Website or listings link</label>
  <input name=website maxlength=400 placeholder="https://">
  <label>Why does it belong here? <span class=req>*</span></label>
  <textarea name=why required placeholder="What kind of music does it host, how often, who plays there? Be specific — a dedicated series and named improvisers count for a lot."></textarea>
  <label>Evidence links <span class=hint>(calendars, past lineups, festival pages — one per line)</span></label>
  <textarea name=evidence placeholder="https://..."></textarea>
  <label>Your name</label>
  <input name=submitter maxlength=120>
  <label>You are a…</label>
  <select name=submitter_role>
    <option value="">(prefer not to say)</option>
    <option>artist / musician</option>
    <option>venue staff / booker</option>
    <option>promoter / organizer</option>
    <option>listener / fan</option>
  </select>
  <button type=submit>Submit for review</button>
</form>
""" + PAGE_FOOT

THANKYOU = PAGE_HEAD.format(title="Thank you") + """
<div class=card>
<h1>Thank you.</h1>
<p class=sub style="margin-bottom:0">Your submission is in the review queue. A human checks each
one against the weighting rubric before it joins the directory, so it may take a little while to
appear. If you left evidence links, that speeds it up. The Atlas is only as good as the people who
tend it — thank you for tending it.</p>
</div>
<p style="margin-top:1.5rem"><a href="/submit">Submit another</a> &nbsp;·&nbsp; <a href="/">Back to the directory</a></p>
""" + PAGE_FOOT


@app.get("/submit", response_class=HTMLResponse)
def submit_form():
    return SUBMIT_FORM


@app.post("/submit", response_class=HTMLResponse)
def submit_post(
    venue_name: str = Form(...),
    city: str = Form(...),
    region: str = Form(""),
    country: str = Form("US"),
    website: str = Form(""),
    why: str = Form(...),
    evidence: str = Form(""),
    submitter: str = Form(""),
    submitter_role: str = Form(""),
):
    rec = {
        "submitted_at": datetime.datetime.utcnow().isoformat() + "Z",
        "venue_name": venue_name.strip()[:200],
        "city": city.strip()[:120],
        "region": region.strip()[:80],
        "country": (country.strip() or "US")[:2].upper(),
        "website": website.strip()[:400],
        "why": why.strip()[:4000],
        "evidence": [e.strip() for e in evidence.splitlines() if e.strip()][:20],
        "submitter": submitter.strip()[:120],
        "submitter_role": submitter_role.strip()[:80],
        "status": "pending",
    }
    with PENDING.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return THANKYOU


# The interactive directory itself is the self-contained static site the build
# step produces. Mount it last so explicit routes above win.
app.mount("/", StaticFiles(directory=str(SITE), html=True), name="site")
