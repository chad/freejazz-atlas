"""Tests for reading gigs off artists' own pages, and matching them to venues.

Two failure modes matter here and both are silent. Mis-parsing a date puts a gig
in the wrong year, and a venue mis-match attributes somebody's concert to a room
they have never played in — which would be a false statement about two different
parties at once. So the matcher is tested for what it *refuses* to do at least as
much as for what it finds.
"""

from __future__ import annotations

import datetime as dt

import pytest

from atlas import events


# --- dates ------------------------------------------------------------------
def test_full_iso_dates_are_taken_as_given():
    iso, inferred, rest = events.parse_date_prefix("2026-10-15: Elastic Arts, Chicago")
    assert (iso, inferred) == ("2026-10-15", False)
    assert rest == "Elastic Arts, Chicago"


def test_explicit_year_is_not_inferred():
    iso, inferred, _ = events.parse_date_prefix("Oct 15, 2027: Somewhere, Chicago")
    assert (iso, inferred) == ("2027-10-15", False)


@pytest.mark.parametrize("line", [
    "Oct 15: Elastic Arts, Chicago",
    "Oct. 15: Elastic Arts, Chicago",
    "October 15 - Elastic Arts, Chicago",
    "Sept 4: The Backdoor, Quezon City",
    "Aug. 14: Front Yard",
])
def test_common_written_date_forms_parse(line):
    assert events.parse_date_prefix(line) is not None


def test_yearless_dates_are_flagged_as_inferred():
    """"Oct 15" does not say which October. The guess must be labelled."""
    iso, inferred, _ = events.parse_date_prefix(
        "Oct 15: Elastic Arts, Chicago", today=dt.date(2026, 8, 17))
    assert iso == "2026-10-15"
    assert inferred is True


def test_year_inference_rolls_forward_for_past_months():
    """Read in November, "Feb 3" means next February, not ten months ago."""
    iso, inferred = events.infer_year(2, 3, today=dt.date(2026, 11, 20))
    assert iso == "2027-02-03"
    assert inferred


def test_year_inference_keeps_the_very_recent_past():
    """A gig three days ago should not jump eleven months into the future."""
    iso, _ = events.infer_year(8, 14, today=dt.date(2026, 8, 17))
    assert iso == "2026-08-14"


def test_non_dates_are_not_dates():
    for line in ("Recordings", "Out now: Muscle Memory", "Contact:", "15 Questions"):
        assert events.parse_date_prefix(line) is None


# --- locations --------------------------------------------------------------
@pytest.mark.parametrize("text,venue,city,region", [
    ("Elastic Arts, Chicago", "Elastic Arts", "Chicago", ""),
    ("Dumb Records, Springfield, IL", "Dumb Records", "Springfield", "IL"),
    ("The Backdoor, Quezon City", "The Backdoor", "Quezon City", ""),
    ("Dissonant Works, St Louis", "Dissonant Works", "St Louis", ""),
])
def test_venue_and_city_split(text, venue, city, region):
    v, c, r, _ = events.split_place(text)
    assert (v, c, r) == (venue, city, region)


def test_address_parenthetical_yields_the_city():
    v, c, r, lineup = events.split_place(
        "Front Yard (1346 Van Buren, St Paul): Nathan Hanson, Steve Hirsh")
    assert v == "Front Yard"
    assert c == "St Paul"
    assert "Nathan Hanson" in lineup


def test_city_only_listing_does_not_invent_a_venue():
    """"Eau Claire, WI" is a held date with no room announced yet."""
    v, c, r, _ = events.split_place("Eau Claire, WI")
    assert v == ""
    assert c == "Eau Claire"
    assert r == "WI"


# --- end-to-end text extraction --------------------------------------------
SAMPLE = """
<h2>Coming Up</h2>
<p>Aug. 14: Front Yard (1346 Van Buren, St Paul): Nathan Hanson, Steve Hirsh</p>
<p>Sept 25: Headwaters School of Music and Art, Bemidji, MN</p>
<p>Sept 26: Master Class, Conversing In Music, Headwaters School of Music and Art</p>
<p>Oct 15: Elastic Arts, Chicago</p>
<p>Oct 17: Dissonant Works, St Louis</p>
<h2>Recordings</h2>
<p>Out now: Muscle Memory</p>
"""


def test_extracts_gigs_and_skips_non_gigs():
    evs = events.extract_events(SAMPLE, source_url="https://x.test/",
                                artist_id="steve-hirsh",
                                today=dt.date(2026, 8, 17))
    names = [e.venue_name for e in evs]
    assert "Elastic Arts" in names
    assert "Front Yard" in names
    # A master class is not a gig.
    assert not any("Master Class" in (e.raw or "") for e in evs)
    # A release announcement is not a gig.
    assert not any("Muscle Memory" in (e.venue_name or "") for e in evs)


