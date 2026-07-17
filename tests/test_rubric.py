"""Calibration + validation tests. These lock the rubric to the four anchors."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas import rubric, storage  # noqa: E402
from atlas.model import validate_venue, validate_musician, enrich_venue  # noqa: E402


def test_weights_total_100():
    assert sum(s.max_points for s in rubric.SIGNALS) == 100


def test_perfect_and_empty():
    perfect = {s.key: 5 for s in rubric.SIGNALS}
    assert rubric.score_from_signals(perfect) == 100
    assert rubric.score_from_signals({}) == 0


def test_tiers_cover_0_to_100_without_gaps():
    for score in range(0, 101):
        t = rubric.tier_for_score(score)
        assert t.low <= score <= t.high


def _venue_by_id(vid):
    for v in storage.load_venues():
        if v["id"] == vid:
            return enrich_venue(v)
    raise AssertionError(f"missing seed venue {vid}")


def test_anchor_ibeam_very_high():
    v = _venue_by_id("ibeam-brooklyn")
    assert v["score"] >= 90
    assert v["tier"] == "cornerstone"


def test_anchor_dissonant_works_very_high():
    v = _venue_by_id("dissonant-works")
    assert v["score"] >= 85
    assert v["tier"] == "cornerstone"


def test_anchor_crosstown_moderate():
    v = _venue_by_id("crosstown-arts")
    assert 45 <= v["score"] <= 64
    assert v["tier"] == "supportive"


def test_anchor_arthurs_very_low():
    v = _venue_by_id("arthur-s-tavern")
    assert v["score"] <= 24
    assert v["tier"] == "incidental"


def test_anchor_ordering():
    ibeam = _venue_by_id("ibeam-brooklyn")["score"]
    dissonant = _venue_by_id("dissonant-works")["score"]
    crosstown = _venue_by_id("crosstown-arts")["score"]
    arthurs = _venue_by_id("arthur-s-tavern")["score"]
    assert ibeam > crosstown > arthurs
    assert dissonant > crosstown > arthurs


def test_all_seed_venues_valid():
    for v in storage.load_venues():
        r = validate_venue(v)
        assert r.ok, f"{v['id']}: {r.errors}"


def test_all_seed_musicians_valid():
    for m in storage.load_musicians():
        r = validate_musician(m)
        assert r.ok, f"{m['id']}: {r.errors}"


def test_stored_scores_match_signals():
    for v in storage.load_venues():
        assert v["score"] == rubric.score_from_signals(v["signals"]), v["id"]


def test_geographic_breadth_not_nyc_heavy():
    venues = storage.load_venues()
    states = {v["location"].get("region") for v in venues}
    assert len(states) >= 12, "seed corpus should span many states"
    nyc = [v for v in venues
           if v["location"].get("city") in ("New York", "Brooklyn")]
    assert len(nyc) <= len(venues) * 0.25, "must not be NYC-heavy"
