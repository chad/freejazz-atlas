"""Command-line interface for Avant Atlas.

    atlas validate                 check every record against the schema
    atlas score [--write]          recompute scores from signals (optionally save)
    atlas build                    generate site/ + DIRECTORY.md
    atlas list [filters]           browse the directory in the terminal
    atlas show <venue-id>          full explainable score breakdown for one venue
    atlas stats                    corpus size + geographic spread
    atlas crawl <url> [opts]       fetch a source -> candidate venue record
    atlas recrawl [--id X]         re-fetch sources, detect changed/closed
"""

from __future__ import annotations

import argparse
import sys

from . import build as build_mod
from . import rubric, storage
from .model import enrich_venue, validate_musician, validate_venue


def _c(s, code):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def cmd_validate(args) -> int:
    venues = storage.load_venues()
    musicians = storage.load_musicians()
    errors = warnings = 0
    ids = set()
    for v in venues:
        vid = v.get("id")
        if vid in ids:
            print(_c(f"ERROR duplicate venue id: {vid}", "31"))
            errors += 1
        ids.add(vid)
        r = validate_venue(v)
        for e in r.errors:
            print(_c(f"ERROR [{vid}] {e}", "31")); errors += 1
        if args.strict:
            for w in r.warnings:
                print(_c(f"warn  [{vid}] {w}", "33")); warnings += 1
    for m in musicians:
        r = validate_musician(m)
        for e in r.errors:
            print(_c(f"ERROR [{m.get('id')}] {e}", "31")); errors += 1
        if args.strict:
            for w in r.warnings:
                print(_c(f"warn  [{m.get('id')}] {w}", "33")); warnings += 1
    print(f"\n{len(venues)} venues, {len(musicians)} musicians checked. "
          f"{errors} errors, {warnings} warnings.")
    return 1 if errors else 0


def cmd_score(args) -> int:
    venues = storage.load_venues()
    changed = 0
    for v in venues:
        computed = rubric.score_from_signals(v.get("signals") or {})
        old = v.get("score")
        if old != computed:
            changed += 1
            print(f"{v.get('id'):32s} {str(old):>4} -> {computed:>3} "
                  f"({rubric.tier_for_score(computed).label})")
            if args.write:
                v["score"] = computed
                v["tier"] = rubric.tier_for_score(computed).key
                storage.save_venue(v)
    if changed == 0:
        print("All stored scores already match computed scores.")
    elif args.write:
        print(f"\nUpdated {changed} record(s).")
    else:
        print(f"\n{changed} record(s) differ. Re-run with --write to save.")
    return 0


def cmd_build(args) -> int:
    result = build_mod.build_all()
    print(f"Built directory: {result['venues']} venues, {result['musicians']} musicians")
    print(f"  {result['outdir']}/index.html")
    print(f"  {result['outdir']}/directory.json")
    print(f"  DIRECTORY.md")
    return 0


def cmd_list(args) -> int:
    venues = [enrich_venue(v) for v in storage.load_venues()]
    venues.sort(key=lambda v: (-v.get("score", 0), v.get("name", "")))
    for v in venues:
        loc = v.get("location") or {}
        if args.state and (loc.get("region") or "").upper() != args.state.upper():
            continue
        if args.tier and v.get("tier") != args.tier:
            continue
        if args.min and v.get("score", 0) < args.min:
            continue
        tier = rubric.tier_for_score(v["score"])
        score_cell = _c(f"{v['score']:>3}", "36")
        print(f"{score_cell} {tier.label:12s} {v.get('name',''):34.34s} "
              f"{loc.get('city',''):16.16s} {loc.get('region',''):3s}")
    return 0