def test_jsonld_events_are_preferred_over_text():
    html = """<script type="application/ld+json">
    {"@type":"MusicEvent","name":"Trio","startDate":"2026-12-01",
     "location":{"@type":"MusicVenue","name":"The Stone",
     "address":{"addressLocality":"New York","addressRegion":"NY"}}}
    </script><p>Oct 15: Somewhere Else, Chicago</p>"""
    evs = events.extract_events(html, source_url="https://x.test/", artist_id="a")
    assert len(evs) == 1
    assert evs[0].method == "jsonld"
    assert evs[0].date == "2026-12-01"
    assert evs[0].year_inferred is False


def test_ics_feeds_are_parsed():
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261015\r\n"
           "SUMMARY:Trio set\r\nLOCATION:Elastic Arts\\, Chicago\r\n"
           "END:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = events.extract_events(ics, source_url="https://x.test/cal.ics", artist_id="a")
    assert len(evs) == 1
    assert evs[0].date == "2026-10-15"
    assert evs[0].venue_name == "Elastic Arts"


# --- venue matching ---------------------------------------------------------
VENUES = [
    {"id": "elastic-arts", "name": "Elastic Arts",
     "location": {"city": "Chicago", "region": "IL", "country": "US"}},
    {"id": "dissonant-works", "name": "Dissonant Works",
     "location": {"city": "St. Louis", "region": "MO", "country": "US"}},
    {"id": "public-space-one-iowa-city", "name": "Public Space One",
     "aliases": ["PS One", "PS1"],
     "location": {"city": "Iowa City", "region": "IA", "country": "US"}},
    {"id": "the-bridge-miami", "name": "The Bridge",
     "location": {"city": "Miami", "region": "FL", "country": "US"}},
]


def _match(venue_name, city, region=""):
    ev = events.Event(date="2026-10-15", raw="", venue_name=venue_name, city=city,
                      region=region, artist_id="a")
    return events.match_venue(ev, VENUES)


def test_exact_name_and_city_matches():
    assert _match("Elastic Arts", "Chicago").venue_id == "elastic-arts"


def test_abbreviated_city_still_matches():
    """Tour lists write "St Louis"; the record says "St. Louis"."""
    assert _match("Dissonant Works", "St Louis").venue_id == "dissonant-works"


def test_aliases_are_used():
    """"PS One" is what locals call Public Space One."""
    assert _match("PS One", "Iowa City").venue_id == "public-space-one-iowa-city"


def test_same_name_different_city_is_not_a_match():
    """"The Bridge" exists in more than one town; the city is what decides."""
    ev = _match("The Bridge", "Amsterdam")
    assert ev.venue_id is None
    assert "city differs" in ev.match_note


def test_unknown_room_is_left_unmatched_with_a_reason():
    ev = _match("Dumb Records", "Springfield", "IL")
    assert ev.venue_id is None
    assert ev.match_note and "no confident match" in ev.match_note


def test_city_only_listing_is_not_matched_to_anything():
    ev = _match("", "Kansas City")
    assert ev.venue_id is None
    assert "no venue named" in ev.match_note


def test_name_key_ignores_words_every_venue_shares():
    assert events.name_key("The Elastic Arts Center") == events.name_key("Elastic")


# --- observed frequency -----------------------------------------------------
def test_observed_frequency_reports_a_caveat_not_a_verdict():
    evs = [events.Event(date="2026-10-15", raw="", venue_id="elastic-arts",
                        artist_id="steve-hirsh"),
           events.Event(date="2026-09-01", raw="", venue_id="elastic-arts",
                        artist_id="other")]
    obs = events.observed_frequency(evs, "elastic-arts", today=dt.date(2026, 8, 17))
    assert obs["observed_events"] == 2
    assert obs["artists_seen"] == ["other", "steve-hirsh"]
    # The number must ship with its own health warning: sparse coverage is a gap
    # in the Atlas, not evidence against a venue.
    assert "coverage" in obs["caveat"]


def test_event_ids_are_stable_and_unique():
    a = events.Event(date="2026-10-15", raw="x", venue_name="Elastic Arts",
                     city="Chicago", artist_id="steve-hirsh")
    b = events.Event(date="2026-10-15", raw="different text",
                     venue_name="Elastic Arts", city="Chicago",
                     artist_id="steve-hirsh")
    c = events.Event(date="2026-10-16", raw="x", venue_name="Elastic Arts",
                     city="Chicago", artist_id="steve-hirsh")
    assert a.id == b.id, "same gig should keep its id when the wording changes"
    assert a.id != c.id
