"""Generate the browsable directory: directory.json, DIRECTORY.md, and a
self-contained static index.html. No web framework, no build step, no server
required — open the HTML file or read the Markdown."""

from __future__ import annotations

import datetime as _dt
import html
import json
from pathlib import Path

from . import rubric, storage
from .model import enrich_venue

SITE = storage.ROOT / "site"


def _sorted_venues(venues: list) -> list:
    enriched = [enrich_venue(v) for v in venues]
    enriched.sort(key=lambda v: (-v.get("score", 0), v.get("name", "")))
    return enriched


def build_json(venues: list, musicians: list) -> dict:
    doc = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "rubric": {
            "signals": [
                {"key": s.key, "label": s.label, "max_points": s.max_points}
                for s in rubric.SIGNALS
            ],
            "tiers": [
                {"key": t.key, "label": t.label, "low": t.low, "high": t.high}
                for t in rubric.TIERS
            ],
        },
        "venue_count": len(venues),
        "musician_count": len(musicians),
        "venues": [],
        "musicians": [],
    }
    for v in _sorted_venues(venues):
        clean = {k: val for k, val in v.items() if not k.startswith("_")}
        clean["score_breakdown"] = rubric.explain(v.get("signals") or {})
        doc["venues"].append(clean)
    for m in sorted(musicians, key=lambda m: m.get("name", "")):
        doc["musicians"].append({k: val for k, val in m.items() if not k.startswith("_")})
    return doc


def build_markdown(venues: list, musicians: list) -> str:
    vs = _sorted_venues(venues)
    lines = []
    lines.append("# The Free Jazz Atlas — Directory\n")
    lines.append(f"_Generated {_dt.date.today().isoformat()} · "
                 f"{len(vs)} venues · {len(musicians)} musicians_\n")
    lines.append("Scores (0-100) measure **commitment** to free jazz / free "
                 "improvisation / avant-garde music. See "
                 "[docs/RUBRIC.md](docs/RUBRIC.md).\n")

    # Group by region (state/country) for geographic browsing.
    by_region: dict = {}
    for v in vs:
        loc = v.get("location") or {}
        region = loc.get("region") or loc.get("country") or "Unknown"
        by_region.setdefault(region, []).append(v)

    lines.append("## By score\n")
    lines.append("| Score | Tier | Venue | City | State | Type | Conf. |")
    lines.append("|------:|------|-------|------|-------|------|------:|")
    for v in vs:
        loc = v.get("location") or {}
        tier = rubric.tier_for_score(v["score"]).label
        conf = v.get("confidence")
        conf_s = f"{conf:.1f}" if isinstance(conf, (int, float)) else "?"
        name = v.get("name", "")
        web = v.get("website")
        name_cell = f"[{name}]({web})" if web else name
        lines.append(
            f"| {v['score']} | {tier} | {name_cell} | {loc.get('city','')} | "
            f"{loc.get('region','')} | {v.get('type','')} | {conf_s} |"
        )
    lines.append("")

    lines.append("## By place\n")
    for region in sorted(by_region):
        lines.append(f"### {region}\n")
        for v in by_region[region]:
            loc = v.get("location") or {}
            lines.append(
                f"- **{v.get('name','')}** ({loc.get('city','')}) — "
                f"score **{v['score']}** / {rubric.tier_for_score(v['score']).label}"
            )
        lines.append("")

    if musicians:
        lines.append("## Musicians (active this year)\n")
        for m in sorted(musicians, key=lambda m: m.get("name", "")):
            hb = m.get("home_base") or {}
            instr = ", ".join(m.get("instruments", []))
            active = "active" if m.get("active_this_year") else "unconfirmed"
            lines.append(
                f"- **{m.get('name','')}** — {instr} — "
                f"{hb.get('city','')} — {active}"
            )
        lines.append("")

    return "\n".join(lines)


