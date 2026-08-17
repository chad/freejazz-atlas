# Data Model

Records are stored as **one YAML file per entity**:

```
data/venues/<venue-id>.yaml
data/musicians/<musician-id>.yaml
```

One file per record keeps diffs small and reviewable — which is what makes
community contribution and moderation tractable. Validation lives in
[`atlas/model.py`](../atlas/model.py); run `atlas validate --strict`.

The model is designed **geography-agnostic from day one** (`country` is ISO-3166
alpha-2), so Phase 2 (Europe) and Phase 3 (Asia) need no schema changes — only
new records.

## Venue

```yaml
id: ibeam-brooklyn            # stable slug; the filename
name: IBeam Brooklyn
aliases: [iBeam]
status: active               # active | dormant | closed | unconfirmed
location:
  address: "168 7th St"      # optional
  city: Brooklyn             # required
  region: NY                 # state / province (US state code, or region)
  country: US                # required; ISO-3166 alpha-2 (Phase 2/3 ready)
  neighborhood: Gowanus      # optional
  lat: 40.6740               # geo-coordinates (for maps / geo-queries)
  lon: -73.9845
type: dedicated_space        # see vocabulary below
operating_model: artist_run  # see vocabulary below
capacity: 50                 # optional int
website: https://…
active_this_year: true       # still presenting this music this year?
signals:                     # the rubric inputs — see docs/RUBRIC.md
  dedicated_series:
    value: 5                 # 0–5
    evidence: "Member-owned space for innovative music; hosts the Brooklyn
      Free Spirit Festival…"
    sources: ["https://www.ibeambrooklyn.com/about-1"]
  show_frequency: { value: 5, evidence: "Live music Tue–Sun." }
  # …artist_roster, self_description, operating_model,
  #   community_reputation, listening_room
score: 98                    # DERIVED from signals (recompute: atlas score)
tier: cornerstone            # DERIVED from score
confidence: 0.9              # 0–1: how sure are we about the score?
provenance:
  added_by: "seed:web-research-2026-07"
  added_on: 2026-07-17
  last_confirmed: 2026-07     # when we last confirmed it's active/accurate
  source_urls: [ … ]
  needs_human_review: false
  last_crawled: null          # set by the crawler
  last_content_hash: null     # set by the crawler (change detection)
notes: "Free-text context."
```

`score` and `tier` are **derived** from `signals`. Edit the signals, then run
`atlas score --write` to refresh them. `atlas validate` warns if a stored score
drifts from its signals.

### Controlled vocabularies

**`status`** — `active`, `dormant`, `closed`, `unconfirmed`

**`type`** — `dedicated_space`, `arts_center`, `diy_space`, `gallery`,
`bar_club`, `presenter` (books into rotating rooms), `festival`,
`record_store`, `university`

**`operating_model`** — `artist_run`, `nonprofit`, `diy_collective`,
`university`, `municipal`, `commercial`

## Musician

```yaml
id: matthew-shipp
name: Matthew Shipp
instruments: [piano]
roles: [performer]            # performer | bandleader | curator | educator | …
home_base: { city: New York, region: NY, country: US }
active_this_year: true       # still performing this year?
associated_venues: [dissonant-works]   # venue ids
collectives: []              # bands / groups the artist is part of
labels: [Mahakala Music]     # record labels that have released their work
website: https://stevehirshdrums.com/   # the artist's own site
socials:                     # their own outbound links, by platform
  bandcamp: https://stevehirsh.bandcamp.com
  instagram: https://www.instagram.com/stevehirshdrums/
dates_url: https://stevehirshdrums.com/ # the page where they publish gigs
confidence: 0.8
provenance:
  added_by: "seed:web-research-2026-07"
  added_on: 2026-07-17
  source_urls: [ … ]
  needs_human_review: false
  note: "Performed at Dissonant Works, Sept 2025."
  label_credits:            # discography evidence, one entry per label
    - label: Mahakala Music
      releases: 16
      release_titles: [Alien Skin, Ebb & Flow, …]
      years: "2021–2026"
      verified_on: 2026-08-17
```

### `labels` and `provenance.label_credits`

