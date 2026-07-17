# Contributing to Avant Atlas

This directory is only as good as its curation. Corrections, additions, and
honest re-scoring are all welcome — from listeners, from artists, and from
venues themselves.

## The golden rule

**Accuracy over coverage.** Never invent a venue, a musician, or a rating. If
you are not sure how committed a venue is, add it with a **low `confidence`**
and `needs_human_review: true`, and note in `notes` what evidence is missing. A
low-confidence honest entry is valuable; a confident wrong one is not.

## Add or fix a venue (artists & fans)

1. Copy an existing file in `data/venues/` (e.g. `elastic-arts.yaml`) to
   `data/venues/<your-venue-id>.yaml`. The `id` is a lowercase slug and matches
   the filename.
2. Fill in the fields — see [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) for every
   field and the controlled vocabularies.
3. Score it by rating the **seven signals 0–5** using
   [`docs/RUBRIC.md`](docs/RUBRIC.md). For each signal you rate above 0, add an
   `evidence:` line and a source URL. This is what makes the score trustworthy.
4. Set `provenance.added_by` to your name/handle and list your `source_urls`.
5. Recompute and validate:
   ```bash
   atlas score --write     # fills in score + tier from your signals
   atlas validate --strict # checks the schema; fix any errors
   atlas show <your-venue-id>   # eyeball the breakdown
   ```
6. Open a pull request. One venue per PR keeps review easy.

## Add yourself or a peer (musicians)

Copy a file in `data/musicians/`, set `instruments`, `home_base`,
`active_this_year`, and link `associated_venues` by their venue `id`. Provenance
required.

## Self-listing (venues)

Venues are welcome to list themselves. Copy the template, fill it in, and set
`provenance.added_by: "self-listed:<venue>"`. Please score your `signals`
**honestly** — a maintainer verifies against public evidence before merge, and
inflated self-scores will be adjusted down. Being clearly a "Supportive" venue
on an honest map is better than being a disputed "Cornerstone."

## What reviewers check

- Facts are backed by `source_urls`.
- Signals have evidence; `score`/`tier` match the signals (`atlas score`).
- Controlled-vocabulary fields are valid (`atlas validate`).
- Confidence reflects the evidence; unverified claims are flagged.
- No NYC/coastal bias creep — geographic breadth is a feature.

## Running the tools

```bash
pip install -e .            # core (Python 3.9+, PyYAML)
pip install -e '.[crawl]'   # + live crawler (requests, beautifulsoup4)
python -m pytest            # run the calibration + validation tests
```

By contributing you agree that code is licensed MIT and data is dedicated to the
public domain under CC0 1.0.
