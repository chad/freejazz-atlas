"""Link health classification, tested offline.

The dangerous failure mode here is a false positive: mistaking a bot defence
or a TLS quirk for a closed venue, then stamping a scary warning on a healthy
venue page. These tests pin the classification rules that prevent that.
"""

from __future__ import annotations

import datetime as dt

from atlas import linkcheck as lc


def test_2xx_is_ok():
    assert lc._classify(200) == lc.OK
    assert lc._classify(204) == lc.OK


def test_bot_defences_are_blocked_not_dead():
    for code in (401, 403, 405, 429):
        assert lc._classify(code) == lc.BLOCKED, code


def test_only_404_and_410_count_as_dead():
    assert lc._classify(404) == lc.DEAD
    assert lc._classify(410) == lc.DEAD
    assert lc._classify(500) == lc.ERROR
    assert lc._classify(503) == lc.ERROR


def test_social_platforms_never_report_dead():
    """A Facebook page is many DIY venues' only web presence; FB cloaks bots."""
    for url in ("https://www.facebook.com/somevenue/",
                "https://instagram.com/somevenue"):
        assert lc._classify(400, url) == lc.BLOCKED
        assert lc._classify(404, url) == lc.BLOCKED
    # A non-social host with the same code is still judged on its merits.
    assert lc._classify(404, "https://venue.example/gone") == lc.DEAD


def test_alternates_cover_www_and_scheme_variants():
    alts = lc._alternates("https://example.org/about")
    assert "https://www.example.org/about" in alts
    assert "http://example.org/about" in alts
    assert "https://example.org/about" not in alts  # never re-try the original
    back = lc._alternates("https://www.example.org/")
    assert "https://example.org/" in back


def test_record_on_venue_flags_review_only_for_real_absence():
    v = {"id": "x"}
    lc.record_on_venue(v, lc.LinkResult(url="u", status=lc.OK, http=200))
    assert v["provenance"]["link_check"]["status"] == "ok"
    assert not v["provenance"].get("needs_human_review")

    v2 = {"id": "y"}
    lc.record_on_venue(v2, lc.LinkResult(url="u", status=lc.BLOCKED, http=403))
    assert not v2["provenance"].get("needs_human_review"), \
        "a 403 must not flag a venue for review — it tells us nothing"

    v3 = {"id": "z"}
    lc.record_on_venue(v3, lc.LinkResult(url="u", status=lc.DEAD, http=404))
    assert v3["provenance"]["needs_human_review"] is True


def test_record_stamps_todays_date():
    v = {}
    lc.record_on_venue(v, lc.LinkResult(url="u", status=lc.OK, http=200))
    assert v["provenance"]["link_check"]["checked"] == dt.date.today().isoformat()


def test_link_check_never_touches_score_or_status():
    v = {"id": "x", "score": 90, "status": "active", "signals": {"listening_room": 5}}
    before = dict(v)
    lc.record_on_venue(v, lc.LinkResult(url="u", status=lc.DEAD, http=404))
    assert v["score"] == before["score"]
    assert v["status"] == before["status"]
    assert v["signals"] == before["signals"]


def test_empty_url_is_skipped_not_failed():
    r = lc.check_url("")
    assert r.status == lc.SKIPPED
    assert not r.needs_attention


def test_missing_crawler_dependency_never_becomes_venue_evidence():
    """A library missing on our machine must not be recorded as a dead venue.

    The first automated sweep wrote 'The crawler needs the crawl extra' into all
    263 records' provenance as if it were a finding about those venues. Local
    incapacity and remote absence are different facts and must stay different.
    """
    from atlas import crawl

    venue = {"id": "x", "website": "https://example.org/",
             "provenance": {"last_content_hash": "abc123"}}

    def boom(*a, **kw):
        raise crawl.CrawlerUnavailable("no requests installed")

    original = crawl.fetch
    crawl.fetch = boom
    try:
        raised = False
        try:
            crawl.recrawl(venue)
        except crawl.CrawlerUnavailable:
            raised = True
        assert raised, "recrawl must propagate CrawlerUnavailable, not swallow it"
        assert "last_crawl_error" not in venue["provenance"]
        assert venue["provenance"]["last_content_hash"] == "abc123"
    finally:
        crawl.fetch = original


def test_network_failure_is_still_recorded():
    """A genuine fetch failure *is* evidence, and must be kept."""
    from atlas import crawl

    venue = {"id": "y", "website": "https://example.org/", "provenance": {}}
    original = crawl.fetch
    crawl.fetch = lambda *a, **kw: (_ for _ in ()).throw(OSError("dns went away"))
    try:
        res = crawl.recrawl(venue)
        assert res.outcome == "gone"
        assert "dns went away" in venue["provenance"]["last_crawl_error"]
    finally:
        crawl.fetch = original
