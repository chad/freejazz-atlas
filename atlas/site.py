"""Multi-page static site generator.

The old build emitted one 1.1 MB page with all 263 venues inlined. That is a
fine artifact and a terrible website: a search engine sees a single URL, so
nobody looking for "free jazz in Lisbon" can ever find the Atlas, and the
project's whole reason to exist — geographic coverage of small scenes — stays
invisible.

This module emits a real site instead:

    /                       the map + browse view (data fetched, not inlined)
    /venues/<id>/           one page per venue, with evidence and JSON-LD
    /cities/<slug>/         every venue in a city
    /countries/<cc>/        every venue in a country, grouped by city
    /artists/<id>/          where an artist plays
    /tiers/<key>/           the rubric's tiers as browsable lists
    /rubric/                how scoring works (rendered from atlas.rubric)
    /directory.json         the whole corpus, one fetch
    /sitemap.xml, /robots.txt

Every page is plain HTML with no build step and no client framework. Pages are
self-describing to crawlers (title, meta description, canonical, Open Graph,
schema.org JSON-LD) because discoverability *is* the feature here.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
import re
from pathlib import Path

from . import rubric, storage
from .model import enrich_venue

SITE = storage.ROOT / "site"

# Public origin, used for canonical URLs and sitemaps. Override with the
# ATLAS_BASE_URL env var at build time. This must always be a hostname that
# actually resolves: a canonical URL pointing at a dead name gets the whole site
# dropped from search results, which is the exact problem the multi-page site
# was built to solve.
DEFAULT_BASE_URL = "https://atlas.mahakalamusic.com"

TIER_COLORS = {
    "cornerstone": "#e0654a",
    "committed": "#e39a3b",
    "supportive": "#d9b74a",
    "occasional": "#8f9a8c",
    "incidental": "#8a857d",
}

COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany",
    "JP": "Japan", "NL": "Netherlands", "CH": "Switzerland", "AT": "Austria",
    "FR": "France", "NO": "Norway", "SE": "Sweden", "PT": "Portugal",
    "IT": "Italy", "PL": "Poland", "KR": "South Korea", "BE": "Belgium",
    "CN": "China", "DK": "Denmark", "TW": "Taiwan", "ES": "Spain",
    "CZ": "Czechia", "IE": "Ireland", "IS": "Iceland", "HK": "Hong Kong",
    "FI": "Finland", "CA": "Canada", "AU": "Australia", "BR": "Brazil",
    "MX": "Mexico", "AR": "Argentina", "NZ": "New Zealand", "ZA": "South Africa",
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

TYPE_LABELS = {
    "dedicated_space": "dedicated space",
    "arts_center": "arts center",
    "diy_space": "DIY space",
    "gallery": "gallery",
    "bar_club": "bar / club",
    "presenter": "presenter",
    "festival": "festival",
    "record_store": "record store",
    "university": "university space",
}

MODEL_LABELS = {
    "artist_run": "artist-run",
    "nonprofit": "nonprofit",
    "diy_collective": "DIY collective",
    "university": "university",
    "municipal": "municipal",
    "commercial": "commercial",
}


# --- helpers ----------------------------------------------------------------
def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "unknown"


def city_slug(loc: dict) -> str:
    parts = [loc.get("city") or "", loc.get("region") or "", loc.get("country") or ""]
    return slugify("-".join(p for p in parts if p))


def city_label(loc: dict) -> str:
    city = loc.get("city") or "Unknown"
    region = loc.get("region") or ""
    country = loc.get("country") or ""
    bits = [city]
    if region and region != city:
        bits.append(region)
    if country and country != "US":
        bits.append(COUNTRY_NAMES.get(country, country))
    return ", ".join(bits)


def country_name(cc: str) -> str:
    return COUNTRY_NAMES.get(cc, cc or "Unknown")


def type_label(v: dict) -> str:
    return TYPE_LABELS.get(v.get("type"), (v.get("type") or "").replace("_", " "))


def model_label(v: dict) -> str:
    return MODEL_LABELS.get(v.get("operating_model"),
                            (v.get("operating_model") or "").replace("_", " "))


def tier_label(key: str) -> str:
    for t in rubric.TIERS:
        if t.key == key:
            return t.label
    return key or ""


def sentence_summary(v: dict) -> str:
    """A one-sentence, human description used for meta descriptions and cards.

    Built from the record rather than hand-written, so it can never drift from
    the data it claims to summarise.
    """
    loc = v.get("location") or {}
    tl = tier_label(v.get("tier"))
    where = city_label(loc)
    kind = type_label(v)
    model = model_label(v)
    bits = f"{v.get('name','')} in {where} — a {model} {kind}".replace("a artist-run", "an artist-run")
    bits += f", scored {v.get('score', 0)}/100 ({tl.lower()}) for its commitment to "
    bits += "free jazz, free improvisation and avant-garde music."
    return bits


# --- page shell -------------------------------------------------------------
CSS = """
:root{color-scheme:light dark;--bg:#faf9f7;--fg:#161514;--mut:#6b6660;--line:#e4e0d8;
 --card:#fff;--accent:#b4432b;--accent2:#8a3520}
@media (prefers-color-scheme:dark){:root{--bg:#141312;--fg:#ece8e2;--mut:#9a938a;
 --line:#2c2a27;--card:#1d1b19;--accent:#e0654a;--accent2:#f08060}}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,sans-serif;
 background:var(--bg);color:var(--fg);-webkit-text-size-adjust:100%}
a{color:var(--accent)}
.wrap{max-width:1050px;margin:0 auto;padding:0 1.25rem}
.topbar{border-bottom:1px solid var(--line);background:var(--card)}
.topbar .wrap{display:flex;align-items:center;gap:1.1rem;flex-wrap:wrap;padding:.7rem 1.25rem}
.brand{font-weight:700;letter-spacing:-.02em;text-decoration:none;color:var(--fg);font-size:1.05rem}
.topbar nav{display:flex;gap:.9rem;flex-wrap:wrap;font-size:.88rem;margin-left:auto}
.topbar nav a{color:var(--mut);text-decoration:none}
.topbar nav a:hover{color:var(--accent)}
header.hero{padding:2rem 0 1.2rem;border-bottom:1px solid var(--line)}
h1{margin:0 0 .3rem;font-size:1.75rem;letter-spacing:-.02em;line-height:1.2}
h2{font-size:1.15rem;margin:2rem 0 .6rem;letter-spacing:-.01em}
h3{font-size:1rem;margin:1.4rem 0 .4rem}
.sub{color:var(--mut);font-size:.95rem;margin:0}
.crumbs{font-size:.82rem;color:var(--mut);padding:.9rem 0 0}
.crumbs a{color:var(--mut);text-decoration:none}
.crumbs a:hover{color:var(--accent)}
main{padding:1rem 0 3rem}
.controls{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0}
input,select{padding:.5rem .6rem;border:1px solid var(--line);border-radius:8px;
 background:var(--card);color:var(--fg);font-size:.95rem;font-family:inherit}
input[type=search]{flex:1;min-width:190px}
.venue{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:.9rem 1.05rem;margin:.65rem 0}
.vhead{display:flex;align-items:baseline;gap:.7rem;flex-wrap:wrap}
.vname{font-size:1.1rem;font-weight:650}
.vname a{color:inherit;text-decoration:none;border-bottom:1px solid var(--line)}
.vname a:hover{border-color:var(--accent);color:var(--accent)}
.score{font-variant-numeric:tabular-nums;font-weight:700;font-size:1.15rem;color:var(--accent)}
.tier{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;padding:.16rem .5rem;
 border-radius:999px;border:1px solid var(--line);color:var(--mut);white-space:nowrap}
.meta{color:var(--mut);font-size:.88rem;margin:.3rem 0 0}
.bars{margin-top:.7rem}
.bar{display:grid;grid-template-columns:minmax(120px,178px) 1fr 52px;align-items:center;
 gap:.6rem;margin:.3rem 0;font-size:.82rem}
.track{background:var(--line);border-radius:6px;height:9px;overflow:hidden}
.fill{background:var(--accent);height:100%}
.pts{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}
.ev{grid-column:1/-1;color:var(--mut);font-size:.79rem;margin:-.1rem 0 .45rem;
 padding-left:.1rem;border-left:2px solid var(--line);padding-left:.6rem}
.ev a{color:var(--mut)}
#map{height:60vh;min-height:340px;border:1px solid var(--line);border-radius:12px;
 margin:1rem 0 .4rem;z-index:0;background:var(--card)}
#vmap{height:230px;border:1px solid var(--line);border-radius:10px;margin:.9rem 0 0;z-index:0}
.legend{display:flex;gap:.9rem;flex-wrap:wrap;font-size:.78rem;color:var(--mut);margin:0 0 .6rem}
.legend span{display:inline-flex;align-items:center;gap:.35rem}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:.7rem;margin:.8rem 0}
.cards a{display:block;background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:.65rem .8rem;text-decoration:none;color:var(--fg)}
.cards a:hover{border-color:var(--accent)}
.cards b{display:block;font-size:.98rem}
.cards small{color:var(--mut);font-size:.8rem}
.grid2{display:grid;grid-template-columns:1fr;gap:1.4rem}
@media(min-width:820px){.grid2{grid-template-columns:1.55fr 1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1rem 1.1rem}
.panel h2,.panel h3{margin-top:0}
dl.facts{margin:0;font-size:.9rem}
dl.facts div{display:flex;gap:.6rem;padding:.28rem 0;border-bottom:1px solid var(--line)}
dl.facts div:last-child{border-bottom:0}
dl.facts dt{color:var(--mut);min-width:118px;flex:none}
dl.facts dd{margin:0}
.big{font-size:2.6rem;font-weight:700;color:var(--accent);line-height:1;font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:.74rem;text-transform:uppercase;letter-spacing:.06em;
 padding:.2rem .55rem;border-radius:999px;color:#fff;margin-left:.4rem}
.srcs{font-size:.82rem;margin:.4rem 0 0;padding-left:1.1rem}
.srcs li{margin:.15rem 0;word-break:break-word}
.warn{background:#b4432b12;border:1px solid var(--accent);border-radius:10px;
 padding:.7rem .9rem;font-size:.86rem;margin:1rem 0}
.tags{display:flex;gap:.4rem;flex-wrap:wrap;margin:.7rem 0 0}
.tags a{font-size:.8rem;text-decoration:none;border:1px solid var(--line);border-radius:999px;
 padding:.2rem .6rem;color:var(--mut);background:var(--card)}
.tags a:hover{border-color:var(--accent);color:var(--accent)}
table.t{width:100%;border-collapse:collapse;font-size:.88rem}
table.t th,table.t td{text-align:left;padding:.4rem .5rem;border-bottom:1px solid var(--line)}
table.t th{color:var(--mut);font-weight:500;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
table.t td.n{text-align:right;font-variant-numeric:tabular-nums}
footer{border-top:1px solid var(--line);color:var(--mut);font-size:.83rem;padding:1.6rem 0 2.4rem}
footer a{color:var(--mut)}
.cta{display:inline-block;background:var(--accent);color:#fff;font-weight:600;
 text-decoration:none;padding:.5rem 1rem;border-radius:8px;font-size:.92rem}
.cta:hover{background:var(--accent2)}
.muted{color:var(--mut)}
.count{color:var(--mut);font-size:.9rem;margin:.4rem 0}
.hidden{display:none!important}
.leaflet-popup-content{margin:.65rem .85rem!important;font:13px/1.5 -apple-system,
 BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1a1a1a;width:250px!important}
.leaflet-popup-content a{color:#b4432b}
.pscore{color:#b4432b;font-weight:700;float:right;margin-left:.5rem}
.pmeta{color:#666;font-size:.8rem;margin:.15rem 0 .3rem}
"""

LEAFLET_CSS = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
LEAFLET_JS = '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" defer></script>'


def _jsonld_safe(block: dict) -> str:
    """Serialise a JSON-LD block that cannot break out of its <script> element.

    Escaping `</` alone is the usual advice and is sufficient, but venue names
    are community-supplied, so angle brackets and ampersands are escaped as
    unicode too. The JSON stays valid and identical in meaning, and no possible
    record content can emit markup.
    """
    raw = json.dumps(block, ensure_ascii=False, default=str)
    return (raw.replace("&", "\\u0026")
               .replace("<", "\\u003c")
               .replace(">", "\\u003e"))


def page(*, base: str, path: str, title: str, description: str, body: str,
         jsonld: list | None = None, head_extra: str = "", nav_here: str = "") -> str:
    """Wrap body content in the shared shell with full crawler metadata."""
    canonical = base.rstrip("/") + path
    nav = [
        ("/", "Map"),
        ("/countries/", "Places"),
        ("/artists/", "Artists"),
        ("/tiers/", "Tiers"),
        ("/rubric/", "How scoring works"),
        ("/submit", "Add a venue"),
    ]
    navhtml = "".join(
        f'<a href="{href}"{" style=color:var(--accent)" if label == nav_here else ""}>{e(label)}</a>'
        for href, label in nav
    )
    ld = ""
    for block in (jsonld or []):
        ld += ('<script type="application/ld+json">'
               + _jsonld_safe(block)
               + "</script>\n")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Avant Atlas">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta name="twitter:card" content="summary">
<style>{CSS}</style>
{head_extra}
{ld}</head>
<body>
<div class="topbar"><div class="wrap">
  <a class="brand" href="/">Avant&nbsp;Atlas</a>
  <nav>{navhtml}</nav>
</div></div>
{body}
<footer><div class="wrap">
  <p><strong>Avant Atlas</strong> — a weighted directory of venues committed to free jazz,
  free improvisation and avant-garde music. Scores measure <em>commitment</em>, not quality,
  and every one is <a href="/rubric/">explainable</a> and arguable.</p>
  <p>Something wrong or missing? <a href="/submit">Tell us</a> — corrections are the point.
  Data <a href="https://creativecommons.org/publicdomain/zero/1.0/" rel="license">CC0</a>.
  <a href="/directory.json">directory.json</a> · <a href="/sitemap.xml">sitemap</a></p>
</div></footer>
</body>
</html>
"""


# --- fragments --------------------------------------------------------------
def venue_card(v: dict, *, show_place: bool = True) -> str:
    loc = v.get("location") or {}
    href = f"/venues/{e(v['id'])}/"
    place = f'<a href="/cities/{city_slug(loc)}/" style="color:inherit">{e(city_label(loc))}</a>' \
        if show_place else ""
    if v.get("status") == "closed":
        active = ' · <b>closed</b>'
    elif v.get("active_this_year"):
        active = ' · <b>active this year</b>'
    else:
        active = ' · <span class="muted">activity unconfirmed</span>'
    link = ((v.get("provenance") or {}).get("link_check") or {}).get("status")
    if link in ("dead", "unreachable"):
        active += ' · <span class="muted">website unreachable</span>'
    conf = v.get("confidence")
    conf_s = f" · confidence {conf:.2f}".rstrip("0").rstrip(".") if isinstance(conf, (int, float)) else ""
    return f"""<article class="venue">
  <div class="vhead">
    <span class="score">{v.get('score', 0)}</span>
    <span class="tier">{e(tier_label(v.get('tier')))}</span>
    <span class="vname"><a href="{href}">{e(v.get('name', ''))}</a></span>
  </div>
  <p class="meta">{place}{' · ' if place else ''}{e(type_label(v))} · {e(model_label(v))}{conf_s}{active}</p>
</article>"""


def signal_bars(v: dict, *, with_evidence: bool = True) -> str:
    rows = rubric.explain(v.get("signals") or {})
    sigs = v.get("signals") or {}
    out = []
    for r in rows:
        pct = round((r["value"] / r["max_value"]) * 100)
        out.append(
            f'<div class="bar"><span>{e(r["label"])}</span>'
            f'<span class="track"><span class="fill" style="width:{pct}%"></span></span>'
            f'<span class="pts">{r["points"]}/{r["max_points"]}</span></div>'
        )
        if with_evidence:
            raw = sigs.get(r["key"]) or {}
            srcs = raw.get("sources") or [] if isinstance(raw, dict) else []
            if r["evidence"]:
                cite = ""
                if srcs:
                    cite = " " + " ".join(
                        f'<a href="{e(u)}" target="_blank" rel="noopener nofollow">[{i + 1}]</a>'
                        for i, u in enumerate(srcs[:3])
                    )
                out.append(f'<div class="ev">{e(r["evidence"])}{cite}</div>')
            elif r["value"]:
                out.append('<div class="ev muted">No evidence recorded yet for this signal — '
                           '<a href="/submit">help us document it</a>.</div>')
    return '<div class="bars">' + "".join(out) + "</div>"


# --- JSON-LD ----------------------------------------------------------------
def venue_jsonld(v: dict, base: str) -> dict:
    loc = v.get("location") or {}
    node = {
        "@context": "https://schema.org",
        "@type": "MusicVenue",
        "@id": f"{base}/venues/{v['id']}/",
        "name": v.get("name"),
        "url": f"{base}/venues/{v['id']}/",
        "description": sentence_summary(v),
        "address": {
            "@type": "PostalAddress",
            "addressLocality": loc.get("city"),
            "addressRegion": loc.get("region"),
            "addressCountry": loc.get("country"),
        },
    }
    if loc.get("address"):
        node["address"]["streetAddress"] = loc["address"]
    if v.get("website"):
        node["sameAs"] = v["website"]
    if loc.get("lat") is not None and loc.get("lon") is not None:
        node["geo"] = {"@type": "GeoCoordinates",
                       "latitude": loc["lat"], "longitude": loc["lon"]}
    if v.get("capacity"):
        node["maximumAttendeeCapacity"] = v["capacity"]
    if v.get("aliases"):
        node["alternateName"] = v["aliases"]
    node["additionalProperty"] = [{
        "@type": "PropertyValue",
        "name": "Avant Atlas commitment score",
        "value": v.get("score", 0),
        "maxValue": 100,
        "description": ("Weighted, evidence-backed measure of the venue's commitment to "
                        "free jazz, free improvisation and avant-garde music."),
    }]
    return node


def breadcrumbs_jsonld(items: list, base: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name,
             "item": base.rstrip("/") + path}
            for i, (path, name) in enumerate(items)
        ],
    }


def itemlist_jsonld(venues: list, base: str, name: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": name,
        "numberOfItems": len(venues),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "url": f"{base}/venues/{v['id']}/", "name": v.get("name")}
            for i, v in enumerate(venues)
        ],
    }


def crumbs(items: list) -> str:
    parts = []
    for i, (path, name) in enumerate(items):
        last = i == len(items) - 1
        parts.append(e(name) if last else f'<a href="{path}">{e(name)}</a>')
    return '<div class="wrap"><p class="crumbs">' + " › ".join(parts) + "</p></div>"


# --- page builders ----------------------------------------------------------
def build_venue_page(v: dict, *, base: str, musicians: list, siblings: list) -> str:
    loc = v.get("location") or {}
    prov = v.get("provenance") or {}
    tier = rubric.tier_for_score(v.get("score", 0))
    place = city_label(loc)
    title = f"{v.get('name', '')} — {place} | Avant Atlas"
    desc = sentence_summary(v)

    plays_here = [m for m in musicians if v["id"] in (m.get("associated_venues") or [])]
    nearby = [s for s in siblings if s["id"] != v["id"]][:6]

    color = TIER_COLORS.get(v.get("tier"), "#8a857d")
    if v.get("website"):
        pretty = re.sub(r"^https?://(www\.)?", "", v["website"]).rstrip("/")
        website = (f'<a href="{e(v["website"])}" target="_blank" rel="noopener">'
                   f"{e(pretty)}</a>")
    else:
        website = '<span class="muted">not recorded</span>'

    link = prov.get("link_check") or {}
    linkwarn = ""
    if link.get("status") in ("dead", "unreachable"):
        linkwarn = (f'<div class="warn"><strong>Heads up:</strong> the website we cite for this '
                    f'venue did not respond when we last checked it ({e(link.get("checked", ""))}). '
                    f'The venue may have moved, closed, or simply changed hosts. '
                    f'<a href="/submit">Know the answer?</a></div>')

    reviewwarn = ""
    if prov.get("needs_human_review"):
        reviewwarn = ('<div class="warn"><strong>Unverified entry.</strong> This record was '
                      'assembled from public sources but has not been confirmed by a human who '
                      'knows the room. Treat the score as a starting point, not a verdict — and '
                      '<a href="/submit">correct it</a> if you know better.</div>')

    statuswarn = ""
    if v.get("status") == "closed":
        statuswarn = ('<div class="warn"><strong>Closed.</strong> This venue is recorded as no '
                      'longer operating. It stays in the Atlas because the history of these rooms '
                      'matters — and because scenes sometimes come back.</div>')
    elif v.get("status") in ("dormant", "unconfirmed"):
        statuswarn = (f'<div class="warn"><strong>Status: {e(v["status"])}.</strong> We are not '
                      f'currently sure this room is presenting music. '
                      f'<a href="/submit">Tell us what you know.</a></div>')

    facts = [("Place", f'<a href="/cities/{city_slug(loc)}/">{e(place)}</a>')]
    if loc.get("address"):
        facts.append(("Address", e(loc["address"])))
    if loc.get("neighborhood"):
        facts.append(("Neighborhood", e(loc["neighborhood"])))
    facts += [
        ("Type", e(type_label(v))),
        ("Run as", e(model_label(v))),
    ]
    if v.get("capacity"):
        facts.append(("Capacity", f'~{v["capacity"]}'))
    facts += [
        ("Website", website),
        ("Status", e(v.get("status", ""))),
        ("Active this year", "yes" if v.get("active_this_year") else "unconfirmed"),
    ]
    if isinstance(v.get("confidence"), (int, float)):
        facts.append(("Our confidence", f'{v["confidence"]:.2f}'.rstrip("0").rstrip(".")))
    factshtml = "".join(f"<div><dt>{k}</dt><dd>{val}</dd></div>" for k, val in facts)

    srcs = prov.get("source_urls") or []
    srchtml = ("<ul class='srcs'>" + "".join(
        f'<li><a href="{e(u)}" target="_blank" rel="noopener nofollow">{e(u)}</a></li>'
        for u in srcs) + "</ul>") if srcs else \
        '<p class="muted" style="font-size:.86rem">No sources recorded — this entry needs ' \
        'documentation. <a href="/submit">Add some.</a></p>'

    artisthtml = ""
    if plays_here:
        artisthtml = ("<h3>Musicians linked to this room</h3><div class='tags'>" + "".join(
            f'<a href="/artists/{e(m["id"])}/">{e(m["name"])}</a>' for m in plays_here
        ) + "</div>")

    nearbyhtml = ""
    if nearby:
        nearbyhtml = (f"<h2>More in {e(place)}</h2>"
                      + "".join(venue_card(n, show_place=False) for n in nearby)
                      + f'<p><a href="/cities/{city_slug(loc)}/">All venues in {e(place)} →</a></p>')

    mapblock = ""
    head_extra = ""
    if loc.get("lat") is not None and loc.get("lon") is not None:
        head_extra = LEAFLET_CSS + LEAFLET_JS
        mapblock = f"""<div id="vmap"></div>
<script>window.addEventListener('load',function(){{
  if(!window.L)return;
  var m=L.map('vmap',{{scrollWheelZoom:false,zoomControl:true}}).setView([{loc['lat']},{loc['lon']}],14);
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{attribution:'&copy; OpenStreetMap &copy; CARTO',maxZoom:19}}).addTo(m);
  L.circleMarker([{loc['lat']},{loc['lon']}],{{radius:9,color:'#00000055',weight:1,
    fillColor:'{color}',fillOpacity:.9}}).addTo(m);
}});</script>"""

    notes = v.get("notes") or ""
    noteshtml = f'<h3>Curator notes</h3><p style="font-size:.9rem">{e(notes)}</p>' if notes else ""

    body = f"""{crumbs([("/", "Atlas"), (f"/countries/{(loc.get('country') or 'US').lower()}/",
                        country_name(loc.get("country"))),
                       (f"/cities/{city_slug(loc)}/", place),
                       (f"/venues/{v['id']}/", v.get("name", ""))])}
<header class="hero"><div class="wrap">
  <h1>{e(v.get('name', ''))}</h1>
  <p class="sub">{e(place)} · {e(type_label(v))} · {e(model_label(v))}</p>
</div></header>
<main><div class="wrap">
{statuswarn}{linkwarn}{reviewwarn}
<div class="grid2">
  <section>
    <div class="panel">
      <div style="display:flex;align-items:flex-start;gap:1rem;flex-wrap:wrap">
        <div>
          <div class="big">{v.get('score', 0)}<span style="font-size:1rem;color:var(--mut)">/100</span></div>
          <div style="margin-top:.3rem"><span class="pill" style="background:{color};margin:0">
            {e(tier.label)}</span></div>
        </div>
        <p class="sub" style="flex:1;min-width:200px;margin:0">{e(tier.blurb)}
          <br><a href="/rubric/" style="font-size:.85rem">How this is calculated →</a></p>
      </div>
      <h3>Why this score</h3>
      {signal_bars(v)}
    </div>
    {artisthtml}
    {nearbyhtml}
  </section>
  <aside>
    <div class="panel">
      <h3>The facts</h3>
      <dl class="facts">{factshtml}</dl>
      {mapblock}
    </div>
    <div class="panel" style="margin-top:1rem">
      <h3>Provenance</h3>
      <p style="font-size:.85rem;margin:.2rem 0">Added by <code>{e(prov.get('added_by', '?'))}</code>
      {(' on ' + e(str(prov.get('added_on')))) if prov.get('added_on') else ''}.
      {('Last confirmed ' + e(str(prov.get('last_confirmed'))) + '.') if prov.get('last_confirmed') else ''}
      {('Website last checked ' + e(str(link.get('checked'))) + ' — <b>' + e(str(link.get('status'))) + '</b>.') if link else ''}</p>
      <h3>Sources</h3>
      {srchtml}
      {noteshtml}
      <p style="margin:1rem 0 0"><a class="cta" href="/submit">Correct this entry</a></p>
    </div>
  </aside>
</div>
</div></main>"""

    return page(base=base, path=f"/venues/{v['id']}/", title=title, description=desc,
                body=body, head_extra=head_extra,
                jsonld=[venue_jsonld(v, base),
                        breadcrumbs_jsonld([("/", "Avant Atlas"),
                                            (f"/cities/{city_slug(loc)}/", place),
                                            (f"/venues/{v['id']}/", v.get("name", ""))], base)])


def _venue_list_page(*, base: str, path: str, title: str, h1: str, desc: str,
                     intro: str, venues: list, crumb_items: list,
                     extra: str = "", show_place: bool = True,
                     nav_here: str = "") -> str:
    stats = _tier_counts(venues)
    statline = " · ".join(f"{n} {tier_label(k).lower()}" for k, n in stats if n)
    body = f"""{crumbs(crumb_items)}
<header class="hero"><div class="wrap">
  <h1>{h1}</h1>
  <p class="sub">{intro}</p>
</div></header>
<main><div class="wrap">
  <p class="count">{len(venues)} venue{'s' if len(venues) != 1 else ''}{' · ' + statline if statline else ''}</p>
  {extra}
  {''.join(venue_card(v, show_place=show_place) for v in venues)}
</div></main>"""
    return page(base=base, path=path, title=title, description=desc, body=body,
                nav_here=nav_here,
                jsonld=[itemlist_jsonld(venues, base, h1),
                        breadcrumbs_jsonld(crumb_items, base)])


def _tier_counts(venues: list) -> list:
    counts = {}
    for v in venues:
        counts[v.get("tier")] = counts.get(v.get("tier"), 0) + 1
    return [(t.key, counts.get(t.key, 0)) for t in rubric.TIERS]


def build_city_page(slug: str, venues: list, *, base: str, musicians: list) -> str:
    loc = venues[0].get("location") or {}
    label = city_label(loc)
    cc = loc.get("country") or "US"
    top = venues[0]
    intro = (f"Every venue in {e(label)} that we know presents free jazz, free improvisation "
             f"or avant-garde music — ranked by how committed each one is, with the evidence "
             f"behind every score.")
    desc = (f"Free jazz, free improvisation and experimental music venues in {label}: "
            f"{len(venues)} rooms ranked by commitment. Top of the list: "
            f"{top.get('name')} ({top.get('score')}/100).")
    return _venue_list_page(
        base=base, path=f"/cities/{slug}/",
        title=f"Free jazz & experimental music venues in {label} | Avant Atlas",
        h1=f"Creative music in {e(label)}", desc=desc, intro=intro, venues=venues,
        crumb_items=[("/", "Atlas"), (f"/countries/{cc.lower()}/", country_name(cc)),
                     (f"/cities/{slug}/", label)],
        show_place=False)


def build_country_page(cc: str, venues: list, *, base: str) -> str:
    name = country_name(cc)
    by_city = {}
    for v in venues:
        by_city.setdefault(city_slug(v.get("location") or {}), []).append(v)
    cities = sorted(by_city.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    cardhtml = "".join(
        f'<a href="/cities/{slug}/"><b>{e(city_label(vs[0].get("location") or {}))}</b>'
        f'<small>{len(vs)} venue{"s" if len(vs) != 1 else ""} · '
        f'top score {max(x.get("score", 0) for x in vs)}</small></a>'
        for slug, vs in cities)
    top = sorted(venues, key=lambda v: -v.get("score", 0))[:12]
    intro = (f"{len(venues)} venues across {len(cities)} "
             f"{'city' if len(cities) == 1 else 'cities'} in {e(name)}.")
    desc = (f"Free jazz, free improvisation and avant-garde music venues in {name} — "
            f"{len(venues)} rooms in {len(cities)} cities, each with an explainable "
            f"commitment score.")
    extra = f"<h2>Cities</h2><div class='cards'>{cardhtml}</div><h2>Highest commitment in {e(name)}</h2>"
    return _venue_list_page(
        base=base, path=f"/countries/{cc.lower()}/",
        title=f"Free jazz & experimental venues in {name} | Avant Atlas",
        h1=f"Creative music in {e(name)}", desc=desc, intro=intro, venues=top,
        crumb_items=[("/", "Atlas"), ("/countries/", "Places"),
                     (f"/countries/{cc.lower()}/", name)],
        extra=extra, nav_here="Places")


def build_places_index(venues: list, *, base: str) -> str:
    by_country = {}
    for v in venues:
        by_country.setdefault((v.get("location") or {}).get("country") or "??", []).append(v)
    order = sorted(by_country.items(), key=lambda kv: (-len(kv[1]), country_name(kv[0])))
    rows = "".join(
        f'<tr><td><a href="/countries/{cc.lower()}/">{e(country_name(cc))}</a></td>'
        f'<td class="n">{len(vs)}</td>'
        f'<td class="n">{len({city_slug(x.get("location") or {}) for x in vs})}</td>'
        f'<td class="n">{max(x.get("score", 0) for x in vs)}</td></tr>'
        for cc, vs in order)

    us = by_country.get("US", [])
    by_state = {}
    for v in us:
        by_state.setdefault((v.get("location") or {}).get("region") or "??", []).append(v)
    statecards = "".join(
        f'<a href="/regions/{slugify(st)}/"><b>{e(US_STATES.get(st, st))}</b>'
        f'<small>{len(vs)} venue{"s" if len(vs) != 1 else ""}</small></a>'
        for st, vs in sorted(by_state.items(), key=lambda kv: US_STATES.get(kv[0], kv[0])))

    allcities = {}
    for v in venues:
        allcities.setdefault(city_slug(v.get("location") or {}), []).append(v)
    citycards = "".join(
        f'<a href="/cities/{slug}/"><b>{e(city_label(vs[0].get("location") or {}))}</b>'
        f'<small>{len(vs)} venue{"s" if len(vs) != 1 else ""}</small></a>'
        for slug, vs in sorted(allcities.items(),
                               key=lambda kv: (-len(kv[1]), kv[0]))[:48])

    body = f"""{crumbs([("/", "Atlas"), ("/countries/", "Places")])}
<header class="hero"><div class="wrap">
  <h1>Places</h1>
  <p class="sub">The Atlas exists to prove that this music happens everywhere, not just in
  four famous cities. {len(venues)} venues, {len(allcities)} cities,
  {len(by_country)} countries.</p>
</div></header>
<main><div class="wrap">
  <h2>Countries</h2>
  <table class="t"><thead><tr><th>Country</th><th class="n">Venues</th>
    <th class="n">Cities</th><th class="n">Top score</th></tr></thead>
    <tbody>{rows}</tbody></table>
  <h2>US states</h2>
  <div class="cards">{statecards}</div>
  <h2>Busiest cities</h2>
  <div class="cards">{citycards}</div>
</div></main>"""
    return page(base=base, path="/countries/", title="Places — every city and country in the Atlas | Avant Atlas",
                description=("Browse free jazz, free improvisation and avant-garde music venues by "
                             f"country, US state and city — {len(venues)} venues in "
                             f"{len(allcities)} cities worldwide."),
                body=body, nav_here="Places",
                jsonld=[breadcrumbs_jsonld([("/", "Avant Atlas"), ("/countries/", "Places")], base)])


def build_region_page(region: str, venues: list, *, base: str) -> str:
    name = US_STATES.get(region, region)
    cities = {city_slug(v.get("location") or {}) for v in venues}
    intro = (f"{len(venues)} venues in {e(name)}, across "
             f"{len(cities)} {'city' if len(cities) == 1 else 'cities'}.")
    desc = (f"Free jazz, free improvisation and experimental music venues in {name}: "
            f"{len(venues)} rooms ranked by commitment, with evidence for every score.")
    return _venue_list_page(
        base=base, path=f"/regions/{slugify(region)}/",
        title=f"Free jazz & experimental venues in {name} | Avant Atlas",
        h1=f"Creative music in {e(name)}", desc=desc, intro=intro, venues=venues,
        crumb_items=[("/", "Atlas"), ("/countries/", "Places"),
                     (f"/regions/{slugify(region)}/", name)],
        nav_here="Places")


def build_tier_page(tier, venues: list, *, base: str) -> str:
    intro = (f"{e(tier.blurb)} Scores {tier.low}–{tier.high} on the "
             f"<a href='/rubric/'>commitment rubric</a>.")
    desc = (f"{tier.label} venues ({tier.low}–{tier.high}/100) in the Avant Atlas: "
            f"{tier.blurb} {len(venues)} venues worldwide.")
    return _venue_list_page(
        base=base, path=f"/tiers/{tier.key}/",
        title=f"{tier.label} venues ({tier.low}–{tier.high}) | Avant Atlas",
        h1=f"{e(tier.label)} venues", desc=desc, intro=intro, venues=venues,
        crumb_items=[("/", "Atlas"), ("/tiers/", "Tiers"), (f"/tiers/{tier.key}/", tier.label)],
        nav_here="Tiers")


def build_tiers_index(venues: list, *, base: str) -> str:
    counts = dict(_tier_counts(venues))
    cards = "".join(
        f'<a href="/tiers/{t.key}/"><b>{e(t.label)} <span class="muted">'
        f'{t.low}–{t.high}</span></b><small>{counts.get(t.key, 0)} venues · {e(t.blurb)}</small></a>'
        for t in rubric.TIERS)
    body = f"""{crumbs([("/", "Atlas"), ("/tiers/", "Tiers")])}
<header class="hero"><div class="wrap">
  <h1>Tiers</h1>
  <p class="sub">Five bands of commitment, from rooms that exist for this music to rooms where
  it turns up by accident. A tier is a summary of the <a href="/rubric/">seven signals</a>,
  never a judgement of the music played there.</p>
</div></header>
<main><div class="wrap"><div class="cards">{cards}</div></div></main>"""
    return page(base=base, path="/tiers/", title="Commitment tiers | Avant Atlas",
                description=("Cornerstone, committed, supportive, occasional, incidental — how "
                             "Avant Atlas groups venues by their commitment to free jazz and "
                             "avant-garde music."),
                body=body, nav_here="Tiers",
                jsonld=[breadcrumbs_jsonld([("/", "Avant Atlas"), ("/tiers/", "Tiers")], base)])


def build_artist_page(m: dict, venues_by_id: dict, *, base: str) -> str:
    linked = [venues_by_id[i] for i in (m.get("associated_venues") or []) if i in venues_by_id]
    linked.sort(key=lambda v: -v.get("score", 0))
    hb = m.get("home_base") or {}
    place = city_label(hb) if hb.get("city") else ""
    instr = ", ".join(m.get("instruments") or [])
    title = f"{m.get('name', '')} — where they play | Avant Atlas"
    desc = (f"{m.get('name', '')}"
            + (f" ({instr})" if instr else "")
            + (f", based in {place}" if place else "")
            + f". {len(linked)} venue{'s' if len(linked) != 1 else ''} in the Avant Atlas "
              f"associated with this artist.")
    prov = m.get("provenance") or {}
    warn = ('<div class="warn"><strong>Unverified.</strong> This artist entry came from public '
            'scene knowledge and has not been confirmed. Venue links especially may be '
            'incomplete or wrong. <a href="/submit">Corrections welcome.</a></div>'
            if prov.get("needs_human_review") else "")
    facts = []
    if instr:
        facts.append(("Instruments", e(instr)))
    if m.get("roles"):
        facts.append(("Roles", e(", ".join(m["roles"]))))
    if place:
        facts.append(("Based in", e(place)))
    if m.get("collectives"):
        facts.append(("Groups", e(", ".join(m["collectives"]))))
    facts.append(("Active this year", "yes" if m.get("active_this_year") else "unconfirmed"))
    if m.get("website"):
        facts.append(("Website", f'<a href="{e(m["website"])}" rel="noopener nofollow" '
                                 f'target="_blank">{e(m["website"])}</a>'))
    factshtml = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    listhtml = ("".join(venue_card(v) for v in linked) if linked else
                '<p class="muted">No venues linked yet. If you have seen this artist play, '
                '<a href="/submit">tell us where</a> — the artist-to-room map is the part of the '
                'Atlas most in need of help.</p>')

    body = f"""{crumbs([("/", "Atlas"), ("/artists/", "Artists"),
                        (f"/artists/{m['id']}/", m.get("name", ""))])}
<header class="hero"><div class="wrap">
  <h1>{e(m.get('name', ''))}</h1>
  <p class="sub">{e(instr)}{' · ' + e(place) if place else ''}</p>
</div></header>
<main><div class="wrap">
{warn}
<div class="grid2">
  <section>
    <h2>Where {e(m.get('name', ''))} plays</h2>
    {listhtml}
  </section>
  <aside><div class="panel"><h3>The facts</h3><dl class="facts">{factshtml}</dl>
  <p style="margin:1rem 0 0"><a class="cta" href="/submit">Add a venue link</a></p></div></aside>
</div>
</div></main>"""
    ld = {
        "@context": "https://schema.org",
        "@type": "Person",
        "@id": f"{base}/artists/{m['id']}/",
        "name": m.get("name"),
        "url": f"{base}/artists/{m['id']}/",
        "description": desc,
    }
    if instr:
        ld["knowsAbout"] = m.get("instruments")
    if m.get("website"):
        ld["sameAs"] = m["website"]
    if linked:
        ld["performerIn"] = [{"@type": "MusicVenue", "name": v.get("name"),
                              "url": f"{base}/venues/{v['id']}/"} for v in linked]
    return page(base=base, path=f"/artists/{m['id']}/", title=title, description=desc,
                body=body, nav_here="Artists",
                jsonld=[ld, breadcrumbs_jsonld([("/", "Avant Atlas"), ("/artists/", "Artists"),
                                                (f"/artists/{m['id']}/", m.get("name", ""))], base)])


def build_artists_index(musicians: list, venues_by_id: dict, *, base: str) -> str:
    rows = []
    for m in sorted(musicians, key=lambda m: (m.get("name") or "").split()[-1]):
        n = len([i for i in (m.get("associated_venues") or []) if i in venues_by_id])
        hb = m.get("home_base") or {}
        rows.append(
            f'<a href="/artists/{e(m["id"])}/"><b>{e(m.get("name", ""))}</b>'
            f'<small>{e(", ".join(m.get("instruments") or []))}'
            f'{" · " + e(city_label(hb)) if hb.get("city") else ""}'
            f' · {n} venue{"s" if n != 1 else ""}</small></a>')
    body = f"""{crumbs([("/", "Atlas"), ("/artists/", "Artists")])}
<header class="hero"><div class="wrap">
  <h1>Artists</h1>
  <p class="sub">The musicians keeping these rooms alive — and which rooms they play.
  {len(musicians)} entries so far. This is the thinnest part of the Atlas and the most
  valuable to grow: <a href="/submit">add an artist or a venue link</a>.</p>
</div></header>
<main><div class="wrap"><div class="cards">{''.join(rows)}</div></div></main>"""
    return page(base=base, path="/artists/", title="Artists — improvisers and where they play | Avant Atlas",
                description=(f"{len(musicians)} improvisers and experimental musicians, and the "
                             f"venues in the Avant Atlas where each of them plays."),
                body=body, nav_here="Artists",
                jsonld=[breadcrumbs_jsonld([("/", "Avant Atlas"), ("/artists/", "Artists")], base)])


def build_rubric_page(venues: list, *, base: str) -> str:
    sigrows = "".join(
        f"<tr><td><b>{e(s.label)}</b><br><small class='muted'>{e(s.question)}</small></td>"
        f'<td class="n">{s.max_points}</td></tr>' for s in rubric.SIGNALS)
    tierrows = "".join(
        f'<tr><td><a href="/tiers/{t.key}/">{e(t.label)}</a></td>'
        f'<td class="n">{t.low}–{t.high}</td><td>{e(t.blurb)}</td></tr>' for t in rubric.TIERS)
    anchors = []
    for vid in ("ibeam-brooklyn", "dissonant-works", "crosstown-arts", "arthur-s-tavern"):
        v = next((x for x in venues if x["id"] == vid), None)
        if v:
            anchors.append(f'<tr><td><a href="/venues/{v["id"]}/">{e(v.get("name"))}</a></td>'
                           f'<td class="n">{v.get("score")}</td>'
                           f'<td>{e(tier_label(v.get("tier")))}</td></tr>')
    counts = dict(_tier_counts(venues))
    dist = "".join(f'<tr><td><a href="/tiers/{t.key}/">{e(t.label)}</a></td>'
                   f'<td class="n">{counts.get(t.key, 0)}</td></tr>' for t in rubric.TIERS)
    body = f"""{crumbs([("/", "Atlas"), ("/rubric/", "How scoring works")])}
<header class="hero"><div class="wrap">
  <h1>How scoring works</h1>
  <p class="sub">Every venue gets a 0–100 <strong>commitment score</strong>. It measures how
  much a room exists to present free jazz, free improvisation and avant-garde music — not how
  good it is, not how good the music is. And it is always explainable: open any venue page and
  read the seven signals and the evidence behind each one.</p>
</div></header>
<main><div class="wrap">
  <h2>The seven signals</h2>
  <p class="sub">A human (or, provisionally, a crawler) rates each signal 0–5. Points are
  <code>(value / 5) × weight</code>, summed and rounded.</p>
  <table class="t"><thead><tr><th>Signal</th><th class="n">Weight</th></tr></thead>
    <tbody>{sigrows}<tr><td><b>Total</b></td><td class="n"><b>100</b></td></tr></tbody></table>

  <h2>Tiers</h2>
  <table class="t"><thead><tr><th>Tier</th><th class="n">Range</th><th>Meaning</th></tr></thead>
    <tbody>{tierrows}</tbody></table>

  <h2>Calibration anchors</h2>
  <p class="sub">The rubric is pinned to four venues chosen because they are obviously
  different from each other. If a change to the weights moves these, the change is wrong.
  These anchors are enforced by the test suite.</p>
  <table class="t"><thead><tr><th>Venue</th><th class="n">Score</th><th>Tier</th></tr></thead>
    <tbody>{''.join(anchors)}</tbody></table>

  <h2>Score is not confidence</h2>
  <p>Score answers <em>how committed is this venue?</em> Confidence (0–1) answers
  <em>how sure are we?</em> A room we cannot verify gets a low confidence, never an invented
  score. Entries flagged for human review say so on the page, in a box you cannot miss. We
  would rather show you an honest question mark than a confident wrong number.</p>

  <h2>What the rubric cannot do yet</h2>
  <p>Two of the heaviest signals — <b>frequency of relevant shows</b> (20 points) and
  <b>artist roster</b> (20 points) — are currently human estimates, because the Atlas does not
  yet ingest event calendars. That is the next thing being built: once shows are in, those two
  signals become measurements instead of judgements, and a room that stops programming will
  drift down on its own.</p>

  <h2>Current distribution</h2>
  <p class="sub">Worth knowing: the corpus was seeded by looking for good venues, so it skews
  high. That is a real limitation of the collection, not a claim that most music rooms are
  committed to this music.</p>
  <table class="t"><thead><tr><th>Tier</th><th class="n">Venues</th></tr></thead>
    <tbody>{dist}</tbody></table>
</div></main>"""
    return page(base=base, path="/rubric/", title="How the commitment score works | Avant Atlas",
                description=("The seven weighted signals behind every Avant Atlas venue score: "
                             "dedicated series, show frequency, artist roster, self-description, "
                             "operating model, community reputation, listening-room intent."),
                body=body, nav_here="How scoring works",
                jsonld=[breadcrumbs_jsonld([("/", "Avant Atlas"), ("/rubric/", "How scoring works")], base)])


def build_index(venues: list, musicians: list, *, base: str, generated: str) -> str:
    """The map + browse front page. Data is fetched, not inlined (page stays ~20 KB)."""
    countries = {(v.get("location") or {}).get("country") for v in venues}
    cities = {city_slug(v.get("location") or {}) for v in venues}
    counts = dict(_tier_counts(venues))
    top = sorted(venues, key=lambda v: -v.get("score", 0))[:8]
    tophtml = "".join(venue_card(v) for v in top)
    legend = "".join(
        f'<span><i class="dot" style="background:{TIER_COLORS[t.key]}"></i>{e(t.label)}'
        f' <span class="muted">({counts.get(t.key, 0)})</span></span>' for t in rubric.TIERS)

    by_country = {}
    for v in venues:
        by_country.setdefault((v.get("location") or {}).get("country") or "??", []).append(v)
    ccards = "".join(
        f'<a href="/countries/{cc.lower()}/"><b>{e(country_name(cc))}</b>'
        f'<small>{len(vs)} venue{"s" if len(vs) != 1 else ""}</small></a>'
        for cc, vs in sorted(by_country.items(), key=lambda kv: -len(kv[1]))[:12])

    body = f"""
<header class="hero"><div class="wrap">
  <h1>Where this music actually happens</h1>
  <p class="sub">A weighted, evidence-backed directory of <strong>{len(venues)} venues</strong>
  in {len(cities)} cities and {len(countries)} countries that genuinely present free jazz,
  free improvisation and avant-garde music — and the {len(musicians)} musicians keeping them
  alive. Every score is <a href="/rubric/">explainable</a>, and arguable.</p>
  <p style="margin:.9rem 0 0"><a class="cta" href="/submit">+ Add a venue</a>
    <a href="/countries/" style="margin-left:.8rem;font-size:.9rem">Browse by place →</a></p>
</div></header>
<main><div class="wrap">
  <div id="map"></div>
  <div class="legend">{legend}</div>
  <div class="controls">
    <input type="search" id="q" placeholder="Search venue, city, region…" aria-label="Search venues">
    <select id="tier" aria-label="Filter by tier"><option value="">All tiers</option></select>
    <select id="country" aria-label="Filter by country"><option value="">All countries</option></select>
    <select id="sort" aria-label="Sort">
      <option value="score">Sort: score</option>
      <option value="name">Sort: name</option>
      <option value="city">Sort: city</option>
    </select>
  </div>
  <p class="count" id="count">Loading the corpus…</p>
  <div id="list">{tophtml}</div>
  <noscript><p class="muted">JavaScript is off, so the map and filters are unavailable —
    but the whole Atlas is browsable as plain pages:
    <a href="/countries/">by place</a>, <a href="/tiers/">by tier</a>,
    <a href="/artists/">by artist</a>.</p></noscript>

  <h2>Browse by country</h2>
  <div class="cards">{ccards}</div>
  <p><a href="/countries/">All {len(by_country)} countries and {len(cities)} cities →</a></p>

  <h2>What the score means</h2>
  <p class="sub" style="max-width:65ch">Most venue lists flatten everything together: the
  artist-run loft that programs improvised music six nights a week sits next to the tourist bar
  that books a trad quartet on Sundays. The Atlas tells them apart with seven weighted signals
  and keeps the evidence attached, so you can see — and argue with — <em>why</em> a room is
  rated the way it is. <a href="/rubric/">Read the rubric →</a></p>
</div></main>
<script>
const TIER_COLORS={json.dumps(TIER_COLORS)};
const TIERS={json.dumps([{"key": t.key, "label": t.label} for t in rubric.TIERS])};
const COUNTRIES={json.dumps(COUNTRY_NAMES)};
let V=[],MAP,MARKERS;
function esc(s){{return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));}}
function cityLabel(l){{l=l||{{}};const b=[l.city||'Unknown'];
  if(l.region&&l.region!==l.city)b.push(l.region);
  if(l.country&&l.country!=='US')b.push(COUNTRIES[l.country]||l.country);return b.join(', ');}}
function card(v){{
  const l=v.location||{{}};
  const tl=(TIERS.find(t=>t.key===v.tier)||{{}}).label||v.tier||'';
  const conf=(typeof v.confidence==='number')?' · confidence '+String(v.confidence).replace(/0+$/,'').replace(/\\.$/,''):'';
  return '<article class="venue"><div class="vhead"><span class="score">'+v.score+'</span>'
    +'<span class="tier">'+esc(tl)+'</span><span class="vname"><a href="/venues/'+esc(v.id)+'/">'
    +esc(v.name)+'</a></span></div><p class="meta">'+esc(cityLabel(l))+' · '+esc((v.type||'').replace(/_/g,' '))
    +' · '+esc((v.operating_model||'').replace(/_/g,' '))+conf
    +(v.active_this_year?' · <b>active this year</b>':'')+'</p></article>';
}}
function initMap(){{
  if(!window.L)return;
  MAP=L.map('map',{{worldCopyJump:true,scrollWheelZoom:false}}).setView([32,2],2);
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
    {{attribution:'&copy; OpenStreetMap &copy; CARTO',maxZoom:19}}).addTo(MAP);
  MARKERS=L.layerGroup().addTo(MAP);
  setTimeout(()=>MAP.invalidateSize(),200);
}}
function updateMap(list){{
  if(!MAP)return;MARKERS.clearLayers();const pts=[];
  list.forEach(v=>{{
    const l=v.location||{{}};if(l.lat==null||l.lon==null)return;
    const tl=(TIERS.find(t=>t.key===v.tier)||{{}}).label||v.tier||'';
    const m=L.circleMarker([l.lat,l.lon],{{radius:4+(v.score||0)/11,color:'#00000055',
      weight:.6,fillColor:TIER_COLORS[v.tier]||'#8a857d',fillOpacity:.82}});
    m.bindPopup('<div><span class="pscore">'+v.score+'</span><b><a href="/venues/'+esc(v.id)+'/">'
      +esc(v.name)+'</a></b></div><div class="pmeta">'+esc(cityLabel(l))+' · '+esc(tl)+'</div>'
      +'<a href="/venues/'+esc(v.id)+'/">Why this score →</a>',{{maxWidth:280}});
    m.bindTooltip(esc(v.name)+' · '+v.score);
    m.addTo(MARKERS);pts.push([l.lat,l.lon]);
  }});
  if(pts.length){{try{{MAP.fitBounds(pts,{{padding:[28,28],maxZoom:6}});}}catch(e){{}}}}
}}
function render(){{
  const q=document.getElementById('q').value.toLowerCase().trim();
  const tier=document.getElementById('tier').value;
  const cc=document.getElementById('country').value;
  const sort=document.getElementById('sort').value;
  let rows=V.slice();
  if(sort==='name')rows.sort((a,b)=>(a.name||'').localeCompare(b.name||''));
  else if(sort==='city')rows.sort((a,b)=>((a.location||{{}}).city||'').localeCompare((b.location||{{}}).city||''));
  else rows.sort((a,b)=>b.score-a.score);
  const vis=rows.filter(v=>{{
    const l=v.location||{{}};
    const hay=((v.name||'')+' '+(l.city||'')+' '+(l.region||'')+' '+(l.country||'')+' '+(v.type||'')).toLowerCase();
    return (!q||hay.includes(q))&&(!tier||v.tier===tier)&&(!cc||(l.country||'')===cc);
  }});
  document.getElementById('list').innerHTML=vis.slice(0,200).map(card).join('')
    +(vis.length>200?'<p class="muted">Showing the top 200 of '+vis.length+' matches — narrow the search, or <a href="/countries/">browse by place</a>.</p>':'');
  document.getElementById('count').textContent=vis.length+' of '+V.length+' venues';
  updateMap(vis);
}}
fetch('/directory.json').then(r=>r.json()).then(d=>{{
  V=d.venues||[];
  const ts=document.getElementById('tier');
  TIERS.forEach(t=>ts.add(new Option(t.label,t.key)));
  const cs=document.getElementById('country');
  [...new Set(V.map(v=>(v.location||{{}}).country).filter(Boolean))]
    .sort((a,b)=>(COUNTRIES[a]||a).localeCompare(COUNTRIES[b]||b))
    .forEach(c=>cs.add(new Option(COUNTRIES[c]||c,c)));
  ['q','tier','country','sort'].forEach(id=>document.getElementById(id).addEventListener('input',render));
  render();
}}).catch(e=>{{document.getElementById('count').textContent=
  'Could not load the corpus. Browse by place instead.';}});
window.addEventListener('load',initMap);
</script>
"""
    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": base + "/",
        "name": "Avant Atlas",
        "url": base + "/",
        "description": ("A curated, weighted directory of venues committed to free jazz, free "
                        "improvisation and avant-garde music, with an explainable commitment "
                        "score for every venue."),
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "dateModified": generated,
    }
    return page(base=base, path="/",
                title="Avant Atlas — venues for free jazz, free improvisation & avant-garde music",
                description=(f"{len(venues)} venues in {len(cities)} cities and {len(countries)} "
                             "countries that genuinely present free jazz, free improvisation and "
                             "avant-garde music — each with an explainable commitment score."),
                body=body, head_extra=LEAFLET_CSS + LEAFLET_JS, jsonld=[ld], nav_here="Map")


def build_404(*, base: str) -> str:
    body = """<header class="hero"><div class="wrap">
  <h1>Not in the Atlas</h1>
  <p class="sub">That page does not exist. The venue may have been renamed, or never added.</p>
  <p style="margin-top:1rem"><a class="cta" href="/">Back to the map</a>
    <a href="/submit" style="margin-left:.8rem">Add a missing venue →</a></p>
</div></header><main><div class="wrap"></div></main>"""
    return page(base=base, path="/404.html", title="Not found | Avant Atlas",
                description="Page not found.", body=body)


def build_sitemap(paths: list, *, base: str, lastmod: str) -> str:
    urls = "".join(
        f"<url><loc>{e(base.rstrip('/') + p)}</loc><lastmod>{lastmod}</lastmod>"
        f"<priority>{prio}</priority></url>"
        for p, prio in paths)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}</urlset>\n")


# --- orchestration ----------------------------------------------------------
def build_site(outdir: Path, venues: list, musicians: list, *, base: str,
               directory_json: dict) -> dict:
    """Write the whole site. Returns a summary dict."""
    base = base.rstrip("/")
    today = _dt.date.today().isoformat()
    outdir.mkdir(parents=True, exist_ok=True)

    def write(relpath: str, content: str):
        p = outdir / relpath.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    venues = sorted((enrich_venue(v) for v in venues),
                    key=lambda v: (-v.get("score", 0), v.get("name", "")))
    venues_by_id = {v["id"]: v for v in venues}
    musicians = sorted(musicians, key=lambda m: m.get("name") or "")

    sitemap_paths = [("/", "1.0"), ("/countries/", "0.8"), ("/artists/", "0.7"),
                     ("/tiers/", "0.6"), ("/rubric/", "0.7"), ("/submit", "0.5")]

    # Group once, reuse everywhere.
    by_city, by_country, by_region, by_tier = {}, {}, {}, {}
    for v in venues:
        loc = v.get("location") or {}
        by_city.setdefault(city_slug(loc), []).append(v)
        by_country.setdefault(loc.get("country") or "??", []).append(v)
        if (loc.get("country") == "US") and loc.get("region"):
            by_region.setdefault(loc["region"], []).append(v)
        by_tier.setdefault(v.get("tier"), []).append(v)

    # Venue pages
    for v in venues:
        siblings = by_city.get(city_slug(v.get("location") or {}), [])
        write(f"/venues/{v['id']}/index.html",
              build_venue_page(v, base=base, musicians=musicians, siblings=siblings))
        sitemap_paths.append((f"/venues/{v['id']}/", "0.9" if v.get("score", 0) >= 65 else "0.7"))

    # City pages
    for slug, vs in by_city.items():
        write(f"/cities/{slug}/index.html",
              build_city_page(slug, vs, base=base, musicians=musicians))
        sitemap_paths.append((f"/cities/{slug}/", "0.8"))

    # Country + region pages
    for cc, vs in by_country.items():
        write(f"/countries/{cc.lower()}/index.html", build_country_page(cc, vs, base=base))
        sitemap_paths.append((f"/countries/{cc.lower()}/", "0.8"))
    for region, vs in by_region.items():
        write(f"/regions/{slugify(region)}/index.html", build_region_page(region, vs, base=base))
        sitemap_paths.append((f"/regions/{slugify(region)}/", "0.7"))

    # Tier pages
    for t in rubric.TIERS:
        write(f"/tiers/{t.key}/index.html",
              build_tier_page(t, by_tier.get(t.key, []), base=base))
        sitemap_paths.append((f"/tiers/{t.key}/", "0.6"))

    # Artist pages
    for m in musicians:
        write(f"/artists/{m['id']}/index.html",
              build_artist_page(m, venues_by_id, base=base))
        sitemap_paths.append((f"/artists/{m['id']}/", "0.6"))

    # Hubs
    write("/index.html", build_index(venues, musicians, base=base, generated=today))
    write("/countries/index.html", build_places_index(venues, base=base))
    write("/artists/index.html", build_artists_index(musicians, venues_by_id, base=base))
    write("/tiers/index.html", build_tiers_index(venues, base=base))
    write("/rubric/index.html", build_rubric_page(venues, base=base))
    write("/404.html", build_404(base=base))

    # Machine-readable
    write("/directory.json", json.dumps(directory_json, indent=2, default=str))
    write("/sitemap.xml", build_sitemap(sitemap_paths, base=base, lastmod=today))
    write("/robots.txt",
          "User-agent: *\nAllow: /\n"
          "# Avant Atlas is a non-commercial, CC0 directory. Crawl politely.\n"
          "Crawl-delay: 1\n"
          f"Sitemap: {base}/sitemap.xml\n")

    return {
        "pages": len(sitemap_paths),
        "venues": len(venues),
        "musicians": len(musicians),
        "cities": len(by_city),
        "countries": len(by_country),
        "regions": len(by_region),
        "outdir": str(outdir),
        "base": base,
    }
