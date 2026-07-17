"""The weighting rubric: the heart of Avant Atlas.

Every venue is scored 0-100 on how strongly it is *committed* to free jazz,
free improvisation, and avant-garde/experimental music. A high score means the
venue exists (at least in large part) to present this music. A low score means
the music shows up there only incidentally.

The score is NOT a single opaion number. It is the sum of seven weighted
*signals*, each rated on a 0-5 scale by a human (or approximated by the
crawler). Every signal carries evidence and source URLs, so any score is
explainable: you can always ask "why is this venue an 82?" and read the
signals behind it.

This module is the single source of truth for the weights. The prose companion
is docs/RUBRIC.md, which walks through the four calibration anchors by hand.
Keep the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    key: str
    max_points: int
    label: str
    question: str


# --- The seven signals. max_points sum to 100. -----------------------------
SIGNALS = [
    Signal(
        key="dedicated_series",
        max_points=25,
        label="Dedicated series / mission",
        question=(
            "Is there a named, recurring series, festival, or curatorial line "
            "explicitly for free / improvised / experimental music? Or is that "
            "music the venue's stated reason to exist? (5 = the venue IS this "
            "music; 0 = no dedicated programming at all.)"
        ),
    ),
    Signal(
        key="show_frequency",
        max_points=20,
        label="Frequency of relevant shows",
        question=(
            "How often does genuinely free/avant/improvised music happen here? "
            "(5 = multiple such shows every week; 3 = a regular monthly series; "
            "1 = a handful a year; 0 = essentially never.)"
        ),
    ),
    Signal(
        key="artist_roster",
        max_points=20,
        label="Artist roster",
        question=(
            "What share of the booked artists are recognized improvisers / "
            "experimental musicians (touring the creative-music circuit, on "
            "relevant labels)? (5 = almost all; 0 = none.)"
        ),
    ),
    Signal(
        key="self_description",
        max_points=12,
        label="Self-description",
        question=(
            "Does the venue describe itself with words like experimental, "
            "improvised, adventurous, creative music, avant-garde, new music? "
            "(5 = that language is central; 0 = describes itself as a bar / "
            "tourist spot / general-purpose room.)"
        ),
    ),
    Signal(
        key="operating_model",
        max_points=10,
        label="Operating model",
        question=(
            "Is it artist-run / DIY collective / nonprofit built to serve the "
            "music (higher), or a commercial/tourist business that books it "
            "(lower)? (5 = artist-run or mission-driven nonprofit; "
            "0 = commercial/tourist.)"
        ),
    ),
    Signal(
        key="community_reputation",
        max_points=8,
        label="Community reputation",
        question=(
            "Do scene participants, press, wikis, and scene lists name this as "
            "a home for the music? (5 = widely cited as a cornerstone; "
            "0 = never mentioned in that context.)"
        ),
    ),
    Signal(
        key="listening_room",
        max_points=5,
        label="Listening-room intent",
        question=(
            "Is the room programmed as an attentive listening experience "
            "(seated, quiet, music is the point) vs. background music in a bar? "
            "(5 = pure listening room; 0 = background music while people drink/"
            "talk.)"
        ),
    ),
]

SIGNAL_KEYS = [s.key for s in SIGNALS]
SIGNALS_BY_KEY = {s.key: s for s in SIGNALS}
MAX_SIGNAL_VALUE = 5

assert sum(s.max_points for s in SIGNALS) == 100, "Signal weights must total 100"


# --- Tiers ------------------------------------------------------------------
@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    low: int
    high: int
    blurb: str


TIERS = [
    Tier("cornerstone", "Cornerstone", 85, 100,
         "Exists to present this music. A pilgrimage venue."),
    Tier("committed", "Committed", 65, 84,
         "A real, regular home for the music; strong dedicated programming."),
    Tier("supportive", "Supportive", 45, 64,
         "Books it meaningfully, but as part of a broader program."),
    Tier("occasional", "Occasional", 25, 44,
         "The music appears here now and then; not a scene anchor."),
    Tier("incidental", "Incidental", 0, 24,
         "Mostly other music; free/avant is rare or accidental."),
]


def score_from_signals(signals: dict) -> int:
    """Compute the 0-100 score from a signals dict.

    `signals` maps signal key -> value (0-5) OR -> a dict with a "value" field.
    Missing signals count as 0. Unknown keys are ignored.
    """
    total = 0.0
    for sig in SIGNALS:
        raw = signals.get(sig.key)
        if isinstance(raw, dict):
            raw = raw.get("value")
        if raw is None:
            continue
        value = max(0, min(MAX_SIGNAL_VALUE, float(raw)))
        total += (value / MAX_SIGNAL_VALUE) * sig.max_points
    return round(total)


def tier_for_score(score: int) -> Tier:
    for t in TIERS:
        if t.low <= score <= t.high:
            return t
    return TIERS[-1]


def explain(signals: dict) -> list:
    """Return a per-signal breakdown for display: (label, value, points)."""
    rows = []
    for sig in SIGNALS:
        raw = signals.get(sig.key)
        evidence = ""
        if isinstance(raw, dict):
            evidence = raw.get("evidence", "")
            raw = raw.get("value")
        value = 0 if raw is None else max(0, min(MAX_SIGNAL_VALUE, float(raw)))
        points = round((value / MAX_SIGNAL_VALUE) * sig.max_points, 1)
        rows.append({
            "key": sig.key,
            "label": sig.label,
            "value": value,
            "max_value": MAX_SIGNAL_VALUE,
            "points": points,
            "max_points": sig.max_points,
            "evidence": evidence,
        })
    return rows