def cmd_show(args) -> int:
    venues = {v.get("id"): v for v in storage.load_venues()}
    v = venues.get(args.venue_id)
    if not v:
        print(f"No venue with id '{args.venue_id}'.")
        return 1
    v = enrich_venue(v)
    loc = v.get("location") or {}
    print(_c(v.get("name", ""), "1"))
    print(f"{loc.get('city','')}, {loc.get('region','')}, {loc.get('country','')} "
          f"· {v.get('type','')} · {v.get('operating_model','')}")
    if v.get("website"):
        print(v["website"])
    print(f"\nSCORE {_c(v['score'], '36')} / 100  "
          f"({rubric.tier_for_score(v['score']).label})  "
          f"confidence {v.get('confidence','?')}  "
          f"active_this_year={v.get('active_this_year')}")
    print("\nSignals:")
    for row in rubric.explain(v.get("signals") or {}):
        bar = "█" * int(row["value"]) + "·" * (row["max_value"] - int(row["value"]))
        print(f"  {row['label']:26s} [{bar}] {row['value']}/5  "
              f"= {row['points']:>4}/{row['max_points']}")
        if row["evidence"]:
            print(f"      {_c(row['evidence'], '90')}")
    prov = v.get("provenance") or {}
    print(f"\nProvenance: added_by={prov.get('added_by','?')} "
          f"last_confirmed={prov.get('last_confirmed','?')}")
    for u in prov.get("source_urls", []):
        print(f"  source: {u}")
    return 0


def cmd_stats(args) -> int:
    venues = [enrich_venue(v) for v in storage.load_venues()]
    musicians = storage.load_musicians()
    states, countries, tiers = {}, {}, {}
    for v in venues:
        loc = v.get("location") or {}
        states[loc.get("region", "?")] = states.get(loc.get("region", "?"), 0) + 1
        countries[loc.get("country", "?")] = countries.get(loc.get("country", "?"), 0) + 1
        tiers[v.get("tier", "?")] = tiers.get(v.get("tier", "?"), 0) + 1
    print(f"{len(venues)} venues, {len(musicians)} musicians")
    print(f"\nStates/regions ({len(states)}):")
    for s, n in sorted(states.items(), key=lambda x: -x[1]):
        print(f"  {s or '?':4s} {n}")
    print(f"\nCountries: " + ", ".join(f"{c}={n}" for c, n in sorted(countries.items())))
    print("Tiers:")
    for t in rubric.TIERS:
        print(f"  {t.label:12s} {tiers.get(t.key, 0)}")
    return 0


def cmd_crawl(args) -> int:
    from . import crawl
    from .storage import dump_record
    f = crawl.fetch(args.url)
    print(f"# fetched {f.url}  (HTTP {f.status}, hash {f.content_hash})", file=sys.stderr)
    cand = crawl.candidate_from_fetch(f, city=args.city or "", region=args.region or "")
    text = dump_record(cand)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote candidate to {args.out}", file=sys.stderr)
        print(f"Score {cand['score']} ({cand['tier']}), confidence {cand['confidence']}. "
              f"REVIEW BEFORE MERGING.", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_recrawl(args) -> int:
    from . import crawl
    venues = storage.load_venues()
    targets = [v for v in venues if not args.id or v.get("id") == args.id]
    if not targets:
        print(f"No venue matched id={args.id}")
        return 1
    for v in targets:
        res = crawl.recrawl(v)
        mark = {"unchanged": "90", "changed": "33", "new": "36", "gone": "31"}.get(res.outcome, "0")
        label = _c(f"{res.outcome.upper():9s}", mark)
        print(f"{label} {v.get('id','')}  {res.notes}")
        if args.write and res.outcome in ("changed", "gone", "new"):
            storage.save_venue(v)
    if args.write:
        print("\nProvenance updated on disk.")
    else:
        print("\n(dry run — pass --write to persist provenance updates)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="atlas", description="Avant Atlas toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate", help="check records against the schema")
    sp.add_argument("--strict", action="store_true", help="also show warnings")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("score", help="recompute scores from signals")
    sp.add_argument("--write", action="store_true", help="save recomputed scores")
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser("build", help="generate site/ and DIRECTORY.md")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("list", help="browse the directory in the terminal")
    sp.add_argument("--state", help="filter by state/region code, e.g. IL")
    sp.add_argument("--tier", help="filter by tier key")
    sp.add_argument("--min", type=int, help="minimum score")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="explainable breakdown for one venue")
    sp.add_argument("venue_id")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("stats", help="corpus size + geographic spread")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("crawl", help="fetch a source -> candidate venue record")
    sp.add_argument("url")
    sp.add_argument("--city")
    sp.add_argument("--region")
    sp.add_argument("--out", help="write YAML candidate here (else stdout)")
    sp.set_defaults(func=cmd_crawl)

    sp = sub.add_parser("recrawl", help="re-fetch sources, detect changed/closed")
    sp.add_argument("--id", help="only this venue id")
    sp.add_argument("--write", action="store_true", help="persist provenance updates")
    sp.set_defaults(func=cmd_recrawl)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
