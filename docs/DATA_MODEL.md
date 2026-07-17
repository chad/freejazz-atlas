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
collectives: []              # bands / collectives / labels
website: null
confidence: 0.8
provenance:
  added_by: "seed:web-research-2026-07"
  added_on: 2026-07-17
  source_urls: [ … ]
  needs_human_review: false
  note: "Performed at Dissonant Works, Sept 2025."
```

## Provenance & "active this year"

Every record carries provenance: **who added it, when, from what sources, and
whether it still needs human review.** This is what lets the directory be
crowd-maintained *and* trustworthy.

"Active this year" is refreshed two ways: (1) humans updating `last_confirmed`
and `active_this_year`, and (2) the crawler's re-crawl pass (`atlas recrawl`),
which re-fetches each `source_url`, compares a content hash, and flags records
whose pages changed or 404'd — surfacing likely-closed venues without a human
re-reading every page.
