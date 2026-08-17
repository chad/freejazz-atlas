"""The site build is now the product surface, so it gets tested like one.

These tests guard the things that quietly break and are expensive to notice:
a page that stops being generated, an unescaped venue name, invalid JSON-LD,
a sitemap that lists URLs nobody can fetch, or the front page slowly growing
back into the 1 MB blob it used to be.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import pytest

from atlas import build as build_mod
from atlas import site as site_mod
from atlas import storage

BASE = "https://example.test"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    venues = storage.load_venues()
    musicians = storage.load_musicians()
    doc = build_mod.build_json(venues, musicians)
    summary = site_mod.build_site(out, venues, musicians, base=BASE, directory_json=doc)
    return out, summary


def test_every_venue_gets_a_page(built):
    out, summary = built
    venues = storage.load_venues()
    assert summary["venues"] == len(venues)
    for v in venues:
        p = out / "venues" / v["id"] / "index.html"
        assert p.exists(), f"no page for {v['id']}"
        # Names are HTML-escaped on the way out, which is the correct behaviour.
        assert site_mod.e(v["name"]) in p.read_text()


def test_every_artist_gets_a_page(built):
    out, _ = built
    for m in storage.load_musicians():
        assert (out / "artists" / m["id"] / "index.html").exists()


def test_hub_pages_exist(built):
    out, _ = built
    for rel in ("index.html", "countries/index.html", "artists/index.html",
                "tiers/index.html", "rubric/index.html", "404.html",
                "sitemap.xml", "robots.txt", "directory.json"):
        assert (out / rel).exists(), f"missing {rel}"


def test_front_page_stays_small(built):
    """The whole point of the rewrite: the index must not inline the corpus."""
    out, _ = built
    size = (out / "index.html").stat().st_size
    assert size < 60_000, f"front page is {size} bytes — is the corpus inlined again?"


def test_sitemap_urls_all_resolve_to_files(built):
    out, _ = built
    root = ET.fromstring((out / "sitemap.xml").read_text())
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text for el in root.findall(".//s:loc", ns)]
    assert len(locs) > 400
    for loc in locs:
        assert loc.startswith(BASE)
        path = loc[len(BASE):]
        if path == "/submit":
            continue  # served by the app, not a file
        target = out / path.strip("/") / "index.html" if path.endswith("/") \
            else out / path.strip("/")
        assert target.exists(), f"sitemap lists {loc} but {target} does not exist"


def test_every_page_declares_canonical_and_description(built):
    out, _ = built
    pages = list(out.rglob("*.html"))
    assert len(pages) > 400
    for p in pages:
        h = p.read_text()
        assert 'rel="canonical"' in h, f"{p} has no canonical URL"
        assert 'name="description"' in h, f"{p} has no meta description"
        assert "<title>" in h


def test_jsonld_is_valid_json(built):
    out, _ = built
    checked = 0
    for p in out.rglob("*.html"):
        for block in re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', p.read_text(), re.S):
            json.loads(block)
            checked += 1
    assert checked > 400


def test_venue_page_carries_musicvenue_schema(built):
    out, _ = built
    h = (out / "venues" / "ibeam-brooklyn" / "index.html").read_text()
    blocks = [json.loads(b) for b in
              re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)]
    types = {b.get("@type") for b in blocks}
    assert "MusicVenue" in types
    venue = next(b for b in blocks if b.get("@type") == "MusicVenue")
    assert venue["geo"]["latitude"]
    assert venue["additionalProperty"][0]["value"] == 98


def test_no_unrendered_template_braces(built):
    """f-string templating is easy to get wrong; a leaked {{ is always a bug."""
    out, _ = built
    for p in out.rglob("*.html"):
        text = p.read_text()
        # Leaflet URL templates legitimately contain {s}/{z}/{x}/{y}.
        stripped = re.sub(r"\{[szxyr]\}", "", text)
        assert "{{" not in stripped, f"{p} contains unrendered braces"


def test_html_escaping_of_hostile_input():
    v = {
        "id": "xss-test", "name": '<script>alert("x")</script>',
        "status": "active", "type": "diy_space", "operating_model": "artist_run",
        "location": {"city": "Nowhere & Co", "region": 'A"B', "country": "US"},
        "signals": {"dedicated_series": {"value": 3, "evidence": "<img src=x>"}},
        "score": 15, "tier": "incidental", "confidence": 0.5,
    }
    html = site_mod.build_venue_page(v, base=BASE, musicians=[], siblings=[])
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x>" not in html
    assert "Nowhere &amp; Co" in html


def test_city_slugs_are_unique_per_city():
    """Two cities must never collide into one page, or venues silently vanish."""
    seen = {}
    for v in storage.load_venues():
        loc = v.get("location") or {}
        slug = site_mod.city_slug(loc)
        key = (loc.get("city"), loc.get("region"), loc.get("country"))
        seen.setdefault(slug, set()).add(key)
    collisions = {s: k for s, k in seen.items() if len(k) > 1}
    assert not collisions, f"slug collisions: {collisions}"