A label that releases free jazz has, by definition, already curated a list of
free jazz musicians — with instruments, groups and dates attached. That makes
label catalogues the cheapest high-quality way to grow the artist corpus, which
is what the rubric's `artist_roster` signal will eventually be measured against.

`labels` is the simple list; `provenance.label_credits` is the evidence behind
it, so a claim like "Steve Hirsh is a working improviser" can be checked rather
than taken on trust. Import with:

```bash
python scripts/import_label_catalog.py \
  --catalog ~/src/mahakala/data/catalog \
  --label "Mahakala Music" --url https://mahakalamusic.com --write
```

The importer's contract matters as much as its output:

- **It never invents.** Instruments and groups come from the release credits;
  release URLs become source URLs. What a catalogue cannot know — home base,
  website, which rooms someone plays — is left `null`, not guessed.
- **It enriches, never overwrites.** On an artist who already exists, curated
  fields (`associated_venues`, `home_base`, `website`, `confidence`, `roles`) are
  preserved untouched; only labels, groups and credits are added.
- **It distinguishes players from personnel.** Engineers, designers and
  liner-notes writers appear in the same credit block as musicians and are
  excluded; a billing like "Chad Fowler, Ivo Perelman, Matthew Shipp" is a
  session line-up rather than a group, so it does not become a `collective`.
- **Exclusions are printed with reasons**, so the judgement calls are arguable
  instead of invisible.

## Provenance & "active this year"

Every record carries provenance: **who added it, when, from what sources, and
whether it still needs human review.** This is what lets the directory be
crowd-maintained *and* trustworthy.

"Active this year" is refreshed two ways: (1) humans updating `last_confirmed`
and `active_this_year`, and (2) the crawler's re-crawl pass (`atlas recrawl`),
which re-fetches each `source_url`, compares a content hash, and flags records
whose pages changed or 404'd — surfacing likely-closed venues without a human
re-reading every page.


## Event

Gigs live in `data/events/<artist-id>.yaml`, one file per artist, because a tour
is written, reviewed and corrected as a unit.

```yaml
artist_id: steve-hirsh
artist_name: Steve Hirsh
source_url: https://stevehirshdrums.com/
scraped_on: 2026-08-17
method: text                 # jsonld | ics | text
events:
  - id: 9f2c1a55b0de         # stable hash of artist+date+venue+city
    date: '2026-10-15'
    raw: "Oct 15: Elastic Arts, Chicago"    # the source line, verbatim
    venue_name: Elastic Arts
    city: Chicago
    region: ''
    lineup: ''
    method: text
    year_inferred: true      # the source gave no year; this is our inference
    venue_id: elastic-arts   # set ONLY on strong match evidence
    match_score: 1.0
    match_note: name similarity 1.00; city matches (Chicago)
```

### Why events exist, and what they are not allowed to do

Two rubric signals carry 40 of the 100 points — `show_frequency` and
`artist_roster` — and both were pure human estimate until there was a record of
an actual gig. Artist dates pages are the way in: one scrape yields evidence
about a venue (something happened there) *and* an artist-to-venue edge.

Three refusals keep this honest:

- **No invented years.** A line reading "Oct 15" does not say which October.
  The year is inferred from context and stamped `year_inferred: true`, never
  presented as if the source said it.
- **No guessed venue links.** `venue_id` is filled only above a match
  threshold, and `match_note` always records the reasoning — including for the
  misses, so a wrong threshold is debuggable. A familiar name in the wrong city
  is treated as a different room, because it usually is.
- **No automatic re-scoring.** `atlas.events.observed_frequency()` reports what
  we have observed and ships a caveat with the number: the Atlas watches a
  handful of artists, so a low count means our coverage is thin, not that a
  venue is quiet. Reading it the other way round would let a sparse crawl demote
  real rooms.

Unmatched venue names are a feature, not a failure: a room in a touring
musician's itinerary that the Atlas has never heard of is the best lead it gets
on a scene it is missing. The first scrape turned up nine, including five in the
Philippines — a country the corpus did not cover at all.

```bash
atlas artistlinks --probe --write   # find sites, socials, dates pages
atlas events --write                # scrape dates -> gigs + venue links
```