def build_html(venues: list, musicians: list) -> str:
    vs = _sorted_venues(venues)
    data = build_json(venues, musicians)
    payload = json.dumps(data).replace("</", "<\\/")

    # A single self-contained page: filter/sort/search happen client-side over
    # the embedded JSON. No external requests (CSP-friendly).
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Free Jazz Atlas</title>
<style>
  :root {{ color-scheme: light dark; --bg:#faf9f7; --fg:#161514; --mut:#6b6660;
           --line:#e4e0d8; --card:#fff; --accent:#b4432b; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141312; --fg:#ece8e2; --mut:#9a938a; --line:#2c2a27;
             --card:#1d1b19; --accent:#e0654a; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          background:var(--bg); color:var(--fg); }}
  header {{ padding:2rem 1.25rem 1rem; border-bottom:1px solid var(--line); }}
  h1 {{ margin:0 0 .25rem; font-size:1.7rem; letter-spacing:-.02em; }}
  .sub {{ color:var(--mut); font-size:.95rem; }}
  .wrap {{ max-width:1050px; margin:0 auto; padding:1.25rem; }}
  .controls {{ display:flex; flex-wrap:wrap; gap:.6rem; margin:1rem 0; }}
  input, select {{ padding:.5rem .6rem; border:1px solid var(--line); border-radius:8px;
                   background:var(--card); color:var(--fg); font-size:.95rem; }}
  input[type=search] {{ flex:1; min-width:200px; }}
  .venue {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
            padding:1rem 1.1rem; margin:.7rem 0; }}
  .vhead {{ display:flex; align-items:baseline; gap:.7rem; flex-wrap:wrap; }}
  .vname {{ font-size:1.15rem; font-weight:650; }}
  .vname a {{ color:inherit; text-decoration:none; border-bottom:1px solid var(--line); }}
  .score {{ font-variant-numeric:tabular-nums; font-weight:700; font-size:1.15rem;
            color:var(--accent); }}
  .tier {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
           padding:.15rem .5rem; border-radius:999px; border:1px solid var(--line);
           color:var(--mut); }}
  .meta {{ color:var(--mut); font-size:.9rem; margin:.35rem 0; }}
  .bars {{ display:none; margin-top:.6rem; }}
  .venue.open .bars {{ display:block; }}
  .bar {{ display:grid; grid-template-columns:170px 1fr 46px; align-items:center;
          gap:.6rem; margin:.28rem 0; font-size:.82rem; }}
  .track {{ background:var(--line); border-radius:6px; height:9px; overflow:hidden; }}
  .fill {{ background:var(--accent); height:100%; }}
  .ev {{ grid-column:1 / -1; color:var(--mut); font-size:.78rem; margin:-.05rem 0 .3rem; }}
  .conf {{ font-size:.78rem; color:var(--mut); }}
  .toggle {{ cursor:pointer; user-select:none; font-size:.8rem; color:var(--accent); }}
  footer {{ color:var(--mut); font-size:.82rem; padding:2rem 1.25rem; text-align:center; }}
  a {{ color:var(--accent); }}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>The Free Jazz Atlas</h1>
  <div class="sub">A curated, weighted directory of venues committed to free jazz,
  free improvisation &amp; avant-garde music — and the musicians keeping them alive.</div>
</div></header>
<div class="wrap">
  <div class="controls">
    <input type="search" id="q" placeholder="Search venue, city, state…">
    <select id="tier"><option value="">All tiers</option></select>
    <select id="region"><option value="">All states/regions</option></select>
    <select id="sort">
      <option value="score">Sort: score</option>
      <option value="name">Sort: name</option>
      <option value="city">Sort: city</option>
    </select>
  </div>
  <div id="count" class="sub"></div>
  <div id="list"></div>
</div>
<footer>
  Scores measure <em>commitment</em>, not quality — see the rubric in the repo.
  Community-maintained &amp; correctable. Data CC0.
</footer>
<script id="data" type="application/json">{payload}</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const V = DATA.venues;
const tierLabel = Object.fromEntries(DATA.rubric.tiers.map(t => [t.key, t.label]));
const regions = [...new Set(V.map(v => (v.location||{{}}).region).filter(Boolean))].sort();
const tiers = DATA.rubric.tiers.map(t => t.key);
const rsel = document.getElementById('region');
regions.forEach(r => rsel.add(new Option(r, r)));
const tsel = document.getElementById('tier');
tiers.forEach(t => tsel.add(new Option(tierLabel[t], t)));

