"""Data model + validation for venues and musicians.

Records live on disk as one YAML file per entity (data/venues/*.yaml,
data/musicians/*.yaml). One-file-per-record keeps diffs small and reviewable,
which is what makes community contribution and moderation tractable.

This module intentionally does light-touch validation rather than a heavy
schema framework: it checks the things a reviewer would otherwise have to
check by hand (required fields, controlled vocabularies, signal ranges,
provenance present) and returns human-readable problems.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from . import rubric

# --- Controlled vocabularies ------------------------------------------------
VENUE_STATUS = {"active", "dormant", "closed", "unconfirmed"}

VENUE_TYPE = {
    "dedicated_space",   # room whose purpose is this music (iBeam, The Stone)
    "arts_center",       # broader multidisciplinary center (Crosstown Arts)
    "diy_space",         # DIY / loft / storefront (Red Room, Gallery 1412)
    "gallery",           # gallery that also programs music (Luggage Store)
    "bar_club",          # commercial bar / club that books music (Arthur's)
    "presenter",         # organization that books into rotating rooms (Nameless Sound)
    "festival",          # recurring festival (High Zero)
    "record_store",      # shop that hosts shows (Normals)
    "university",        # university-affiliated space
}

OPERATING_MODEL = {
    "artist_run",        # run by the musicians themselves
    "nonprofit",         # mission-driven 501(c)(3) or equivalent
    "diy_collective",    # volunteer collective / DIY
    "university",        # academic institution
    "municipal",         # city / public
    "commercial",        # for-profit business
}

COUNTRY_ISO = None  # free-form ISO-3166 alpha-2 (US, DE, JP, ...); Phase 2/3 ready


@dataclass
class ValidationResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_date_ish(v: Any) -> bool:
    if isinstance(v, (_dt.date, _dt.datetime)):
        return True
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                _dt.datetime.strptime(v, fmt)
                return True
            except ValueError:
                continue
    return False


def validate_venue(v: dict) -> ValidationResult:
    r = ValidationResult()

    for req in ("id", "name", "status", "type", "location"):
        if not v.get(req):
            r.errors.append(f"missing required field: {req}")

    if v.get("status") and v["status"] not in VENUE_STATUS:
        r.errors.append(f"status '{v['status']}' not in {sorted(VENUE_STATUS)}")
    if v.get("type") and v["type"] not in VENUE_TYPE:
        r.errors.append(f"type '{v['type']}' not in {sorted(VENUE_TYPE)}")
    if v.get("operating_model") and v["operating_model"] not in OPERATING_MODEL:
        r.errors.append(
            f"operating_model '{v['operating_model']}' not in {sorted(OPERATING_MODEL)}"
        )

    loc = v.get("location") or {}
    if isinstance(loc, dict):
        for req in ("city", "country"):
            if not loc.get(req):
                r.errors.append(f"location.{req} is required")
        if "lat" in loc and loc["lat"] is not None:
            if not (-90 <= float(loc["lat"]) <= 90):
                r.errors.append("location.lat out of range")
        if "lon" in loc and loc["lon"] is not None:
            if not (-180 <= float(loc["lon"]) <= 180):
                r.errors.append("location.lon out of range")
        if not loc.get("lat") or not loc.get("lon"):
            r.warnings.append("no geo-coordinates (lat/lon) — needed for map/geo-query")
    else:
        r.errors.append("location must be a mapping")

    # Signals
    signals = v.get("signals") or {}
    if not signals:
        r.warnings.append("no signals recorded — score cannot be explained")
    for key, raw in signals.items():
        if key not in rubric.SIGNAL_KEYS:
            r.warnings.append(f"unknown signal '{key}' (ignored in scoring)")
            continue
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val is None:
            r.warnings.append(f"signal '{key}' has no value")
        elif not (0 <= float(val) <= rubric.MAX_SIGNAL_VALUE):
            r.errors.append(f"signal '{key}' value {val} out of 0-5 range")
        elif isinstance(raw, dict) and not raw.get("evidence"):
            r.warnings.append(f"signal '{key}' has no evidence text")

    # Score consistency (stored score should match computed score)
    computed = rubric.score_from_signals(signals)
    if "score" in v and v["score"] is not None and int(v["score"]) != computed:
        r.warnings.append(
            f"stored score {v['score']} != computed {computed}; run `atlas score --write`"
        )

    # Confidence
    conf = v.get("confidence")
    if conf is None:
        r.warnings.append("no confidence recorded")
    elif not (0 <= float(conf) <= 1):
        r.errors.append("confidence must be between 0 and 1")

    # active_this_year / provenance
    if "active_this_year" not in v:
        r.warnings.append("active_this_year not set")
    prov = v.get("provenance") or {}
    if not prov.get("added_by"):
        r.warnings.append("provenance.added_by missing")
    if prov.get("last_confirmed") and not _is_date_ish(prov["last_confirmed"]):
        r.errors.append("provenance.last_confirmed is not a date")

    return r


def validate_musician(m: dict) -> ValidationResult:
    r = ValidationResult()
    for req in ("id", "name"):
        if not m.get(req):
            r.errors.append(f"missing required field: {req}")
    if "active_this_year" not in m:
        r.warnings.append("active_this_year not set")
    if not m.get("instruments"):
        r.warnings.append("no instruments listed")
    loc = m.get("home_base") or {}
    if not loc.get("city"):
        r.warnings.append("no home_base.city")
    if not m.get("associated_venues"):
        r.warnings.append("no associated_venues — artist is not yet linked to any room")

    for field in ("instruments", "roles", "collectives", "labels", "associated_venues"):
        val = m.get(field)
        if val is not None and not isinstance(val, list):
            r.errors.append(f"{field} must be a list")
        elif isinstance(val, list) and any(not isinstance(x, str) for x in val):
            r.errors.append(f"{field} must contain only strings")

    prov = m.get("provenance") or {}
    if not prov.get("added_by"):
        r.warnings.append("provenance.added_by missing")
    for credit in (prov.get("label_credits") or []):
        if not credit.get("label"):
            r.errors.append("provenance.label_credits entry has no label")
        if not credit.get("releases"):
            r.warnings.append(
                f"label_credits for '{credit.get('label')}' records no release count")
    return r


def enrich_venue(v: dict) -> dict:
    """Return a copy with derived fields (score, tier) filled from signals."""
    out = dict(v)
    signals = out.get("signals") or {}
    out["score"] = rubric.score_from_signals(signals)
    out["tier"] = rubric.tier_for_score(out["score"]).key
    return out
