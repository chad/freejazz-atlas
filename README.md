# Avant Atlas

**A curated, weighted, constantly-updating directory of venues that genuinely
welcome free jazz, free improvisation, and avant-garde music — and the
musicians keeping them alive.**

Most "jazz venue" lists flatten everything together: the artist-run loft that
programs free improvisation six nights a week sits next to the tourist bar that
books a trad quartet on Sundays. Avant Atlas exists to tell those apart.
Every venue gets an **explainable commitment score**, so you can see — and
argue with — *why* a place is rated the way it is.

> **Project name.** The repository directory is `freejazz-atlas`; the product
> name is **Avant Atlas**. "Atlas" because the mission is geographic
> coverage — small scenes everywhere, not just the coasts.

## The idea in one screen

- **Weighting is the hard part, and the point.** A venue's score (0–100)
  measures *commitment* to this music, built from seven documented signals
  (dedicated series, show frequency, artist roster, self-description, operating
  model, community reputation, listening-room intent). See
  [`docs/RUBRIC.md`](docs/RUBRIC.md).
- **Every score is explainable.** We store the signals and the evidence behind
  the number — not just the number. `atlas show <venue>` prints the full
  breakdown.
- **Calibrated to real anchors.** iBeam (Brooklyn) → **98**. Dissonant Works
  (St. Louis) → **94**. Crosstown Arts (Memphis) → **47** (a broad arts center,
  not free-jazz-dedicated). Arthur's Tavern (West Village) → **10** (a
  commercial bar with occasional trad jazz).
- **US-wide first, not NYC.** The seed corpus deliberately spreads across 17
  states + DC; New York City is only 4 of 32 venues.
- **Built to grow geographically.** `country` is ISO-3166 from day one, so
  Phase 2 (Europe) and Phase 3 (Asia) need new records, not new code.
- **Community-maintained.** Human-editable YAML, one file per venue, full
  provenance. Artists send small PRs; venues can self-list. See
  [`CONTRIBUTING.md`](CONTRIBUTING.md).

