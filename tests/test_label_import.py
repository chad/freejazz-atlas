"""Tests for the label-catalogue importer.

Release credits are free text typed by whoever made the record, so the parser is
the part most likely to quietly produce nonsense — a mangled name, an engineer
filed as a saxophonist, or a session line-up recorded as if it were a band.
Each test below corresponds to something the Mahakala Music import actually got
wrong before it was fixed.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

SPEC = importlib.util.spec_from_file_location(
    "label_import",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "import_label_catalog.py")
li = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(li)


# --- credit line splitting --------------------------------------------------
def test_splits_both_separator_styles():
    assert li.split_credit("William Parker - bass") == ("William Parker", "bass")
    assert li.split_credit("Matt Lavelle: pocket trumpet") == ("Matt Lavelle",
                                                               "pocket trumpet")


def test_hyphenated_surnames_survive():
    """A naive dash split decapitates gabby fluke-mogul and Gilman-Opalsky."""
    name, instr = li.split_credit("gabby fluke-mogul - violin")
    assert name == "gabby fluke-mogul"
    assert instr == "violin"
    name, instr = li.split_credit("Richard Gilman-Opalsky: drums, percussion")
    assert name == "Richard Gilman-Opalsky"


# --- instrument normalisation -----------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("drumset", "drums"),
    ("drum set", "drums"),
    ("tenor sax", "tenor saxophone"),
    ("tenor saxophones", "tenor saxophone"),
    ("bari sax", "baritone saxophone"),
    ("contrabass", "bass"),
    ("double bass", "bass"),
    ("vocals", "voice"),
    ("Yellow Fever keyboard", "keyboards"),
    ("contabass sax", "contrabass saxophone"),  # typo in the source catalogue
])
def test_instrument_canonicalisation(raw, expected):
    assert li.canon_instrument(raw) == expected


@pytest.mark.parametrize("raw", [
    "graphic design", "mastering", "liner notes", "cover art", "photography",
    "compositions", "text by anne e elias", "video assistance", "",
    "opalsky: drums",  # a mis-split line, not an instrument
])
def test_non_instruments_are_rejected(raw):
    assert li.canon_instrument(raw) is None


def test_unusual_but_real_instruments_are_kept():
    """This music is full of odd horns; the importer must not flatten them."""
    for raw in ("stritch", "saxello", "shakuhachi", "fujara", "tubax",
                "c melody sax", "pocket trumpet", "bass clarinet"):
        assert li.canon_instrument(raw), raw


# --- group vs. session billing ----------------------------------------------
NAMES = {"Chad Fowler", "Ivo Perelman", "Matthew Shipp", "William Parker",
         "Steve Hirsh", "Eri Yamamoto", "Kelley Hurt", "Christopher Parker",
         "Matt Lavelle", "Adam Linz", "Alden Ikeda", "George Cartwright"}
LABEL = "Mahakala Music"


@pytest.mark.parametrize("billing", [
    "Dopolarians",
    "Blue Reality Quartet",
    "Matt Lavelle and the 12 Houses",
    "Eri Yamamoto Quadraphonic",
    "Christopher Parker & the Band of Guardian Angels",
    "(D)IVO Saxophone Quartet",
])
def test_real_group_names_are_kept(billing):
    assert li.is_group_name(billing, "Chad Fowler", NAMES, LABEL)


@pytest.mark.parametrize("billing", [
    "Chad Fowler, Ivo Perelman, Matthew Shipp, William Parker, Steve Hirsh",
    "Chad Fowler and Matt Lavelle",
    "Eri Yamamoto",                       # the artist's own name
    "Christopher Parker & Kelly Hurt",    # misspelt name, still just a duo
    "Mahakala Music",                     # the label, on compilations
])
def test_session_billings_are_not_groups(billing):
    assert not li.is_group_name(billing, "Chad Fowler", NAMES, LABEL)


def test_personnel_lists_are_stripped_from_group_names():
    assert li.clean_billing(
        "Sparks Quartet (Eri Yamamoto, Chad Fowler, William Parker, Steve Hirsh)"
    ) == "Sparks Quartet"
    assert li.clean_billing(
        "George Cartwright's GloryLand PonyCat with Adam Linz and Alden Ikeda"
    ) == "George Cartwright's GloryLand PonyCat"


def test_short_parentheticals_are_part_of_the_name():
    """(D)IVO is a pun the group uses, not an aside to be discarded."""
    assert li.clean_billing("(D)IVO Saxophone Quartet") == "(D)IVO Saxophone Quartet"


# --- record building --------------------------------------------------------
def _data(**kw):
    import collections
    base = {"instr": collections.Counter({"drums": 3}), "releases": ["a", "b"],
            "bands": collections.Counter({"Dopolarians": 2}),
            "urls": ["https://label.example/album/a"], "years": ["2021", "2024"],
            "titles": ["Album A", "Album B"]}
    base.update(kw)
    return base


def test_new_record_leaves_unknowable_fields_empty():
    """The catalogue cannot know where someone lives. It must not guess."""
    rec = li.build_record("Steve Hirsh", _data(), label=LABEL,
                          label_url="https://label.example", existing=None,
                          all_names=NAMES)
    assert rec["id"] == "steve-hirsh"
    assert rec["instruments"] == ["drums"]
    assert rec["home_base"] == {"city": None, "region": None, "country": None}
    assert rec["associated_venues"] == []
    assert rec["website"] is None
    assert rec["active_this_year"] is None
    assert rec["labels"] == [LABEL]
    assert rec["provenance"]["needs_human_review"] is True


def test_existing_curation_is_never_overwritten():
    existing = {
        "id": "william-parker", "name": "William Parker",
        "instruments": ["double bass"], "roles": ["performer", "curator"],
        "home_base": {"city": "New York", "region": "NY", "country": "US"},
        "active_this_year": True,
        "associated_venues": ["the-stone", "ibeam-brooklyn"],
        "collectives": ["Arts for Art / Vision Festival"],
        "website": "https://example.org", "confidence": 0.8,
        "provenance": {"added_by": "seed:web-research-2026-07",
                       "source_urls": ["https://prior.example"]},
    }
    rec = li.build_record("William Parker", _data(), label=LABEL,
                          label_url="https://label.example", existing=existing,
                          all_names=NAMES)
    assert rec["associated_venues"] == ["the-stone", "ibeam-brooklyn"]
    assert rec["home_base"]["city"] == "New York"
    assert rec["website"] == "https://example.org"
    assert rec["confidence"] == 0.8
    assert rec["active_this_year"] is True
    assert rec["roles"] == ["performer", "curator"]
    assert rec["provenance"]["added_by"] == "seed:web-research-2026-07"
    # ...and the new information is additive
    assert "double bass" in rec["instruments"] and "drums" in rec["instruments"]
    assert "Arts for Art / Vision Festival" in rec["collectives"]
    assert "Dopolarians" in rec["collectives"]
    assert "https://prior.example" in rec["provenance"]["source_urls"]


def test_label_credits_record_titles_not_slugs():
    rec = li.build_record("Steve Hirsh", _data(), label=LABEL, label_url="",
                          existing=None, all_names=NAMES)
    credit = rec["provenance"]["label_credits"][0]
    assert credit["releases"] == 2
    assert credit["release_titles"] == ["Album A", "Album B"]
    assert credit["years"] == "2021\u20132024"


def test_reimport_does_not_duplicate_credits():
    rec = li.build_record("Steve Hirsh", _data(), label=LABEL, label_url="",
                          existing=None, all_names=NAMES)
    again = li.build_record("Steve Hirsh", _data(), label=LABEL, label_url="",
                            existing=rec, all_names=NAMES)
    assert len(again["provenance"]["label_credits"]) == 1
    assert again["labels"] == [LABEL]
    assert again["instruments"] == ["drums"]


def test_editorial_exclusions_are_declared_with_reasons():
    """Excluding someone is an editorial act; it must be stated, not hidden."""
    assert "Zoh Amba" in li.EXCLUDE
    assert "Brian Blade" in li.EXCLUDE
    for name, reason in li.EXCLUDE.items():
        assert len(reason) > 10, f"{name} excluded without a real reason"


def test_slugify_handles_accents_and_quotes():
    assert li.slugify("Iva Bittov\u00e1") == "iva-bittova"
    assert li.slugify('Edward "Kidd" Jordan') == "edward-kidd-jordan"
    assert li.slugify("gabby fluke-mogul") == "gabby-fluke-mogul"
