"""Command-line interface for Avant Atlas.

    atlas validate                 check every record against the schema
    atlas score [--write]          recompute scores from signals (optionally save)
    atlas build                    generate site/ + DIRECTORY.md
    atlas list [filters]           browse the directory in the terminal
    atlas show <venue-id>          full explainable score breakdown for one venue
    atlas stats                    corpus size + geographic spread
    atlas crawl <url> [opts]       fetch a source -> candidate venue record
    atlas recrawl [--id X]         re-fetch sources, detect changed/closed
    atlas linkcheck [--write]      is every cited URL still reachable?
    atlas verify [--limit N]       ranked queue: what to verify next, and why
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
    result = build_mod.build_all(base_url=args.base_url, single_page=args.single_page)
    print(f"Built {result['pages']} pages for {result['base']}")
    print(f"  {result['venues']} venue pages")
    print(f"  {result['cities']} city pages, {result['regions']} US state pages, "
          f"{result['countries']} country pages")
    print(f"  {result['musicians']} artist pages")
    print(f"  {result['outdir']}/index.html · directory.json · sitemap.xml · robots.txt")
    if result.get("single_page"):
        print(f"  {result['single_page']} (offline all-in-one)")
    print("  DIRECTORY.md")
    return 0


def cmd_linkcheck(args) -> int:
    """Check every cited website. This is the cheapest honesty mechanism we have."""
    from . import linkcheck

    venues = storage.load_venues()
    targets = [v for v in venues if not args.id or v.get("id") == args.id]
    urls = [v.get("website") for v in targets if v.get("website")]
    print(f"Checking {len(urls)} websites with {args.workers} workers...\n")
    results = linkcheck.check_many(urls, workers=args.workers, timeout=args.timeout)

    color = {linkcheck.OK: "32", linkcheck.BLOCKED: "90", linkcheck.ERROR: "33",
             linkcheck.DEAD: "31", linkcheck.UNREACHABLE: "31",
             linkcheck.SKIPPED: "90"}
    tally, changed = {}, 0
    for v in targets:
        url = v.get("website")
        res = results.get(url) or linkcheck.LinkResult(url="", status=linkcheck.SKIPPED)
        tally[res.status] = tally.get(res.status, 0) + 1
        if res.status != linkcheck.OK or args.all:
            label = _c(f"{res.status.upper():12s}", color.get(res.status, "0"))
            print(f"{label} {v.get('id', ''):38.38s} "
                  f"{res.detail or res.final_url or url}")
        if args.write:
            linkcheck.record_on_venue(v, res)
            storage.save_venue(v)
            changed += 1

    print("\n" + "  ".join(f"{k}={n}" for k, n in sorted(tally.items(), key=lambda x: -x[1])))
    attention = tally.get(linkcheck.DEAD, 0) + tally.get(linkcheck.UNREACHABLE, 0) \
        + tally.get(linkcheck.ERROR, 0)
    print(f"{attention} venue(s) need attention.")
    if args.write:
        print(f"Recorded link health on {changed} record(s).")
    else:
        print("(dry run — pass --write to record link health in provenance)")
    return 0


def cmd_verify(args) -> int:
    """Rank the corpus by where human attention would change the most.

    Verification effort is the scarcest resource in a curated directory, so
    spend it where a wrong number does the most damage: high-scoring venues we
    are least sure about, with the least evidence, checked the longest ago.
    """
    import datetime as dt

    venues = [enrich_venue(v) for v in storage.load_venues()]
    today = dt.date.today()

    def staleness_days(v) -> int:
        prov = v.get("provenance") or {}
        best = None
        for key in ("last_confirmed", "added_on"):
            raw = prov.get(key)
            if not raw:
                continue
            s = str(raw)
            for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
                try:
                    d = dt.datetime.strptime(s, fmt).date()
                    best = d if best is None or d > best else best
                    break
                except ValueError:
                    continue
        return (today - best).days if best else 3650

    rows = []
    for v in venues:
        prov = v.get("provenance") or {}
        conf = v.get("confidence")
        conf = 0.5 if not isinstance(conf, (int, float)) else float(conf)
        sigs = v.get("signals") or {}
        missing_ev = sum(1 for s in sigs.values()
                         if isinstance(s, dict) and not s.get("evidence"))
        n_sources = len(prov.get("source_urls") or [])
        link = (prov.get("link_check") or {}).get("status")

        # Impact: a wrong cornerstone misleads far more people than a wrong
        # occasional room, and uncertainty is what verification actually buys.
        impact = (v.get("score", 0) / 100) ** 1.5
        doubt = (1 - conf)
        thin = min(1.0, (missing_ev * 0.15) + (0.4 if n_sources == 0 else 0.0)
                   + (0.2 if n_sources == 1 else 0.0))
        stale = min(1.0, staleness_days(v) / 365)
        broken = 0.6 if link in ("dead", "unreachable") else (0.2 if link == "error" else 0.0)
        flagged = 0.25 if prov.get("needs_human_review") else 0.0

        priority = impact * (doubt + thin + flagged + broken) + 0.25 * stale * impact
        reasons = []
        if conf <= 0.55:
            reasons.append(f"low confidence {conf:g}")
        if n_sources == 0:
            reasons.append("NO sources")
        elif n_sources == 1:
            reasons.append("single source")
        if missing_ev:
            reasons.append(f"{missing_ev} signal(s) lack evidence")
        if link in ("dead", "unreachable", "error"):
            reasons.append(f"website {link}")
        if prov.get("needs_human_review"):
            reasons.append("flagged for review")
        if staleness_days(v) > 300:
            reasons.append(f"unconfirmed {staleness_days(v)}d")
        rows.append((priority, v, reasons))

    rows.sort(key=lambda r: -r[0])
    shown = rows[: args.limit]
    print(f"Verification queue — top {len(shown)} of {len(rows)} venues, "
          f"ranked by (score impact × uncertainty).\n")
    for pri, v, reasons in shown:
        loc = v.get("location") or {}
        print(f"{_c(f'{pri:5.2f}', '36')} {_c(str(v.get('score')).rjust(3), '1')} "
              f"{v.get('name', ''):34.34s} {loc.get('city', ''):16.16s} "
              f"{(loc.get('region') or loc.get('country') or ''):6.6s}")
        if reasons:
            print(f"        {_c('; '.join(reasons), '90')}")
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
    import concurrent.futures

    from . import crawl
    venues = storage.load_venues()
    targets = [v for v in venues if not args.id or v.get("id") == args.id]
    if not targets:
        print(f"No venue matched id={args.id}")
        return 1

    # Fail fast if the crawler cannot run at all, rather than recording 263
    # false "gone" verdicts caused by a missing library on this machine.
    try:
        crawl.fetch("https://example.com", timeout=10)
    except crawl.CrawlerUnavailable as exc:
        print(_c(f"cannot re-crawl: {exc}", "31"))
        return 2
    except Exception:
        pass  # example.com being unreachable is not our problem here

    # Re-crawling 250+ sites one at a time takes long enough that nobody does
    # it, which defeats the purpose. Fetches are I/O bound and independent.
    def one(v):
        try:
            return v, crawl.recrawl(v)
        except crawl.CrawlerUnavailable:
            raise
        except Exception as exc:  # never let one bad host kill the sweep
            return v, crawl.RecrawlResult(url=v.get("website") or "", outcome="gone",
                                          notes=f"{type(exc).__name__}: {str(exc)[:120]}")

    tally = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for v, res in ex.map(one, targets):
            tally[res.outcome] = tally.get(res.outcome, 0) + 1
            mark = {"unchanged": "90", "changed": "33", "new": "36",
                    "gone": "31"}.get(res.outcome, "0")
            if res.outcome != "unchanged" or args.all:
                print(f"{_c(f'{res.outcome.upper():9s}', mark)} {v.get('id',''):40.40s} {res.notes}")
            if args.write and res.outcome in ("changed", "gone", "new"):
                storage.save_venue(v)
    print("\n" + "  ".join(f"{k}={n}" for k, n in sorted(tally.items(), key=lambda x: -x[1])))
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

    sp = sub.add_parser("build", help="generate the static site + DIRECTORY.md")
    sp.add_argument("--base-url", help="public origin for canonical URLs/sitemap "
                                      "(default: $ATLAS_BASE_URL)")
    sp.add_argument("--single-page", action="store_true",
                    help="also emit the offline all-in-one.html artifact")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("linkcheck", help="check that every cited website still resolves")
    sp.add_argument("--id", help="only this venue id")
    sp.add_argument("--write", action="store_true", help="record results in provenance")
    sp.add_argument("--all", action="store_true", help="list healthy links too")
    sp.add_argument("--workers", type=int, default=16)
    sp.add_argument("--timeout", type=int, default=15)
    sp.set_defaults(func=cmd_linkcheck)

    sp = sub.add_parser("verify", help="ranked queue of what to verify next")
    sp.add_argument("--limit", type=int, default=25)
    sp.set_defaults(func=cmd_verify)

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
    sp.add_argument("--all", action="store_true", help="list unchanged sources too")
    sp.add_argument("--workers", type=int, default=12)
    sp.set_defaults(func=cmd_recrawl)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