**Live at [atlas.run.garden](https://atlas.run.garden).**

## Quick start

```bash
# Core toolkit needs only Python 3.9+ and PyYAML:
pip install -e .

atlas stats                 # corpus size + geographic spread
atlas list --min 85         # every Cornerstone venue
atlas list --state IL       # browse by state
atlas show ibeam-brooklyn   # explainable score breakdown
atlas build                 # generate the 514-page static site + DIRECTORY.md
atlas linkcheck             # is every cited website still reachable?
atlas verify                # ranked queue: what a human should check next
open site/index.html
```

Run the web service (adds the submission form + JSON APIs on top of the site):

```bash
pip install -r requirements.txt
uvicorn web.server:app --port 8000
```

Browse without any tooling: read [`DIRECTORY.md`](DIRECTORY.md) (generated), or
`atlas build --single-page` for a self-contained offline `all-in-one.html`.

## The site is the product surface

`atlas build` emits a real multi-page site — **not** one giant page — because
geographic coverage is the mission and a single URL is invisible to anyone
searching for "free jazz in Lisbon":

```
/                     map + browse (20 KB; the corpus is fetched, not inlined)
/venues/<id>/         one page per venue: score, seven signals, evidence, sources
/cities/<slug>/       every venue in a city          (134 pages)
/regions/<state>/     every venue in a US state       (38 pages)
/countries/<cc>/      every venue in a country        (24 pages)
/artists/<id>/        where an artist plays           (44 pages)
/tiers/<key>/         the rubric's tiers as lists
/rubric/              how scoring works, incl. what it can't do yet
/directory.json       the whole corpus in one fetch
/sitemap.xml          every page, with priorities
```

Every page carries a canonical URL, meta description, Open Graph tags and
schema.org JSON-LD (`MusicVenue` with geo + the commitment score as a
`PropertyValue`; `Person` for artists; `BreadcrumbList` and `ItemList` for
navigation). Tests assert that every venue has a page, every sitemap URL
resolves to a file, all JSON-LD parses, and the front page never grows back
into a 1 MB blob.

## Keeping it honest over time

A venue directory rots — domains lapse, lofts become parking garages. Three
mechanisms fight that, and none of them may silently change a score:

| Command | What it does |
|---|---|
| `atlas linkcheck --write` | Fetches every cited website concurrently and records `ok` / `blocked` / `dead` / `unreachable` in provenance. Deliberately distinguishes **dead** from **blocked**: a 403 from Cloudflare, a 400 from Facebook, or a TLS version mismatch tells us about bot defences, not about the venue. Only 404/410 and DNS failure raise `needs_human_review`. |
| `atlas recrawl --write` | Re-fetches each source page and compares a content hash — `unchanged` / `changed` / `gone`. A changed page flags the record for re-reading rather than re-scoring it. |
| `atlas verify` | Ranks the whole corpus by `score impact × uncertainty` (confidence, missing evidence, source count, staleness, link health) so scarce human attention lands where a wrong number does the most damage. |

[`scripts/refresh.sh`](scripts/refresh.sh) chains all of it and commits the
result, so the corpus keeps its own history. It is meant to run unattended.

The first sweep found and fixed real rot: **18 of 259 cited websites were
broken**; nine were repaired to verified current URLs (recorded in
`provenance.url_corrections`), and the rest are flagged in public on the venue
page itself rather than quietly left to look fine.

## The ingestion engine

The crawler turns a public web source into a **scored venue candidate**:

```bash
pip install -e '.[crawl]'        # adds requests + beautifulsoup4

atlas crawl https://some-venue.org/about --city Chicago --region IL --out cand.yaml
atlas recrawl --write            # re-fetch sources, flag changed/closed venues
```

1. **Fetch** the page politely (identifies itself, times out).
2. **Extract** visible text + metadata.
3. **Approximate** the rubric signals with transparent, inspectable keyword
   lexicons, attaching the evidence snippet that drove each signal.
4. **Emit** a low-confidence `unconfirmed` candidate for a human to verify.

**The crawler never invents a committed venue.** Its signal values are *capped
below the "Cornerstone" range* — the automated pass produces triage, and a human
gate turns triage into curation. The re-crawl pass (`atlas recrawl`) hashes each
source page to detect `unchanged` / `changed` / `gone`, keeping "active this
year" honest over time without re-reading every page by hand.

Sources it is designed to ingest: venue sites, event calendars, artist tour
dates, festival lineups, label/collective sites, Bandcamp, and existing scene
lists/wikis. (See *Status* for what's implemented vs. designed.)

## How to contribute

- **Artists & fans:** add or correct a venue with a one-file YAML PR, or open an
  issue. Add yourself or peers to `data/musicians/`. Full guide in
  [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Venues:** self-list by copying the template and setting
  `operating_model` / `signals` honestly — a maintainer verifies before merge.
- Every entry records **who added it and from what sources.** Low-confidence or
  unverified entries are marked `needs_human_review: true` rather than dropped.

## Repository layout

```
atlas/            the toolkit
  rubric.py       the weights — single source of truth
  model.py        schema + validation
  storage.py      YAML load/save
  crawl.py        fetch a source -> scored candidate; content-hash re-crawl
  linkcheck.py    is the cited evidence still reachable?
  site.py         the multi-page static site generator
  build.py        orchestration: site + directory.json + DIRECTORY.md
  cli.py          the `atlas` command
web/server.py     HTTP service: serves the site, submissions, JSON API
data/venues/      one YAML file per venue  (canonical, human-editable)
data/musicians/   one YAML file per musician
docs/RUBRIC.md    the weighting rubric, with worked anchor examples
docs/DATA_MODEL.md the schema
scripts/seed.py   how the seed corpus was generated (calibration record)
scripts/refresh.sh unattended freshness sweep (link health, re-crawl, rebuild)
deploy/           launchd + systemd units
.miren/app.toml   deployment config
site/             generated site (gitignored — rebuild with `atlas build`)
tests/            rubric calibration, validation, link health, site integrity
```

## Status: what's real vs. stubbed

**Real and working now:**
- The rubric, calibrated to four anchors and enforced by tests.
- Data model + validation (`atlas validate`), scoring (`atlas score`).
- A corpus of **263 venues in 134 cities across 24 countries** and **44
  musicians**, with per-signal evidence, source URLs and honest confidence.
- A 514-page static site with full crawler metadata, plus `DIRECTORY.md`,
  `directory.json` and a JSON API.
- Link health, content-hash change detection, and a ranked verification queue.
- 32 tests covering rubric calibration, validation, link classification, and
  site integrity (including HTML escaping of community-supplied text).

**Known limitations — stated plainly:**

- **The corpus is LLM-seeded, not human-verified.** Every record's provenance
  says `seed:web-research-2026-07`; 77 are flagged `needs_human_review` and 10
  have no source URLs at all. `atlas verify` exists precisely because this is
  the project's weakest property. Venue pages say so where it applies.
- **No event data yet, so 40 of the 100 points are estimates.**
  `show_frequency` (20) and `artist_roster` (20) are human judgements because
  the Atlas does not yet ingest calendars. This is the biggest open gap; see
  below.
- **The corpus skews high** — 61 cornerstones, only 9 venues below 45 — because
  the seed pass went looking for good venues. A rubric whose corpus has no
  negative space is not being tested very hard.
- Crawler signal extraction is **keyword-heuristic** and capped below
  "cornerstone" by design: triage, not judgement.
- Geocoding is by hand. Musician activity is human-maintained. There are no
  contact/booking fields yet.

**Honesty note.** Curation quality is the entire point. We would rather show a
low confidence and a note about missing evidence than a confident wrong number.
Corrections are welcome and expected.

## What's next, in leverage order

1. **Events.** Gigs are the verbs; venues are only the nouns. Platform adapters
   (WordPress `tribe/events`, Squarespace JSON, Bandcamp, Eventbrite, Dice)
   cover roughly 40–50% of the corpus with structured data; an LLM pass over
   calendar HTML covers much of the tail. A probe of 60 venue sites found
   JSON-LD `Event` on only 4% but a known CMS on 62%, so adapters — not
   schema.org — are the way in. Once shows are ingested, `show_frequency` and
   `artist_roster` become *measurements*, and a room that stops programming
   drifts down on its own.
2. **Artist graph, 44 → thousands.** Label rosters and festival lineups
   (MusicBrainz, Bandcamp, Clean Feed, Intakt, Astral Spirits, Catalytic Sound,
   Trost…) give the roster signal something to match against, and artist↔venue
   edges then fall out of event data for free.
3. **Contact + booking fields.** `contact`, `booker`, `pay_model`, PA/piano,
   accessibility, capacity (only 99/263 have it). This is what makes touring
   musicians want to maintain the data.
4. **Verification passes** down the `atlas verify` queue, starting with the 10
   zero-source records.

## License

Code: MIT. Data (`/data`): CC0 1.0 — see [`LICENSE`](LICENSE) and
[`data/README.md`](data/README.md).
