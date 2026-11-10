#!/usr/bin/env python3
"""Search StatsBomb Open Data for a match, or list what competitions exist.

    find_match.py argentina france 2022          # every word must match
    find_match.py barcelona "champions league"
    find_match.py --competitions                 # what is available at all
    find_match.py --competitions women

Words are matched (accent- and case-insensitively) against the team names,
competition, season, stage and date, so years, rounds and partial names all work.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

import sbdata


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("terms", nargs="*", help="words that must all appear in the match description")
    ap.add_argument("--competitions", action="store_true", help="list competition-seasons instead of matches")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--refresh", action="store_true", help="rebuild the cached index")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    rows = sbdata.match_index(refresh=args.refresh)
    words = [sbdata.fold(w) for term in args.terms for w in term.split()]

    if args.competitions:
        counts = Counter((r["competition"], r["season"], r["gender"]) for r in rows)
        items = [
            {"competition": c, "season": s, "gender": g, "matches": n}
            for (c, s, g), n in counts.items()
            if all(w in sbdata.fold(f"{c} {s} {g}") for w in words)
        ]
        items.sort(key=lambda i: (i["competition"], i["season"]))
        if args.json:
            print(json.dumps(items, indent=1))
            return
        for i in items:
            print(f"{i['competition']:<28} {i['season']:<10} {i['gender']:<7} {i['matches']:>4} matches")
        print(f"\n{len(items)} competition-seasons, {sum(i['matches'] for i in items)} matches")
        return

    def haystack(r):
        return sbdata.fold(
            f"{r['home']} {r['away']} {r['competition']} {r['season']} {r['stage']} {r['date']} {r['gender']}"
        )

    hits = [r for r in rows if all(w in haystack(r) for w in words)]
    shown = hits[: args.limit]
    if args.json:
        print(json.dumps(shown, indent=1))
        return
    if not hits:
        print("No matches found. StatsBomb Open Data only covers selected competitions;")
        print("run with --competitions to see what exists, or try fewer / different words.")
        return
    for r in shown:
        print(
            f"{r['match_id']:>8}  {r['date']}  {r['home']} {r['home_score']}-{r['away_score']} {r['away']}"
            f"  |  {r['competition']} {r['season']}, {r['stage']}"
        )
    if len(hits) > len(shown):
        print(f"... {len(hits) - len(shown)} more; add words (year, opponent, stage) to narrow it down")


if __name__ == "__main__":
    main()
