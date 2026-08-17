#!/usr/bin/env python3
"""Import a record label's catalogue into data/musicians/.

Why this exists
---------------
The Atlas's `artist_roster` signal asks "what share of the booked artists are
recognized improvisers?" — a question the project cannot currently answer,
because 44 musicians is far too small a set to match booking listings against.
Label rosters are the cheapest high-quality source of that set: a label that
releases free jazz has, by definition, curated a list of free jazz musicians,
with instruments, band groupings, and dates already attached.

This is the first such import. It reads a Bandcamp-derived catalogue (one JSON
file per release, with a `credits` block) and merges the credited performers
into the musician corpus.

Rules it follows, because a directory that invents things is worthless
---------------------------------------------------------------------
* **Nothing is invented.** Instruments and band names come from the credits;
  release URLs become source URLs. Fields the catalogue cannot know — home
  base, venue links, website — are left absent rather than guessed.
* **Existing records are enriched, never overwritten.** Human-curated fields
  (`associated_venues`, `home_base`, `website`, `confidence`) are preserved
  exactly; only label/collective/provenance information is added.
* **Non-performers are excluded.** Engineers, designers, photographers and
  liner-notes writers are credited in the same block as musicians; they are not
  musicians and must not enter the corpus as if they were.
* **Exclusions are explicit and printed.** Every dropped name is reported with
  a reason, so the judgement calls can be argued with rather than discovered
  later.

Usage:
    python scripts/import_label_catalog.py --catalog ~/src/mahakala/data/catalog \\
        --label "Mahakala Music" --url https://mahakalamusic.com [--write]
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas import storage  # noqa: E402

# --- credit-line parsing ----------------------------------------------------
# Credits are free text written by whoever made the record, so both "Name -
# instrument" and "Name: instrument" appear, sometimes in the same catalogue.
# The colon form is tried first and the dash form requires surrounding spaces,
# because hyphenated surnames are common in this music (gabby fluke-mogul,
# Richard Gilman-Opalsky) and a naive dash split decapitates them.
CREDIT_COLON = re.compile(r"^([^:]{2,42}?)\s*:\s*(.+)$")
CREDIT_DASH = re.compile(r"^(.{2,42}?)\s+[\-\u2013]\s+(.+)$")


def split_credit(line: str):
    for rx in (CREDIT_COLON, CREDIT_DASH):
        m = rx.match(line)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None

# Lines that describe production rather than performance.
NON_PERFORMER_LINE = re.compile(
    r"^(recorded|rec\.|mixed|mixing|mastered|mastering|produced|producer|"
    r"engineer|engineering|recording|cover|design|graphic|artwork|art work|"
    r"photo|photography|photograph|liner|layout|art direction|executive|"
    r"all compositions|composition|composed|jewelry|group photo|musician photo|"
    r"back tray|original artwork|drums$|saxophone|bass$|piano$|guitar$|"
    r"tracks?\b|\u2022|\d+[\.\)]|ankhitek$|art$|mahakala)", re.I)

# Role words that mean the person contributed something other than playing.
ROLE_WORDS = re.compile(
    r"(design|photograph|liner note|mastering|engineer|mixing|recording|"
    r"artwork|cover art|covert art|poetry|text by|prepared by|arranged by|"
    r"lyrics by|video|assistance|producer|\u00a9)", re.I)

# Words that mean the person did play something.
INSTRUMENT_WORDS = re.compile(
    r"(sax|drum|bass|piano|guitar|trumpet|vocal|voice|violin|viola|cello|"
    r"clarinet|flute|trombone|horn|reed|wind|percussion|conga|bongo|vibra|"
    r"keyboard|keys|cornet|melodica|electronic|synth|banjo|mandolin|oud|tuba|"
    r"shakuhachi|gong|bassoon|piccolo|stritch|strich|saxello|didgeridoo|"
    r"digeridoo|fujara|balafon|steel|tubax|evi|pipe)", re.I)

# Names written inconsistently across the catalogue, or in ALL CAPS.
NAME_ALIASES = {
    "CHAD FOWLER": "Chad Fowler",
    "MATT LAVELLE": "Matt Lavelle",
    "KEN FILIANO": "Ken Filiano",
    "BOBBY KAPP": "Bobby Kapp",
    "Bobby Lavell": "Bobby LaVell",
    "Chris Parker": "Christopher Parker",
    "Kidd Jordan": 'Edward "Kidd" Jordan',
    "ZA": "Zoh Amba",
    "Marvin Bugalu Smith": 'Marvin "Bugalu" Smith',
    "Pheeroan AkLaff": "Pheeroan akLaff",
    "jon irabagon": "Jon Irabagon",
    # gabby fluke-mogul styles their name in lower case; that is not a typo and
    # is deliberately left alone.
}

# Names in the credits that are not people at all (headings, stray fragments).
NOT_A_PERSON = {
    "art", "drums", "graphic design", "liner notes", "mixing/mastering",
    "original artwork", "mahakala executive producer", "saxophone / doodley pipe",
    "recording assistant", "ankhitek", "back tray image by", "group photography",
    "artwork and graphic design", "recording engineer, mixing", "jewelry",
    "all compositions", "musician photo",
}

# Excluded by explicit editorial decision, with the reason recorded.
EXCLUDE = {
    "Zoh Amba": "excluded at the label's request",
    "Brian Blade": "guest sideman; a mainstream jazz drummer rather than a "
                   "free jazz / creative music player",
}

# Credited for production work under their own name on some releases and for
# playing on others; keep them, but only their playing credits.
INSTRUMENT_CANON = [
    (r"^(drumset|drum set|drum kit|drums?)$", "drums"),
    (r"^(tenor sax|tenor saxophone|tenor)$", "tenor saxophone"),
    (r"^(alto sax|alto saxophone|alto)$", "alto saxophone"),
    (r"^(bari sax|baritone sax|baritone saxophone|baritone)$", "baritone saxophone"),
    (r"^(soprano sax|soprano saxophone|soprano)$", "soprano saxophone"),
    (r"^(sopranino sax|sopranino saxophone|sopranino)$", "sopranino saxophone"),
    (r"^(saxophones?|saxes|sax)$", "saxophone"),
    (r"^(contrabass|double bass|upright bass|upright|acoustic bass|bass)$", "bass"),
    (r"^(electric bass|bass guitar)$", "electric bass"),
    (r"^(vocals?|voice|singing)$", "voice"),
    (r"^(electric guitar|guitars?)$", "guitar"),
    (r"^(keyboards?|keys)$", "keyboards"),
    (r".*keyboard.*", "keyboards"),
    (r"^contabass sax.*$", "contrabass saxophone"),  # source typo
    (r"^contrabass sax.*$", "contrabass saxophone"),
    (r"^(percussions?)$", "percussion"),
    (r"^(strich|stritch)$", "stritch"),
    (r"^(pocket trumpet)$", "pocket trumpet"),
    (r"^(bass clarinet)$", "bass clarinet"),
    (r"^(alto clarinets?|alto clarinet)$", "alto clarinet"),
    (r"^(clarinets?)$", "clarinet"),
    (r"^(flutes?)$", "flute"),
    (r"^(alto flute)$", "alto flute"),
    (r"^(bass flute)$", "bass flute"),
    (r"^(winds?|woodwinds?)$", "winds"),
    (r"^(reeds?)$", "reeds"),
    (r"^(trumpets?)$", "trumpet"),
    (r"^(trombones?)$", "trombone"),
    (r"^(violins?)$", "violin"),
    (r"^(violas?)$", "viola"),
    (r"^(cellos?)$", "cello"),
    (r"^(electronics?)$", "electronics"),
    (r"^(modular synthesizer|synthesizer|synth)$", "synthesizer"),
    (r"^(vibraphone|vibes)$", "vibraphone"),
    (r"^(french horn)$", "french horn"),
    (r"^(english horn)$", "english horn"),
]

# Instrument strings that are really performance notes, not instruments.
INSTRUMENT_JUNK = re.compile(
    r"^(tr\.?\s*\d|track|and|the|on|with|plus|etc|various|misc|sounds?|such|"
    r"prerecorded|pre-recorded|compositions?|composer|arranger|arrangements?|"
    r"leader|conductor|\d+)$", re.I)


def slugify(name: str) -> str:
    s = name.lower()
    s = (s.replace("\u2019", "").replace("'", "").replace('"', "")
          .replace("\u00e1", "a").replace("\u00e9", "e").replace("\u00ed", "i")
          .replace("\u00f3", "o").replace("\u00fa", "u").replace("\u00e0", "a")
          .replace("\u00e8", "e").replace("\u00e4", "a").replace("\u00f6", "o")
          .replace("\u00fc", "u").replace("\u00e5", "a").replace("\u00f8", "o")
          .replace("\u00e7", "c").replace("\u00f1", "n"))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def canon_instrument(raw: str) -> str | None:
    i = raw.strip().lower().strip(" .;")
    i = re.sub(r"\s+", " ", i)
    # A colon surviving this far means the line was mis-split, not an instrument.
    if not i or ":" in i or len(i) > 30 or INSTRUMENT_JUNK.match(i):
        return None
    if ROLE_WORDS.search(i) and not INSTRUMENT_WORDS.search(i):
        return None
    for pat, canon in INSTRUMENT_CANON:
        if re.match(pat, i):
            return canon
    # Credits pluralise freely ("tenor saxophones", "alto clarinets"); try the
    # singular before giving up and keeping the raw string.
    if i.endswith("s"):
        for pat, canon in INSTRUMENT_CANON:
            if re.match(pat, i[:-1]):
                return canon
    return i if INSTRUMENT_WORDS.search(i) else None


def parse_catalog(catalog_dir: str) -> tuple[dict, int]:
    """Return {name: {instruments, releases, bands, urls}} and a release count."""
    people: dict = collections.defaultdict(
        lambda: {"instr": collections.Counter(), "releases": [],
                 "bands": collections.Counter(), "urls": [], "years": [],
                 "titles": []})
    files = sorted(glob.glob(os.path.join(catalog_dir, "releases", "*.json")))
    if not files:
        files = sorted(glob.glob(os.path.join(catalog_dir, "*.json")))
    for f in files:
        try:
            d = json.load(open(f))
        except Exception as e:
            print(f"  ! skipping {f}: {e}", file=sys.stderr)
            continue
        band = (d.get("artist") or "").strip()
        url = d.get("url") or ""
        year = (d.get("releaseDate") or "")[:4]
        for line in (d.get("credits") or "").splitlines():
            line = line.strip().strip("*").strip()
            if not line or NON_PERFORMER_LINE.match(line):
                continue
            parts = split_credit(line)
            if not parts:
                continue
            name, instr_text = parts[0].strip(" .*\u2022"), parts[1]
            # Parentheticals are performance notes ("voice (tr. 1, 5)") and
            # contain commas, so they must go before the instrument split.
            instr_text = re.sub(r"\(.*?\)", "", instr_text)
            name = NAME_ALIASES.get(name, NAME_ALIASES.get(name.upper(), name))
            if name.lower() in NOT_A_PERSON:
                continue
            if not re.match(r"^[A-Za-z\u00c0-\u017f]", name) or len(name.split()) > 4:
                continue
            # Periods separate a player's instruments from trailing sentences
            # ("pocket trumpet. Compositions by..."), so they split too.
            instruments = [c for c in
                           (canon_instrument(x) for x in
                            re.split(r"[,;/&.]|\band\b|\+", instr_text))
                           if c]
            if not instruments:
                continue  # credited, but not for playing anything
            p = people[name]
            p["releases"].append(d.get("slug") or os.path.basename(f))
            if d.get("title"):
                p["titles"].append(d["title"])
            p["instr"].update(instruments)
            if band:
                p["bands"][band] += 1
            if url:
                p["urls"].append(url)
            if year:
                p["years"].append(year)
    return people, len(files)


CONNECTIVES = {"and", "with", "featuring", "feat", "feat.", "the", "&", "presents",
               "plus", "vs", "meets", "trio's"}


def clean_billing(billing: str) -> str:
    """Strip the personnel list that often trails a real group name.

    "Sparks Quartet (Eri Yamamoto, Chad Fowler, ...)" and "George Cartwright's
    GloryLand PonyCat with Adam Linz and Alden Ikeda" both name a group and then
    enumerate it. The group is the part before the enumeration.
    """
    # Only strip a parenthetical that looks like a personnel list. "(D)IVO
    # Saxophone Quartet" is a pun the group actually uses, not an aside.
    def drop(mm):
        inner = mm.group(1)
        return " " if ("," in inner or len(inner.split()) > 2) else mm.group(0)

    b = re.sub(r"\((.*?)\)", drop, billing).strip()
    b = re.split(r"\s+with\s+", b, maxsplit=1)[0].strip()
    return b.strip(" ,&")


def is_group_name(billing: str, person: str, all_names: set, label: str) -> bool:
    """Is this release billing a group, or just a list of who played?

    Bandcamp's `artist` field holds whatever the release was billed as. For
    "Dopolarians" or "Matt Lavelle and the 12 Houses" that is a real group; for
    "Chad Fowler, Ivo Perelman, Matthew Shipp" it is a session line-up, and for a
    compilation it is the label's own name. Only the first kind belongs in
    `collectives`, so the test is whether the billing contains any word that is
    not simply somebody's name or a connective.
    """
    b = clean_billing(billing)
    if not b or b.lower() == label.lower():
        return False
    name_words = {w.lower().strip('.,"\u201c\u201d')
                  for n in list(all_names) + list(NAME_ALIASES) + [person]
                  for w in n.split()}
    for word in re.split(r"[\s,/]+", b):
        w = re.sub(r"[’']s$", "", word.lower()).strip('.,"\u201c\u201d()’\'')
        if not w or w in CONNECTIVES or w in name_words:
            continue
        # Names are spelled inconsistently across a catalogue ("Kelly" for
        # "Kelley"), so a near miss still counts as a name, not a group word.
        if difflib.get_close_matches(w, name_words, n=1, cutoff=0.86):
            continue
        return True
    return False


def build_record(name: str, data: dict, *, label: str, label_url: str,
                 existing: dict | None, all_names: set) -> dict:
    """Create or enrich one musician record."""
    today = _dt.date.today().isoformat()
    instruments = [i for i, _ in data["instr"].most_common()]
    bands = []
    for b, _ in data["bands"].most_common():
        if is_group_name(b, name, all_names, label):
            g = clean_billing(b)
            if g not in bands:
                bands.append(g)
    releases = sorted(set(data["releases"]))
    # Titles, not slugs: a slug like "alien-skin" cannot be turned back into a
    # title reliably, and guessing produced nonsense like "skin".
    titles = sorted(set(data["titles"]))
    years = sorted(set(data["years"]))

    rec = dict(existing) if existing else {}
    rec.setdefault("id", slugify(name))
    rec.setdefault("name", name)

    # Instruments: union, catalogue order first, never dropping what a human set.
    have = list(rec.get("instruments") or [])
    for i in instruments:
        if i not in have:
            have.append(i)
    rec["instruments"] = have

    rec.setdefault("roles", ["performer"])
    if existing is None:
        # The catalogue cannot know where someone lives. Say so rather than guess.
        rec["home_base"] = {"city": None, "region": None, "country": None}
        rec["active_this_year"] = None
        rec["associated_venues"] = []
        rec["website"] = None
        # Identity and instruments are well-sourced; the record as a whole is
        # thin until a human fills in the rest.
        rec["confidence"] = 0.6

    coll = list(rec.get("collectives") or [])
    for b in bands:
        if b not in coll:
            coll.append(b)
    rec["collectives"] = coll

    labels = list(rec.get("labels") or [])
    if label not in labels:
        labels.append(label)
    rec["labels"] = labels

    prov = rec.setdefault("provenance", {})
    prov.setdefault("added_by", f"label-catalog:{slugify(label)}")
    prov.setdefault("added_on", today)
    srcs = prov.setdefault("source_urls", [])
    for u in ([label_url] + sorted(set(data["urls"]))[:4]):
        if u and u not in srcs:
            srcs.append(u)
    disco = prov.setdefault("label_credits", [])
    entry = {"label": label, "releases": len(releases),
             "release_titles": titles[:12],
             "years": f"{years[0]}\u2013{years[-1]}" if len(years) > 1 else (years[0] if years else None),
             "verified_on": today}
    disco[:] = [d for d in disco if d.get("label") != label] + [entry]
    prov["needs_human_review"] = True
    prov["review_note"] = (
        "Imported from the label catalogue: name, instruments, groups and "
        "release credits are sourced. Home base, website and venue links are "
        "still unknown \u2014 those are what a human should add."
        if existing is None else
        prov.get("review_note", "Label credits added by catalogue import; "
                                "existing curation left untouched."))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", required=True,
                    help="directory containing releases/*.json")
    ap.add_argument("--label", required=True, help='e.g. "Mahakala Music"')
    ap.add_argument("--url", default="", help="label homepage")
    ap.add_argument("--write", action="store_true", help="write YAML files")
    ap.add_argument("--min-releases", type=int, default=1,
                    help="skip performers with fewer credits than this")
    args = ap.parse_args()

    people, n_releases = parse_catalog(os.path.expanduser(args.catalog))
    existing = {m["id"]: m for m in storage.load_musicians()}

    print(f"{args.label}: {n_releases} releases, "
          f"{len(people)} credited performers\n")

    dropped, created, enriched = [], [], []
    for name, data in sorted(people.items(), key=lambda kv: -len(kv[1]["releases"])):
        if name in EXCLUDE:
            dropped.append((name, EXCLUDE[name]))
            continue
        if len(set(data["releases"])) < args.min_releases:
            dropped.append((name, f"only {len(set(data['releases']))} credit(s)"))
            continue
        mid = slugify(name)
        prior = existing.get(mid)
        rec = build_record(name, data, label=args.label, label_url=args.url,
                           existing=prior, all_names=set(people))
        target = (created if prior is None else enriched)
        target.append((rec, len(set(data["releases"]))))
        if args.write:
            path = str(storage.MUSICIANS_DIR / f"{rec['id']}.yaml")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(storage.dump_record(rec))

    print(f"NEW ({len(created)}):")
    for rec, n in created:
        print(f"  {n:2}  {rec['name']:28.28s} {', '.join(rec['instruments'][:4])}")
    print(f"\nENRICHED ({len(enriched)}):")
    for rec, n in enriched:
        print(f"  {n:2}  {rec['name']:28.28s} "
              f"(kept {len(rec.get('associated_venues') or [])} venue link(s))")
    print(f"\nEXCLUDED ({len(dropped)}):")
    for name, why in dropped:
        print(f"      {name:28.28s} {why}")

    if not args.write:
        print("\n(dry run \u2014 pass --write to create/update data/musicians/)")
    else:
        print(f"\nWrote {len(created) + len(enriched)} record(s). "
              f"Run `atlas validate` and `atlas build`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
