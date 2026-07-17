# The Free Jazz Atlas

**A curated, weighted, constantly-updating directory of venues that genuinely
welcome free jazz, free improvisation, and avant-garde music — and the
musicians keeping them alive.**

Most "jazz venue" lists flatten everything together: the artist-run loft that
programs free improvisation six nights a week sits next to the tourist bar that
books a trad quartet on Sundays. The Free Jazz Atlas exists to tell those apart.
Every venue gets an **explainable commitment score**, so you can see — and
argue with — *why* a place is rated the way it is.

> **Project name.** The repository directory is `freejazz-atlas`; the product
> name is **The Free Jazz Atlas**. "Atlas" because the mission is geographic
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

## Quick start

```bash
# Core toolkit needs only Python 3.9+ and PyYAML:
pip install -e .

atlas stats                 # corpus size + geographic spread
atlas list --min 85         # every Cornerstone venue
atlas list --state IL       # browse by state
atlas show ibeam-brooklyn   # explainable score breakdown
atlas build                 # regenerate site/ + DIRECTORY.md
open site/index.html        # browsable, searchable, self-contained page
```

Browse without any tooling: read [`DIRECTORY.md`](DIRECTORY.md) (generated) or
open `site/index.html` (a single self-contained page with search, tier/state
filters, and an expandable "why this score" breakdown per venue).

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
atlas/            the toolkit (model, rubric, storage, crawler, build, CLI)
data/venues/      one YAML file per venue  (canonical, human-editable)
data/musicians/   one YAML file per musician
docs/RUBRIC.md    the weighting rubric, with worked anchor examples
docs/DATA_MODEL.md the schema
scripts/seed.py   how the seed corpus was generated (calibration record)
site/             generated browsable directory (gitignored)
tests/            rubric calibration + validation tests
```

## Status: what's real vs. stubbed

**Real and working now:**
- The rubric, calibrated to the four anchors and enforced by tests.
- Data model + validation (`atlas validate`), scoring (`atlas score`).
- A seed corpus of **32 venues across 17 states + DC** and **13 active
  musicians**, with per-signal evidence, source URLs, and honest confidence.
- Browsable/queryable outputs: CLI (`list`/`show`/`stats`), `DIRECTORY.md`,
  `directory.json`, and a self-contained static `site/index.html`.
- A live crawler (`atlas crawl`) that fetches a real URL and produces a scored,
  evidence-bearing candidate; and a re-crawl/update mechanism (`atlas recrawl`)
  with content-hash change detection.

**Partial / stubbed (designed, not fully built):**
- Crawler signal extraction is **keyword-heuristic**, deliberately conservative
  and capped. It is triage, not judgement; it does not yet parse structured
  event calendars, identify artists against a roster database, or read Bandcamp
  / social APIs. The re-crawl scheduler is manual (run it on cron); there is no
  hosted service yet.
- Geocoding is by hand (lat/lon in the YAML); no automatic geocoder wired up.
- Musician "still active this year" is human-maintained; no automatic tour-date
  ingestion yet.
- `needs_human_review` entries (~10 venues, several musicians) are known real
  places included for geographic breadth but **not re-verified this session** —
  confidence ~0.5 by design.

**Honesty note.** Curation quality is the entire point. We would rather show a
low confidence and a note about missing evidence than a confident wrong number.
Corrections are welcome and expected.

## License

Code: MIT. Data (`/data`): CC0 1.0 — see [`LICENSE`](LICENSE) and
[`data/README.md`](data/README.md).
