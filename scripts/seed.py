#!/usr/bin/env python3
"""Generate the seed venue + musician YAML files under data/.

Run:  python scripts/seed.py

The YAML files it writes are the canonical, human-editable records. This script
exists so the initial corpus is calibrated consistently against the four rubric
anchors; after this, humans edit the YAML directly and this script is only a
historical record of the seed.

CONFIDENCE POLICY (honesty is the point of this project):
  * ~0.80-0.90 : facts verified via web research during the seeding session,
                 with source URLs recorded.
  * ~0.45-0.60 : well-known venue believed to fit, but NOT re-verified this
                 session. Marked needs_human_review=True so contributors know
                 to confirm details (open status, current programming).
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import rubric, storage  # noqa: E402

TODAY = _dt.date.today().isoformat()
SIG_ORDER = rubric.SIGNAL_KEYS  # dedicated_series, show_frequency, ...


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def V(name, city, region, country, vtype, opmodel, sig, *,
      capacity=None, website=None, lat=None, lon=None, neighborhood=None,
      aliases=None, active=True, last_confirmed=None, confidence=0.8,
      sources=None, evidence=None, notes=None, needs_review=False,
      status="active", vid=None):
    """Assemble one venue record.

    sig: 7-tuple of 0-5 values in SIG_ORDER.
    evidence: optional {signal_key: "text"} to attach to signals.
    """
    evidence = evidence or {}
    signals = {}
    for key, val in zip(SIG_ORDER, sig):
        entry = {"value": val}
        if key in evidence:
            entry["evidence"] = evidence[key]
        if sources:
            entry["sources"] = list(sources)
        signals[key] = entry
    score = rubric.score_from_signals(signals)
    tier = rubric.tier_for_score(score)
    loc = {"city": city, "region": region, "country": country}
    if neighborhood:
        loc["neighborhood"] = neighborhood
    if lat is not None:
        loc["lat"] = lat
    if lon is not None:
        loc["lon"] = lon
    rec = {
        "id": vid or slug(name),
        "name": name,
        "aliases": aliases or [],
        "status": status,
        "location": loc,
        "type": vtype,
        "operating_model": opmodel,
        "capacity": capacity,
        "website": website,
        "active_this_year": active,
        "signals": signals,
        "score": score,
        "tier": tier.key,
        "confidence": confidence,
        "provenance": {
            "added_by": "seed:web-research-2026-07",
            "added_on": TODAY,
            "last_confirmed": last_confirmed or "2026-07",
            "source_urls": list(sources or []),
            "needs_human_review": needs_review,
        },
        "notes": notes or "",
    }
    return rec


# ===========================================================================
# THE FOUR CALIBRATION ANCHORS (must land in the documented ranges)
# ===========================================================================
VENUES = []

VENUES.append(V(
    "IBeam Brooklyn", "Brooklyn", "NY", "US", "dedicated_space", "artist_run",
    (5, 5, 5, 5, 5, 4, 5),
    aliases=["iBeam"], capacity=50, neighborhood="Gowanus",
    website="https://www.ibeambrooklyn.com/", lat=40.6740, lon=-73.9845,
    confidence=0.9,
    sources=["https://www.ibeambrooklyn.com/about-1",
             "https://www.jazznearyou.com/nyc/venue/ibeam-brooklyn"],
    evidence={
        "dedicated_series": "Member-owned space for innovative music; hosts the Brooklyn Free Spirit Festival (3rd year in 2026); programs free-form and experimental jazz.",
        "show_frequency": "Live music Tuesday-Sunday nights.",
        "artist_roster": "Established and emerging improvisers; visiting artists workshop new works.",
        "self_description": "Mission is to foster a community of innovative and creative musicians; hosts free-form/experimental jazz.",
        "operating_model": "Member owned and operated by professional musicians (artist-run).",
        "listening_room": "Intimate listening room; music is the point.",
    },
    notes="ANCHOR: calibrated as a VERY HIGH cornerstone venue."))

VENUES.append(V(
    "Dissonant Works", "St. Louis", "MO", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 5, 5, 4, 5),
    neighborhood="South City", website="https://www.dissonantworks.org/",
    lat=38.6009, lon=-90.2360, confidence=0.88,
    aliases=["Dissonant Works Gallery"],
    sources=["https://www.dissonantworks.org/about",
             "https://www.stlmag.com/events/pianist-matthew-shipp-to-perform-at-dissonant-works-gallery/"],
    evidence={
        "dedicated_series": "Dedicated experimental art and music event space and gallery; programming built around experimental sound.",
        "show_frequency": "Regular experimental performances, exhibits, and workshops.",
        "artist_roster": "Books recognized improvisers (e.g. pianist Matthew Shipp, Sept 2025).",
        "self_description": "Nonprofit for experimental art and music; runs Prismatic Dissonance experimental-sound archive.",
        "operating_model": "Volunteer-run 501(c)(3) nonprofit.",
        "listening_room": "Gallery/event space presented for attentive listening.",
    },
    notes="ANCHOR: calibrated as a VERY HIGH cornerstone venue."))

VENUES.append(V(
    "Crosstown Arts", "Memphis", "TN", "US", "arts_center", "nonprofit",
    (2, 2, 2, 2, 4, 2, 5),
    neighborhood="Crosstown Concourse", website="https://crosstownarts.org/",
    lat=35.1537, lon=-89.9925, capacity=417, confidence=0.85,
    sources=["https://crosstownarts.org/",
             "https://wearememphis.com/play/music/venue-profile-the-green-room-at-crosstown-concourse/"],
    evidence={
        "dedicated_series": "Broad contemporary arts center (visual art, residencies, film, music); books some adventurous music but is not free-jazz-dedicated.",
        "artist_roster": "Wide-ranging lineups (Todd Snider, The Bad Plus, Booker T. Jones, Rebirth Brass Band) — mostly not the free/avant circuit.",
        "self_description": "Describes itself as a contemporary arts center, not an experimental-music venue.",
        "operating_model": "Nonprofit arts organization, institutional in scale.",
        "listening_room": "The Green Room is a genuine acoustically-treated listening room without bar distractions.",
    },
    notes="ANCHOR: calibrated as MODERATE — on the list, but a broad arts center, not free-jazz-dedicated."))

VENUES.append(V(
    "Arthur's Tavern", "New York", "NY", "US", "bar_club", "commercial",
    (0, 1, 1, 0, 1, 0, 0),
    neighborhood="West Village", website="https://arthurstavern.nyc/",
    lat=40.7324, lon=-74.0027, confidence=0.85,
    sources=["https://arthurstavern.nyc/",
             "https://en.wikipedia.org/wiki/Arthur's_Tavern"],
    evidence={
        "show_frequency": "Live music nightly, but trad jazz, blues, and soul — not free/avant.",
        "artist_roster": "House bands (e.g. Grove Street Stompers since 1962); traditional players, not the improvised-music circuit.",
        "operating_model": "88-year-old commercial neighborhood bar / tourist spot; no cover, drink minimum.",
    },
    notes="ANCHOR: calibrated as VERY LOW — commercial venue with occasional/traditional jazz, not an avant-garde home."))

# ===========================================================================
# VERIFIED THIS SESSION (confidence ~0.8)
# ===========================================================================
VENUES.append(V(
    "The Stone", "New York", "NY", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 5, 5, 4, 5),
    aliases=["The Stone at The New School"], neighborhood="Greenwich Village",
    website="http://thestonenyc.com/", lat=40.7357, lon=-73.9967, confidence=0.85,
    sources=["https://en.wikipedia.org/wiki/The_Stone_(music_space)"],
    evidence={
        "dedicated_series": "Not-for-profit experimental music space founded by John Zorn (2005); weekly artist-curated residencies.",
        "self_description": "The vast majority of performers are part of the experimental/avant-garde scene.",
        "operating_model": "Nonprofit; all door revenue goes to performers; no food/drinks sold.",
        "artist_roster": "Deep roster of experimental/avant-garde musicians.",
        "listening_room": "No food, drink, or dancing — pure listening space.",
    },
    notes="Now at The Glass Box Theatre, The New School (55 W. 13th St)."))

VENUES.append(V(
    "Roulette Intermedium", "Brooklyn", "NY", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 4, 5, 4, 4),
    aliases=["Roulette"], neighborhood="Boerum Hill",
    website="https://roulette.org/", lat=40.6862, lon=-73.9817, capacity=400,
    confidence=0.8,
    sources=["https://en.wikipedia.org/wiki/Roulette_Intermedium"],
    evidence={
        "dedicated_series": "Long-running nonprofit presenter of experimental, improvised, and new music.",
        "operating_model": "Nonprofit performing-arts organization.",
        "artist_roster": "Extensive experimental/new-music/improviser roster.",
    },
    notes="Larger flagship experimental-music presenter."))

VENUES.append(V(
    "Elastic Arts", "Chicago", "IL", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 5, 5, 4, 4),
    aliases=["Elastic Arts Foundation"], neighborhood="Avondale",
    website="https://elasticarts.org/", lat=41.9316, lon=-87.7118, confidence=0.85,
    sources=["https://elasticarts.org/improvised-music-series",
             "https://elasticarts.org/"],
    evidence={
        "dedicated_series": "Home of the Elastic Improvised Music Series, running weekly since April 2002 (curated 2002-2023 by Dave Rempis; now Ishmael Ali, Molly Jones, Ben Zucker).",
        "show_frequency": "Weekly improvised-music series plus other experimental programming.",
        "operating_model": "501(c)(3) not-for-profit for independent artists of all disciplines.",
        "artist_roster": "Core of Chicago's improvised-music community.",
    },
    notes="Cornerstone of the Chicago improvised-music scene."))

VENUES.append(V(
    "The Red Room", "Baltimore", "MD", "US", "diy_space", "diy_collective",
    (5, 5, 5, 5, 5, 4, 4),
    aliases=["Red Room Collective"], website="https://www.redroom.org/",
    lat=39.3260, lon=-76.6165, confidence=0.85,
    sources=["https://www.redroom.org/booking/", "https://en.wikipedia.org/wiki/High_Zero"],
    evidence={
        "dedicated_series": "Volunteer-run space hosting ONLY experimental, improvised, and/or non-idiomatic performances; weekly concerts.",
        "show_frequency": "Weekly improvised-music concerts.",
        "operating_model": "Volunteer collective; space donated by Normals Books & Records.",
        "self_description": "Dedicated to mind-expanding experimental culture.",
    },
    notes="Runs inside Normals Books & Records; sibling to the High Zero festival."))

VENUES.append(V(
    "High Zero Festival", "Baltimore", "MD", "US", "festival", "nonprofit",
    (5, 2, 5, 5, 5, 5, 4),
    website="http://www.highzero.org/", lat=39.3260, lon=-76.6165, confidence=0.8,
    active=True, sources=["https://en.wikipedia.org/wiki/High_Zero"],
    evidence={
        "dedicated_series": "Annual festival (since 1999) of experimental free-improvised music; non-idiomatic improvisation, instrument building, sound art.",
        "show_frequency": "Annual festival plus related weekly Red Room concerts.",
        "operating_model": "High Zero Foundation nonprofit; volunteer collective.",
        "community_reputation": "Nationally recognized free-improvisation festival, 25+ years.",
    },
    notes="Festival (annual). Frequency is intentionally low as a single event; commitment is very high."))

VENUES.append(V(
    "Chapel Performance Space", "Seattle", "WA", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 5, 5, 4, 5),
    aliases=["Wayward Music Series", "Good Shepherd Center Chapel"],
    neighborhood="Wallingford", website="https://www.waywardmusic.org/",
    lat=47.6613, lon=-122.3327, confidence=0.85,
    sources=["https://www.waywardmusic.org/", "https://www.nseq.org/"],
    evidence={
        "dedicated_series": "Home of the Wayward Music Series (curated by Nonsequitur): ~10 concerts a month of adventurous/experimental music, free improvisation, and the outer limits of jazz.",
        "show_frequency": "Roughly ten concerts every month.",
        "operating_model": "Nonsequitur is a 501(c)(3) nonprofit dedicated to adventurous and experimental music.",
        "artist_roster": "Free improvisation, electroacoustic, post-classical composers.",
        "listening_room": "Seated concert hall in a former chapel; attentive listening.",
    },
    notes="Wayward Music Series presented by Nonsequitur and partner organizations."))

VENUES.append(V(
    "Gallery 1412", "Seattle", "WA", "US", "diy_space", "diy_collective",
    (4, 4, 5, 5, 5, 3, 4),
    neighborhood="Central District", website="https://gallery1412dotorg.wordpress.com/",
    lat=47.6130, lon=-122.3140, confidence=0.8,
    sources=["https://gallery1412dotorg.wordpress.com/"],
    evidence={
        "dedicated_series": "Small DIY storefront run by a collective of musicians, geared toward improvised and other experimental music.",
        "operating_model": "Musician collective, DIY.",
        "artist_roster": "Improvised and experimental musicians.",
    },
    notes="DIY improvised/experimental storefront."))

VENUES.append(V(
    "Trinosophes", "Detroit", "MI", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 4, 5, 3, 4),
    neighborhood="Eastern Market", website="https://trinosophes.com/",
    lat=42.3436, lon=-83.0384, confidence=0.82,
    sources=["https://trinosophes.com/", "https://avantmusicnews.com/2024/10/19/coming-to-detroits-trinosophes-38/"],
    evidence={
        "dedicated_series": "Arts nonprofit running live experimental/improvised music, exhibitions, a label and publishing; hosts avant-garde jazz and creative improvisation.",
        "show_frequency": "Performs most nights (typically closed Mondays).",
        "operating_model": "Trinosophes Projects, a Michigan 501(c)(3) nonprofit.",
        "artist_roster": "Local and international improvisers and experimental artists.",
    },
    notes="Also houses Peoples Records."))

VENUES.append(V(
    "Solar Myth", "Philadelphia", "PA", "US", "dedicated_space", "nonprofit",
    (5, 4, 5, 5, 5, 4, 5),
    aliases=["Ars Nova Workshop"], neighborhood="South Broad",
    website="https://www.arsnovaworkshop.org/", lat=39.9339, lon=-75.1655,
    capacity=300, confidence=0.85,
    sources=["https://www.arsnovaworkshop.org/", "https://www.jazztimes.com/festivals-events/scenes/phillys-ars-nova-workshop-finds-a-new-home/"],
    evidence={
        "dedicated_series": "Ars Nova Workshop's full-time home; a listening room named for Sun Ra, programming adventurous jazz and experimental music.",
        "show_frequency": "Frequent Ars Nova-curated concerts through the year.",
        "operating_model": "Ars Nova Workshop is a nonprofit presenter of creative/experimental music.",
        "artist_roster": "Marshall Allen, Immanuel Wilkins, Nduduzo Makhathini and the creative-music circuit.",
        "listening_room": "Vinyl listening bar / dedicated listening room.",
    },
    notes="Reopened 2022 in the former Boot & Saddle; presents Ars Nova Workshop programming."))

VENUES.append(V(
    "Nameless Sound", "Houston", "TX", "US", "presenter", "nonprofit",
    (5, 4, 5, 5, 5, 4, 4),
    website="https://www.namelesssound.org/", lat=29.7386, lon=-95.3595,
    confidence=0.83,
    sources=["https://www.namelesssound.org/", "https://en.wikipedia.org/wiki/Nameless_Sound"],
    evidence={
        "dedicated_series": "Houston's most important presenter of creative music and free improvisation; weekly 'They, Who Sound' experimental series (with Lawndale).",
        "show_frequency": "Weekly experimental/improvised series plus concerts.",
        "operating_model": "Nonprofit founded 2001 by musician David Dove; deep arts-education mission.",
        "artist_roster": "International contemporary/free-improv artists (e.g. Joe McPhee editions).",
    },
    notes="Presenter (books into rooms such as MATCH and Lawndale)."))

VENUES.append(V(
    "Epistrophy Arts", "Austin", "TX", "US", "presenter", "nonprofit",
    (5, 2, 5, 5, 5, 3, 3),
    website="https://nowplayingaustin.com/organization/epistrophy-arts/",
    lat=30.2672, lon=-97.7431, confidence=0.8,
    sources=["https://www.furious.com/perfect/epistrophyarts.html",
             "https://austin.culturemap.com/news/entertainment/02-06-14-bringing-adventurous-avant-garde-music-to-town-with-pedro-moreno-and-epistrophy-arts/"],
    evidence={
        "dedicated_series": "Grass-roots organization presenting adventurous and improvised music in Austin since 1998.",
        "show_frequency": "~100 shows over two decades — periodic rather than weekly.",
        "operating_model": "Grass-roots, artist/organizer-run (Pedro Moreno).",
        "artist_roster": "Presented Joe McPhee, Arthur Doyle, Susie Ibarra, Assif Tsahar, Fire!, Konk Pack.",
    },
    notes="Presenter; books into Austin rooms such as the Museum of Human Achievement."))

VENUES.append(V(
    "Museum of Human Achievement", "Austin", "TX", "US", "diy_space", "diy_collective",
    (3, 3, 3, 4, 5, 3, 3),
    aliases=["MoHA"], website="https://glasstire.com/venues/the-museum-of-human-achievement/",
    lat=30.2530, lon=-97.7000, confidence=0.72,
    sources=["https://calendar.austinchronicle.com/location/the-museum-of-human-achievement-11832610"],
    evidence={
        "dedicated_series": "Warehouse arts venue hosting heavily experimental music including the No Idea Festival, alongside other disciplines.",
        "operating_model": "Multidisciplinary DIY/artist-run warehouse space.",
        "artist_roster": "Experimental and improvised music among broader programming.",
    },
    notes="Broad multidisciplinary warehouse; strong experimental strand (No Idea Festival)."))

VENUES.append(V(
    "2220 Arts + Archives", "Los Angeles", "CA", "US", "arts_center", "diy_collective",
    (4, 4, 4, 5, 5, 3, 4),
    neighborhood="Historic Filipinotown", website="https://www.2220arts.org/",
    lat=34.0653, lon=-118.2760, confidence=0.8,
    sources=["https://www.2220arts.org/about", "https://culture.lacity.gov/venue/2220-arts-archives"],
    evidence={
        "dedicated_series": "Volunteer-run interdisciplinary center focused on experimentation, improvisation and adventure; cooperatively programmed by ~a dozen LA programmers/nonprofits.",
        "operating_model": "Volunteer-run community arts cooperative (former Bootleg Theater).",
        "self_description": "Dedicated to innovative performance and experimental arts.",
        "artist_roster": "Improvised, international, and experimental music among film/literary programs.",
    },
    notes="Cooperatively programmed; music is one strong strand of a broad experimental program."))

VENUES.append(V(
    "Luggage Store Gallery", "San Francisco", "CA", "US", "gallery", "nonprofit",
    (4, 3, 5, 4, 5, 3, 3),
    aliases=["LSG Creative Music Series"], neighborhood="Tenderloin",
    website="https://www.luggagestoregallerysf.org/", lat=37.7825, lon=-122.4103,
    confidence=0.6, needs_review=True,
    sources=["https://www.bayimproviser.com/venue/7/luggage-store-creative-music-series",
             "https://outsound.org/programs/"],
    evidence={
        "dedicated_series": "Long-standing new-music series curated by Outsound Presents / Rent Romus; historically the Bay Area's longest-running experimental series (since 1991).",
        "operating_model": "Gallery + Outsound volunteer collective.",
        "artist_roster": "Free improvisation, electronic manipulation, noise, sonic sculpture.",
    },
    notes="NEEDS REVIEW: the weekly LSG New Music Series was retired Dec 2024; a twice-monthly Creative Music Series is reported to continue. Confirm current cadence."))

VENUES.append(V(
    "The Lab", "San Francisco", "CA", "US", "arts_center", "nonprofit",
    (3, 3, 4, 4, 5, 3, 3),
    neighborhood="Mission District", website="https://www.thelab.org/",
    lat=37.7620, lon=-122.4211, confidence=0.6, needs_review=True,
    sources=["https://www.thelab.org/"],
    evidence={
        "dedicated_series": "Multidisciplinary nonprofit presenting experimental and improvised music among other art forms.",
        "operating_model": "Nonprofit artist-centered space.",
    },
    notes="NEEDS REVIEW: confirm current experimental-music cadence and 2026 programming."))

VENUES.append(V(
    "Berlin", "Minneapolis", "MN", "US", "bar_club", "commercial",
    (3, 4, 3, 3, 2, 3, 5),
    aliases=["Berlin MPLS"], neighborhood="North Loop",
    website="https://www.berlinmpls.com/", lat=44.9857, lon=-93.2716,
    capacity=85, confidence=0.75,
    sources=["https://www.berlinmpls.com/", "https://www.thecurrent.org/feature/2024/07/26/berlin-is-a-minneapolis-music-venue-that-creates-unmatched-intimacy"],
    evidence={
        "dedicated_series": "Music-and-dining room programming innovative jazz, electronic, and experimental music; catering to more adventurous showcases.",
        "show_frequency": "Open nightly except Tuesdays.",
        "self_description": "Positions itself for adventurous/experimental and vulnerable, experimental performances.",
        "operating_model": "Commercial live-music bar/restaurant (lowers commitment score despite adventurous booking).",
        "listening_room": "High-fidelity, candlelit 85-seat intimate listening room.",
    },
    notes="Commercial but genuinely adventurous; sibling in spirit to Icehouse."))

VENUES.append(V(
    "Icehouse", "Minneapolis", "MN", "US", "bar_club", "commercial",
    (2, 3, 3, 2, 2, 2, 3),
    neighborhood="Eat Street", website="https://icehousempls.com/",
    lat=44.9553, lon=-93.2780, confidence=0.65, needs_review=True,
    sources=["https://www.exploreminnesota.com/profile/icehouse/4037"],
    evidence={
        "dedicated_series": "Two-story supper club booking a wide range including adventurous jazz; not free-jazz-dedicated.",
        "operating_model": "Commercial supper club / music venue.",
    },
    notes="NEEDS REVIEW: books some creative music but broad commercial booking."))

VENUES.append(V(
    "Music Box Village", "New Orleans", "LA", "US", "dedicated_space", "nonprofit",
    (4, 2, 3, 4, 5, 3, 3),
    aliases=["New Orleans Airlift"], neighborhood="Bywater",
    website="https://musicboxvillage.com/", lat=29.9640, lon=-90.0330,
    confidence=0.7,
    sources=["https://musicboxvillage.com/our-story", "https://splice.com/sounds/packs/splice-soundscapes/music-box-village/story"],
    evidence={
        "dedicated_series": "Outdoor 'musical architecture' sonic-sculpture village and performance platform for one-of-a-kind concerts, residencies, and interdisciplinary works.",
        "self_description": "Celebrates the city's avant-garde musicians, tinkerers, and inventors.",
        "operating_model": "Flagship project of the New Orleans Airlift nonprofit.",
        "artist_roster": "Experimental/improvised and cross-genre artists on custom instruments.",
    },
    notes="Unique experimental sound-sculpture venue; programming is periodic/curated."))

# ===========================================================================
# KNOWN BUT NOT RE-VERIFIED THIS SESSION (confidence ~0.45-0.55, needs review)
# These add real geographic breadth. Contributors should confirm details.
# ===========================================================================
VENUES.append(V(
    "Rhizome DC", "Washington", "DC", "US", "diy_space", "nonprofit",
    (4, 3, 4, 4, 5, 3, 3),
    website="https://www.rhizomedc.org/", lat=38.9700, lon=-77.0200,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "House-based nonprofit arts space widely associated with experimental and improvised music in DC.",
        "operating_model": "Community nonprofit / DIY arts space.",
    },
    notes="NEEDS REVIEW: not re-verified this session; confirm current programming and address."))

VENUES.append(V(
    "The Hungry Brain", "Chicago", "IL", "US", "bar_club", "commercial",
    (4, 3, 4, 3, 2, 4, 3),
    neighborhood="Roscoe Village", lat=41.9430, lon=-87.6790,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Long associated with the Sunday-night Transmission improvised-music series (Umbrella Music).",
        "artist_roster": "Chicago improvised-music community.",
        "operating_model": "Commercial bar hosting a dedicated weekly improvised series.",
    },
    notes="NEEDS REVIEW: confirm the current status/cadence of the Sunday improvised series."))

VENUES.append(V(
    "Firehouse 12", "New Haven", "CT", "US", "dedicated_space", "commercial",
    (4, 3, 4, 3, 2, 3, 5),
    website="https://firehouse12.com/", lat=41.3050, lon=-72.9300,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Recording studio + performance space running an adventurous jazz/creative-music concert series.",
        "listening_room": "Dedicated listening-room performance space.",
    },
    notes="NEEDS REVIEW: confirm current season and cadence."))

VENUES.append(V(
    "Lilypad", "Cambridge", "MA", "US", "diy_space", "commercial",
    (4, 4, 4, 3, 3, 3, 3),
    neighborhood="Inman Square", lat=42.3736, lon=-71.1010,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Small Inman Square room hosting frequent improvised, experimental, and creative-music sets.",
        "artist_roster": "Boston-area improvisers.",
    },
    notes="NEEDS REVIEW: not re-verified this session."))

VENUES.append(V(
    "Hallwalls Contemporary Arts Center", "Buffalo", "NY", "US", "arts_center", "nonprofit",
    (3, 3, 3, 4, 5, 3, 3),
    website="https://www.hallwalls.org/", lat=42.8940, lon=-78.8700,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Storied nonprofit contemporary arts center with a long history of experimental and improvised music programming.",
        "operating_model": "Nonprofit multidisciplinary arts center.",
    },
    notes="NEEDS REVIEW: confirm current music programming cadence."))

VENUES.append(V(
    "Kerrytown Concert House", "Ann Arbor", "MI", "US", "dedicated_space", "nonprofit",
    (3, 3, 3, 3, 5, 3, 4),
    aliases=["Edgefest"], website="https://kerrytownconcerthouse.com/",
    lat=42.2840, lon=-83.7460, confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Nonprofit concert house; home of Edgefest, a festival of creative/adventurous jazz and improvised music.",
        "operating_model": "Nonprofit concert house.",
        "listening_room": "Seated concert-house listening environment.",
    },
    notes="NEEDS REVIEW: confirm Edgefest continuity and season."))

VENUES.append(V(
    "Bird & Beckett Books and Records", "San Francisco", "CA", "US", "record_store", "commercial",
    (3, 4, 3, 2, 3, 3, 4),
    neighborhood="Glen Park", website="https://www.birdbeckett.com/",
    lat=37.7340, lon=-122.4330, confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Independent bookstore hosting a long-running weekly jazz and creative-music series.",
        "listening_room": "Intimate bookstore listening setting.",
    },
    notes="NEEDS REVIEW: leans jazz; confirm share of free/creative programming."))

VENUES.append(V(
    "An Die Musik Live", "Baltimore", "MD", "US", "dedicated_space", "commercial",
    (3, 3, 3, 3, 2, 3, 5),
    website="https://www.andiemusiklive.com/", lat=39.2970, lon=-76.6150,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Intimate acoustic listening room presenting jazz including creative/adventurous artists.",
        "listening_room": "Dedicated seated listening room.",
    },
    notes="NEEDS REVIEW: confirm share of free/avant vs. mainstream jazz."))

VENUES.append(V(
    "Eyedrum Art & Music Gallery", "Atlanta", "GA", "US", "gallery", "nonprofit",
    (3, 3, 3, 4, 5, 3, 3),
    website="https://eyedrum.org/", lat=33.7490, lon=-84.3850,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Nonprofit art/music gallery with a long history of experimental and improvised music.",
        "operating_model": "Volunteer-driven nonprofit gallery.",
    },
    notes="NEEDS REVIEW: confirm current venue location and programming."))

VENUES.append(V(
    "Dazzle", "Denver", "CO", "US", "bar_club", "commercial",
    (1, 3, 2, 2, 2, 2, 4),
    website="https://dazzledenver.com/", lat=39.7420, lon=-104.9870,
    confidence=0.5, needs_review=True,
    evidence={
        "dedicated_series": "Prominent Denver jazz club; mostly mainstream/straight-ahead with occasional adventurous booking.",
        "operating_model": "Commercial jazz club/restaurant.",
        "listening_room": "Seated club listening environment.",
    },
    notes="NEEDS REVIEW: included for Rocky Mountain coverage; leans mainstream jazz — low free/avant commitment."))

# ===========================================================================
# MUSICIANS (active this year; associated with the venues above)
# ===========================================================================
def M(name, instruments, city, region, country, *, roles=None, venues=None,
      collectives=None, website=None, active=True, confidence=0.7,
      sources=None, note=None, needs_review=False):
    return {
        "id": slug(name),
        "name": name,
        "instruments": instruments,
        "roles": roles or ["performer"],
        "home_base": {"city": city, "region": region, "country": country},
        "active_this_year": active,
        "associated_venues": venues or [],
        "collectives": collectives or [],
        "website": website,
        "confidence": confidence,
        "provenance": {
            "added_by": "seed:web-research-2026-07",
            "added_on": TODAY,
            "source_urls": list(sources or []),
            "needs_human_review": needs_review,
            "note": note or "",
        },
    }


MUSICIANS = [
    M("Matthew Shipp", ["piano"], "New York", "NY", "US",
      venues=["dissonant-works"], confidence=0.8,
      sources=["https://www.stlmag.com/events/pianist-matthew-shipp-to-perform-at-dissonant-works-gallery/"],
      note="Performed at Dissonant Works, Sept 2025."),
    M("Marshall Allen", ["alto saxophone", "EVI"], "Philadelphia", "PA", "US",
      roles=["performer", "bandleader"], venues=["solar-myth"],
      collectives=["Sun Ra Arkestra", "Ghost Horizons"], confidence=0.8,
      sources=["https://www.arsnovaworkshop.org/"],
      note="Ghost Horizons at Solar Myth, Feb 2026; centenarian free-jazz elder still active."),
    M("Immanuel Wilkins", ["alto saxophone"], "New York", "NY", "US",
      roles=["performer", "bandleader"], venues=["solar-myth"], confidence=0.75,
      sources=["https://www.arsnovaworkshop.org/"],
      note="Quartet closing Philly Music Fest at Solar Myth, Oct 2026."),
    M("Dave Rempis", ["alto saxophone", "tenor saxophone", "baritone saxophone"],
      "Chicago", "IL", "US", roles=["performer", "curator"],
      venues=["elastic-arts"], collectives=["Elastic Improvised Music Series"],
      confidence=0.78, sources=["https://elasticarts.org/improvised-music-series"],
      note="Curated the Elastic Improvised Music Series 2002-2023."),
    M("Ishmael Ali", ["cello", "guitar", "electronics"], "Chicago", "IL", "US",
      roles=["performer", "curator"], venues=["elastic-arts"], confidence=0.7,
      sources=["https://elasticarts.org/improvised-music-series"],
      note="Current co-curator of the Elastic Improvised Music Series."),
    M("Molly Jones", ["saxophone", "flute"], "Chicago", "IL", "US",
      roles=["performer", "curator"], venues=["elastic-arts"], confidence=0.65,
      sources=["https://elasticarts.org/improvised-music-series"],
      note="Current co-curator of the Elastic Improvised Music Series.", needs_review=True),
    M("Ben Zucker", ["trumpet", "percussion", "composition"], "Chicago", "IL", "US",
      roles=["performer", "curator"], venues=["elastic-arts"], confidence=0.6,
      sources=["https://elasticarts.org/improvised-music-series"],
      note="Current co-curator of the Elastic Improvised Music Series.", needs_review=True),
    M("Rent Romus", ["saxophone"], "Oakland", "CA", "US",
      roles=["performer", "curator", "producer"], venues=["luggage-store-gallery"],
      collectives=["Outsound Presents"], confidence=0.72,
      sources=["https://outsound.org/about/"],
      note="Founder of Outsound Presents; curated the Luggage Store new-music series."),
    M("David Dove", ["trombone"], "Houston", "TX", "US",
      roles=["performer", "educator", "director"], venues=["nameless-sound"],
      collectives=["Nameless Sound"], confidence=0.72,
      sources=["https://en.wikipedia.org/wiki/Nameless_Sound"],
      note="Founder/director of Nameless Sound."),
    M("Joel Peterson", ["bass", "guitar"], "Detroit", "MI", "US",
      roles=["performer", "organizer"], venues=["trinosophes"],
      collectives=["Trinosophes Projects"], confidence=0.6,
      sources=["https://joelpetersonmusic.com/about"],
      note="Co-founder/organizer at Trinosophes.", needs_review=True),
    M("Joe McPhee", ["saxophone", "trumpet", "pocket trumpet"], "Poughkeepsie", "NY", "US",
      roles=["performer", "bandleader"], venues=["epistrophy-arts", "nameless-sound"],
      confidence=0.6, sources=["https://www.furious.com/perfect/epistrophyarts.html"],
      note="Free-jazz elder presented by Epistrophy Arts and Nameless Sound.", needs_review=True),
    M("Susie Ibarra", ["drums", "percussion"], "New York", "NY", "US",
      roles=["performer", "composer"], venues=["epistrophy-arts"], confidence=0.55,
      sources=["https://www.furious.com/perfect/epistrophyarts.html"],
      note="Presented at Epistrophy Arts' early shows; still active. Confirm current base.",
      needs_review=True),
    M("Nduduzo Makhathini", ["piano"], "New York", "NY", "US",
      roles=["performer", "bandleader"], venues=["solar-myth"], confidence=0.55,
      sources=["https://www.arsnovaworkshop.org/"],
      note="Two nights at Solar Myth, July 2026. South African-born; confirm US/home base.",
      needs_review=True),
]

# ===========================================================================
def main():
    storage.VENUES_DIR.mkdir(parents=True, exist_ok=True)
    storage.MUSICIANS_DIR.mkdir(parents=True, exist_ok=True)
    ids = set()
    for v in VENUES:
        if v["id"] in ids:
            raise SystemExit(f"duplicate venue id: {v['id']}")
        ids.add(v["id"])
        path = storage.VENUES_DIR / f"{v['id']}.yaml"
        storage.save_venue(v, str(path))
    for m in MUSICIANS:
        path = storage.MUSICIANS_DIR / f"{m['id']}.yaml"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(storage.dump_record(m))
    print(f"Wrote {len(VENUES)} venues, {len(MUSICIANS)} musicians.")


if __name__ == "__main__":
    main()