function esc(s) {{ return (s||'').replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}

function card(v) {{
  const loc = v.location || {{}};
  const web = v.website ? `<a href="${{esc(v.website)}}" target="_blank" rel="noopener">${{esc(v.name)}}</a>` : esc(v.name);
  const bars = (v.score_breakdown||[]).map(s => {{
    const pct = Math.round((s.value/s.max_value)*100);
    const ev = s.evidence ? `<div class="ev">${{esc(s.evidence)}}</div>` : '';
    return `<div class="bar"><span>${{esc(s.label)}}</span>`
      + `<span class="track"><span class="fill" style="width:${{pct}}%"></span></span>`
      + `<span>${{s.points}}/${{s.max_points}}</span></div>${{ev}}`;
  }}).join('');
  const conf = (typeof v.confidence === 'number') ? `confidence ${{v.confidence.toFixed(1)}}` : 'confidence ?';
  return `<div class="venue" data-tier="${{v.tier}}" data-region="${{esc(loc.region||'')}}"
    data-hay="${{esc((v.name+' '+(loc.city||'')+' '+(loc.region||'')+' '+(v.type||'')).toLowerCase())}}"
    data-score="${{v.score}}" data-name="${{esc(v.name)}}" data-city="${{esc(loc.city||'')}}">
    <div class="vhead">
      <span class="score">${{v.score}}</span>
      <span class="tier">${{esc(tierLabel[v.tier]||v.tier)}}</span>
      <span class="vname">${{web}}</span>
    </div>
    <div class="meta">${{esc(loc.city||'')}}${{loc.region?', '+esc(loc.region):''}} ·
      ${{esc(v.type||'')}} · ${{esc(v.operating_model||'')}} · ${{conf}}
      ${{v.active_this_year ? '· <b>active this year</b>' : ''}}</div>
    <span class="toggle">▸ why this score</span>
    <div class="bars">${{bars}}</div>
  </div>`;
}}

function render() {{
  const q = document.getElementById('q').value.toLowerCase().trim();
  const tier = document.getElementById('tier').value;
  const region = document.getElementById('region').value;
  const sort = document.getElementById('sort').value;
  let rows = V.slice();
  if (sort === 'name') rows.sort((a,b)=> (a.name||'').localeCompare(b.name||''));
  else if (sort === 'city') rows.sort((a,b)=> ((a.location||{{}}).city||'').localeCompare((b.location||{{}}).city||''));
  else rows.sort((a,b)=> b.score - a.score);
  const html = rows.map(card).join('');
  const list = document.getElementById('list');
  list.innerHTML = html;
  let shown = 0;
  list.querySelectorAll('.venue').forEach(el => {{
    const okQ = !q || el.dataset.hay.includes(q);
    const okT = !tier || el.dataset.tier === tier;
    const okR = !region || el.dataset.region === region;
    const show = okQ && okT && okR;
    el.style.display = show ? '' : 'none';
    if (show) shown++;
  }});
  document.getElementById('count').textContent = shown + ' of ' + V.length + ' venues';
}}
document.getElementById('list').addEventListener('click', e => {{
  if (e.target.classList.contains('toggle')) {{
    const v = e.target.closest('.venue'); v.classList.toggle('open');
    e.target.textContent = (v.classList.contains('open') ? '▾' : '▸') + ' why this score';
  }}
}});
['q','tier','region','sort'].forEach(id => document.getElementById(id).addEventListener('input', render));
render();
</script>
</body>
</html>
"""


def build_all(outdir: Path | None = None) -> dict:
    outdir = outdir or SITE
    outdir.mkdir(parents=True, exist_ok=True)
    venues = storage.load_venues()
    musicians = storage.load_musicians()

    doc = build_json(venues, musicians)
    (outdir / "directory.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (outdir / "index.html").write_text(build_html(venues, musicians), encoding="utf-8")
    (storage.ROOT / "DIRECTORY.md").write_text(build_markdown(venues, musicians), encoding="utf-8")
    return {
        "venues": len(venues),
        "musicians": len(musicians),
        "outdir": str(outdir),
    }
