# The Weighting Rubric

This is the heart of the Free Jazz Atlas. It answers one question for every
venue:

> **How committed is this place to free jazz, free improvisation, and
> avant-garde / experimental music?**

A high score means the venue *exists to present this music*. A low score means
the music shows up there only occasionally or incidentally. The rubric is
designed so a human can apply it by hand, and so the crawler can approximate it
automatically — and so **every score is explainable**: you can always read the
signals and evidence behind the number.

The machine-readable source of truth for the weights is
[`atlas/rubric.py`](../atlas/rubric.py). Keep this document in sync with it.

## The score

Each venue gets a **0–100 score**, the sum of **seven weighted signals**. Each
signal is rated **0–5** by a human (or approximated by the crawler), then scaled
to its point weight:

| Signal | Weight | What it measures |
|---|---:|---|
| **Dedicated series / mission** | 25 | Is there a named recurring series/festival for free/improvised/experimental music — or is that music the venue's reason to exist? |
| **Frequency of relevant shows** | 20 | How often does genuinely free/avant/improvised music actually happen here? |
| **Artist roster** | 20 | What share of booked artists are recognized improvisers / experimental musicians? |
| **Self-description** | 12 | Does the venue describe *itself* as experimental / improvised / adventurous / creative music? |
| **Operating model** | 10 | Artist-run / DIY / mission-driven nonprofit (high) vs. commercial / tourist (low)? |
| **Community reputation** | 8 | Do scene participants, press, and scene lists name it as a home for the music? |
| **Listening-room intent** | 5 | Programmed as attentive listening vs. background music in a bar? |
| **Total** | **100** | |

`points = (value / 5) × weight`, summed and rounded.

### The 0–5 scale, in words

- **5** — defining. This *is* what the venue does.
- **4** — strong and regular.
- **3** — a real, recurring commitment (e.g. a monthly series).
- **2** — present but secondary.
- **1** — rare / incidental.
- **0** — absent.

## Tiers

| Tier | Range | Meaning |
|---|---:|---|
| **Cornerstone** | 85–100 | Exists to present this music. A pilgrimage venue. |
| **Committed** | 65–84 | A real, regular home for the music. |
| **Supportive** | 45–64 | Books it meaningfully, but as part of a broader program. |
| **Occasional** | 25–44 | Appears now and then; not a scene anchor. |
| **Incidental** | 0–24 | Mostly other music; free/avant is rare or accidental. |

## Confidence is separate from score

Score answers *"how committed is this venue?"* Confidence (`0.0–1.0`) answers
*"how sure are we about that score?"* A venue we cannot verify gets a **low
confidence**, never a made-up score. Seed entries verified via web research this
session sit around `0.8–0.9`; well-known venues we did not re-verify are marked
`~0.5` with `needs_human_review: true`. **When unsure, lower the confidence and
record what evidence is missing** — do not inflate the score.

## Calibration anchors (worked by hand)

The rubric is calibrated so these four real venues land where they should.

### IBeam Brooklyn — VERY HIGH → **98, Cornerstone**
Member-owned, artist-run room for innovative music; live music Tue–Sun; hosts
the Brooklyn Free Spirit Festival.

| Signal | Value | Points |
|---|---:|---:|
| Dedicated series/mission | 5 | 25 |
| Frequency | 5 | 20 |
| Artist roster | 5 | 20 |
| Self-description | 5 | 12 |
| Operating model | 5 | 10 |
| Community reputation | 4 | 6.4 |
| Listening room | 5 | 5 |
| **Total** | | **≈98** |

### Dissonant Works (St. Louis) — VERY HIGH → **94, Cornerstone**
Volunteer-run 501(c)(3) dedicated to experimental art and music; books
improvisers like Matthew Shipp; runs an experimental-sound archive.
Frequency scored 4 (regular, not nightly) → **94**.

### Crosstown Arts (Memphis) — MODERATE → **47, Supportive**
A broad contemporary arts center (visual art, residencies, film, café) that
books *some* adventurous music but is **not** free-jazz-dedicated. Dedicated
series 2, frequency 2, roster 2, self-description 2, operating model 4,
reputation 2, listening room 5 (the Green Room is a genuine listening room) →
**47**. On the list, but clearly separated from the cornerstones.

### Arthur's Tavern (West Village, NYC) — VERY LOW → **10, Incidental**
An 88-year-old commercial neighborhood bar with nightly *traditional* jazz,
blues, and soul. No dedicated series (0), frequency 1, roster 1, self-description
0, operating model 1 (commercial/tourist), reputation 0, listening room 0 →
**10**. Correctly separated from venues committed to the music.

## How the crawler approximates this

The [crawler](../atlas/crawl.py) reads a page and matches transparent keyword
lexicons (strong genre terms, mission terms, series/frequency terms, listening
terms, commercial terms) to estimate each signal. **Crawler values are capped
below the top of each signal's range** — the automated pass can never mint a
"Cornerstone." It produces a low-confidence `unconfirmed` candidate with the
evidence snippets it saw, for a human to verify and adjust. Curation quality
comes from the human gate; the crawler just does the legwork.
