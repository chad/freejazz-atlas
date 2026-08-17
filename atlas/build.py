"""Generate the browsable directory: directory.json, DIRECTORY.md, and a real
multi-page static site (see atlas/site.py). No web framework, no build step
beyond `atlas build`, no server required.

The single-file `index.html` this module used to emit is still available via
`build_html()` and `atlas build --single-page`, because a self-contained,
offline-readable artifact is genuinely useful (archive it, email it, open it on
a plane). It is no longer the website: one URL for 263 venues meant nobody
searching for "free jazz in Lisbon" could ever find us.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
import os
from pathlib import Path

from . import rubric, site as site_mod, storage
from .model import enrich_venue

SITE = storage.ROOT / "site"


def _sorted_venues(venues: list) -> list:
    enriched = [enrich_venue(v) for v in venues]
    enriched.sort(key=lambda v: (-v.get("score", 0), v.get("name", "")))
    return enriched


def build_json(venues: list, musicians: list, events: list | None = None) -> dict:
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
        "event_count": len(events or []),
        "venues": [],
        "musicians": [],
        "events": list(events or []),
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
    lines.append("# Avant Atlas — Directory\n")
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
<title>Avant Atlas</title>
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
  #map {{ height:62vh; min-height:380px; border:1px solid var(--line); border-radius:12px; margin:1rem 0; z-index:0; }}
  .maplegend {{ display:flex; gap:.9rem; flex-wrap:wrap; font-size:.78rem; color:var(--mut); margin:-.3rem 0 .3rem; }}
  .maplegend span {{ display:inline-flex; align-items:center; gap:.35rem; }}
  .dot {{ width:11px; height:11px; border-radius:50%; display:inline-block; }}
  .artistbar {{ position:relative; margin-top:.9rem; max-width:520px; }}
  .artistbar input {{ width:100%; padding:.55rem .7rem; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); font-size:.95rem; }}
  .artistresults {{ position:absolute; z-index:5; left:0; right:0; background:var(--card); border:1px solid var(--line); border-radius:8px; margin-top:4px; max-height:300px; overflow:auto; box-shadow:0 8px 28px #0004; }}
  .ares {{ padding:.5rem .7rem; cursor:pointer; border-bottom:1px solid var(--line); font-size:.9rem; }}
  .ares:last-child {{ border-bottom:0; }}
  .ares:hover {{ background:var(--line); }}
  .ares small {{ color:var(--mut); }}
  .artistbanner {{ background:var(--card); border:1px solid var(--accent); border-radius:10px; padding:.7rem .9rem; margin-top:.9rem; font-size:.92rem; }}
  .artistbanner .x {{ float:right; cursor:pointer; color:var(--accent); font-weight:600; }}
  .leaflet-popup-content {{ margin:.7rem .9rem !important; font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:#1a1a1a; width:290px !important; }}
  .leaflet-popup-content a {{ color:#b4432b; }}
  .poph {{ font-size:1.04rem; line-height:1.3; }}
  .popscore {{ color:#b4432b; font-weight:700; float:right; margin-left:.6rem; font-size:1.05rem; }}
  .popmeta {{ color:#666; font-size:.8rem; margin:.2rem 0 .45rem; }}
  .popev {{ border-top:1px solid #0001; padding-top:.4rem; max-height:190px; overflow:auto; }}
  .pev {{ margin:.3rem 0; font-size:.82rem; color:#333; }}
  .pevl {{ color:#b4432b; font-weight:600; }}
  .pact {{ color:#2e7d32; font-weight:600; }}
</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
<header><div class="wrap">
  <h1>Avant Atlas</h1>
  <div class="sub">A curated, weighted directory of venues committed to free jazz,
  free improvisation &amp; avant-garde music — and the musicians keeping them alive.</div>
  <div style="margin-top:1rem"><a href="/submit" style="display:inline-block;background:#e05a6d;color:#0a0c12;font-weight:600;text-decoration:none;padding:.5rem 1rem;border-radius:8px">+ Add a venue</a></div>
  <div class="artistbar">
    <input type="search" id="artistq" placeholder="🎷  Find where an artist plays…" autocomplete="off">
    <div id="artistresults" class="artistresults" hidden></div>
  </div>
  <div id="artistbanner" class="artistbanner" hidden></div>
</div></header>
<div class="wrap">
  <div id="map"></div>
  <div class="maplegend" id="legend"></div>
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
const M = (DATA.musicians || []);
const venueById = Object.fromEntries(V.map(v => [v.id, v]));
let ACTIVE_ARTIST = null;
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

const TIER_COLORS = {{cornerstone:'#e0654a', committed:'#e39a3b', supportive:'#d9b74a', occasional:'#8f9a8c', incidental:'#8a857d'}};
let MAP, MARKERS;
function initMap() {{
  MAP = L.map('map', {{ worldCopyJump:true, scrollWheelZoom:false }}).setView([30, 5], 2);
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{ attribution:'&copy; OpenStreetMap contributors &copy; CARTO', maxZoom:19 }}).addTo(MAP);
  MARKERS = L.layerGroup().addTo(MAP);
  const leg = document.getElementById('legend');
  leg.innerHTML = tiers.map(t => `<span><i class="dot" style="background:${{TIER_COLORS[t]||'#8a857d'}}"></i>${{esc(tierLabel[t]||t)}}</span>`).join('');
  setTimeout(() => MAP.invalidateSize(), 250);
}}
function updateMap(list) {{
  if (!MAP) return;
  MARKERS.clearLayers();
  const pts = [];
  list.forEach(v => {{
    const loc = v.location || {{}};
    if (loc.lat == null || loc.lon == null) return;
    const color = TIER_COLORS[v.tier] || '#8a857d';
    const m = L.circleMarker([loc.lat, loc.lon], {{ radius: 4 + (v.score||0)/11, color:'#00000055', weight:.6, fillColor:color, fillOpacity:.82 }});
    const web = v.website ? `<a href="${{esc(v.website)}}" target="_blank" rel="noopener">${{esc(v.name)}}</a>` : esc(v.name);
    const place = esc(loc.city||'') + (loc.region ? ', '+esc(loc.region) : '') + ((loc.country && loc.country!=='US') ? ', '+esc(loc.country) : '');
    const byKey = Object.fromEntries((v.score_breakdown||[]).map(s => [s.key, s]));
    const evLines = ['dedicated_series','artist_roster','show_frequency','self_description']
      .map(k => byKey[k]).filter(s => s && s.evidence).slice(0,3)
      .map(s => `<div class="pev"><span class="pevl">${{esc(s.label)}}:</span> ${{esc(s.evidence)}}</div>`).join('');
    const active = v.active_this_year ? ' &middot; <span class="pact">active this year</span>' : '';
    const html = `<div class="poph"><span class="popscore">${{v.score}}</span><b>${{web}}</b></div>`
      + `<div class="popmeta">${{place}} &middot; ${{esc(tierLabel[v.tier]||v.tier)}}${{active}}</div>`
      + (evLines ? `<div class="popev">${{evLines}}</div>` : '<div class="popev"><i>Evidence still being gathered — help us verify.</i></div>');
    m.bindPopup(html, {{ maxWidth: 320 }});
    m.bindTooltip(`${{esc(v.name)}} · ${{v.score}} ${{esc(tierLabel[v.tier]||v.tier)}}`);
    m.addTo(MARKERS);
    pts.push([loc.lat, loc.lon]);
  }});
  if (pts.length) {{ try {{ MAP.fitBounds(pts, {{ padding:[30,30], maxZoom:6 }}); }} catch(e) {{}} }}
}}
function render() {{
  const q = document.getElementById('q').value.toLowerCase().trim();
  const tier = document.getElementById('tier').value;
  const region = document.getElementById('region').value;
  const sort = document.getElementById('sort').value;
  const base = ACTIVE_ARTIST ? V.filter(v => (ACTIVE_ARTIST.associated_venues || []).includes(v.id)) : V;
  let rows = base.slice();
  if (sort === 'name') rows.sort((a,b)=> (a.name||'').localeCompare(b.name||''));
  else if (sort === 'city') rows.sort((a,b)=> ((a.location||{{}}).city||'').localeCompare((b.location||{{}}).city||''));
  else rows.sort((a,b)=> b.score - a.score);
  const visible = rows.filter(v => {{
    const loc = v.location || {{}};
    const hay = (v.name+' '+(loc.city||'')+' '+(loc.region||'')+' '+(v.type||'')).toLowerCase();
    return (!q || hay.includes(q)) && (!tier || v.tier === tier) && (!region || (loc.region||'') === region);
  }});
  document.getElementById('list').innerHTML = visible.map(card).join('');
  document.getElementById('count').textContent = ACTIVE_ARTIST
    ? (visible.length + ' venue' + (visible.length!==1?'s':'') + ' where ' + ACTIVE_ARTIST.name + ' plays')
    : (visible.length + ' of ' + V.length + ' venues');
  updateMap(visible);
}}
document.getElementById('list').addEventListener('click', e => {{
  if (e.target.classList.contains('toggle')) {{
    const v = e.target.closest('.venue'); v.classList.toggle('open');
    e.target.textContent = (v.classList.contains('open') ? '▾' : '▸') + ' why this score';
  }}
}});
['q','tier','region','sort'].forEach(id => document.getElementById(id).addEventListener('input', render));

// --- fan view: find where an artist plays ---
function artistRow(a) {{
  const instr = (a.instruments||[]).join(', ');
  const hb = a.home_base || {{}};
  const place = [hb.city, hb.region, (hb.country && hb.country!=='US'?hb.country:'')].filter(Boolean).join(', ');
  const n = (a.associated_venues||[]).filter(id => venueById[id]).length;
  return `<div class="ares" data-id="${{esc(a.id)}}"><b>${{esc(a.name)}}</b>`
    + (instr ? ` <small>· ${{esc(instr)}}</small>` : '')
    + (place ? ` <small>· ${{esc(place)}}</small>` : '')
    + ` <small>· ${{n}} venue${{n!==1?'s':''}}</small></div>`;
}}
const aq = document.getElementById('artistq');
const ares = document.getElementById('artistresults');
aq.addEventListener('input', () => {{
  const q = aq.value.toLowerCase().trim();
  if (!q) {{ ares.hidden = true; return; }}
  const hits = M.filter(a => (a.name+' '+(a.instruments||[]).join(' ')).toLowerCase().includes(q)).slice(0, 12);
  ares.innerHTML = hits.length ? hits.map(artistRow).join('')
    : '<div class="ares"><small>no matching artist yet — the roster is still growing</small></div>';
  ares.hidden = false;
}});
ares.addEventListener('click', e => {{
  const el = e.target.closest('.ares'); if (!el || !el.dataset.id) return;
  selectArtist(M.find(a => a.id === el.dataset.id));
}});
document.addEventListener('click', e => {{ if (!e.target.closest('.artistbar')) ares.hidden = true; }});
function selectArtist(a) {{
  if (!a) return;
  ACTIVE_ARTIST = a; ares.hidden = true; aq.value = a.name;
  const instr = (a.instruments||[]).join(', ');
  const hb = a.home_base || {{}};
  const place = [hb.city, hb.region, (hb.country && hb.country!=='US'?hb.country:'')].filter(Boolean).join(', ');
  const site = a.website ? ` &middot; <a href="${{esc(a.website)}}" target="_blank" rel="noopener">site</a>` : '';
  const nv = (a.associated_venues||[]).filter(id => venueById[id]).length;
  const b = document.getElementById('artistbanner');
  b.innerHTML = `<span class="x" id="clearartist">clear ✕</span><b>${{esc(a.name)}}</b>`
    + (instr ? ` — ${{esc(instr)}}` : '') + (place ? ` — ${{esc(place)}}` : '') + site
    + `<br><small>${{nv ? 'Showing '+nv+' venue'+(nv!==1?'s':'')+' in the Atlas where they play.' : 'No linked venues in the Atlas yet — help us add them.'}}</small>`;
  b.hidden = false;
  render();
}}
document.getElementById('artistbanner').addEventListener('click', e => {{
  if (e.target.id === 'clearartist') {{
    ACTIVE_ARTIST = null; aq.value = '';
    document.getElementById('artistbanner').hidden = true; render();
  }}
}});

initMap();
render();
</script>
</body>
</html>
"""


def build_all(outdir: Path | None = None, *, base_url: str | None = None,
              single_page: bool = False) -> dict:
    """Build everything: the multi-page site, directory.json, and DIRECTORY.md."""
    outdir = outdir or SITE
    outdir.mkdir(parents=True, exist_ok=True)
    venues = storage.load_venues()
    musicians = storage.load_musicians()
    base = (base_url or os.environ.get("ATLAS_BASE_URL")
            or site_mod.DEFAULT_BASE_URL)

    events = storage.load_events()
    doc = build_json(venues, musicians, events)
    result = site_mod.build_site(outdir, venues, musicians, base=base,
                                directory_json=doc, events=events)
    (storage.ROOT / "DIRECTORY.md").write_text(build_markdown(venues, musicians),
                                               encoding="utf-8")
    if single_page:
        (outdir / "all-in-one.html").write_text(build_html(venues, musicians),
                                                encoding="utf-8")
        result["single_page"] = str(outdir / "all-in-one.html")
    return result
