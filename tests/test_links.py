"""Tests for finding an artist's own web presence.

The risk here is misattribution: recording somebody else's site, a ticketing
page, or the label's own homepage as an artist's website. That would be a false
statement about a person, published under their name, so the classifier is
tested mostly on what it declines to accept.
"""

from __future__ import annotations

import pytest

from atlas import links


@pytest.mark.parametrize("url,platform", [
    ("https://www.facebook.com/steve.hirsh.7", "facebook"),
    ("https://www.instagram.com/stevehirshdrums/", "instagram"),
    ("https://stevehirsh.bandcamp.com", "bandcamp"),
    ("https://x.com/someone", "twitter"),
    ("https://open.spotify.com/artist/123", "spotify"),
])
def test_socials_are_recognised(url, platform):
    assert links.classify_link(url) == ("social", platform)


@pytest.mark.parametrize("url", [
    "https://www.songkick.com/artists/2362507-someone",
    "https://www.bandsintown.com/a/123",
    "https://dice.fm/event/abc",
])
def test_listing_services_are_not_websites(url):
    """Songkick is useful, but it is not the artist's site."""
    kind = links.classify_link(url)
    assert kind and kind[0] == "aggregator"


def test_artist_website_is_recognised():
    assert links.classify_link("https://stevehirshdrums.com/") == \
        ("website", "stevehirshdrums.com")


def test_infrastructure_urls_are_ignored():
    for url in ("https://bcbits.com/img/x.jpg", "https://fonts.googleapis.com/x",
                "https://schema.org/Event", "https://www.facebook.com/tr?id=1"):
        assert links.classify_link(url) is None


def test_release_links_fall_back_to_the_site_root():
    """A link to one album on a label's site is not the artist's home page."""
    found = links.links_from_bandcamp(
        '<a href="https://phonogramunit.com/album/rhizome">Rhizome</a>')
    assert found["website"] == "https://phonogramunit.com/"
    assert "derived from release link" in found["website_note"]


def test_one_concert_page_is_not_kept_as_a_profile():
    found = links.links_from_bandcamp(
        '<a href="https://www.songkick.com/concerts/43362578-evan-parker">gig</a>')
    assert found["website"] is None
    assert "songkick" not in found["socials"]


def test_artist_page_on_a_listing_service_is_kept_as_a_profile():
    found = links.links_from_bandcamp(
        '<a href="https://www.songkick.com/artists/123-someone">dates</a>')
    assert found["socials"].get("songkick")
    assert found["website"] is None


# --- Bandcamp identification ------------------------------------------------
@pytest.mark.parametrize("name,subdomain,ok", [
    ("Eri Yamamoto", "eriyamamoto", True),
    ("Dave Sewelson", "sewelson", True),          # surname only
    ("Ava Mendoza", "avamendozamusic", True),     # with a suffix
    ("Steve Hirsh", "stevehirsh", True),
    ("Steve Hirsh", "mahakalamusic", False),      # the label, not the artist
    ("Steve Hirsh", "someoneelse", False),
])
def test_bandcamp_subdomain_attribution(name, subdomain, ok):
    assert links.name_matches_subdomain(name, subdomain) is ok


def test_label_release_urls_never_become_an_artist_page():
    """The bug this prevents: 150 artists all "owning" the label's Bandcamp."""
    m = {"name": "Art Edmaiston", "provenance": {"source_urls": [
        "https://mahakalamusic.com",
        "https://mahakalamusic.bandcamp.com/album/memphis-mandala",
    ]}}
    assert links.guess_bandcamp(m) is None


def test_own_bandcamp_page_is_found_when_recorded():
    m = {"name": "Eri Yamamoto", "provenance": {"source_urls": [
        "https://mahakalamusic.bandcamp.com/album/sparks",
        "https://eriyamamoto.bandcamp.com/album/horizon",
    ]}}
    assert links.guess_bandcamp(m) == "https://eriyamamoto.bandcamp.com"


def test_candidate_addresses_are_plausible_and_bounded():
    cands = links.bandcamp_candidates("Steve Hirsh")
    assert "https://stevehirsh.bandcamp.com" in cands
    assert len(cands) <= 4, "guessing must stay cheap; hosts are not ours to hammer"
    assert all("mahakalamusic" not in c for c in cands)


# --- dates page discovery ---------------------------------------------------
def test_front_page_listing_dates_is_its_own_dates_page():
    html = ("<h2>Coming Up</h2><p>Oct 15: Elastic Arts, Chicago</p>"
            "<p>Oct 17: Dissonant Works, St Louis</p>")
    url, why = links.find_dates_url(html, "https://artist.test/")
    assert url == "https://artist.test/"
    assert "already lists" in why


def test_dates_link_is_followed_on_the_same_host_only():
    html = ('<a href="/shows">Shows</a>'
            '<a href="https://ticketing.example/buy">Tickets</a>')
    url, why = links.find_dates_url(html, "https://artist.test/")
    assert url == "https://artist.test/shows"
    assert "shows" in why.lower()


def test_no_dates_page_is_reported_honestly():
    url, why = links.find_dates_url("<a href='/bio'>Bio</a>", "https://artist.test/")
    assert url is None
    assert "no dates page" in why


def test_rate_limiting_is_a_distinct_condition():
    """A 429 must be distinguishable from "this artist has no links"."""
    assert issubclass(links.RateLimited, RuntimeError)
    assert links.MIN_INTERVAL >= 1.0, "be a considerate guest"
