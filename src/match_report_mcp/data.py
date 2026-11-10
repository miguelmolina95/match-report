"""Thin, cached access to StatsBomb Open Data (github.com/statsbomb/open-data).

Reads the raw JSON straight from GitHub so the only dependency is `requests`.
Everything is cached on disk: match events never change once published, and the
match index is refreshed weekly because StatsBomb adds competitions over time.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/"
INDEX_MAX_AGE = 7 * 24 * 3600

CACHE = Path(
    os.environ.get("MATCH_REPORT_CACHE")
    or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "match-report"
)


def _fetch(path: str):
    resp = requests.get(BASE + path, timeout=30)
    resp.raise_for_status()
    return resp.json()


def cached(path: str, max_age: float | None = None):
    """Return the JSON at `path`, from disk if present (and younger than max_age)."""
    target = CACHE / path
    if target.exists() and (max_age is None or time.time() - target.stat().st_mtime < max_age):
        return json.loads(target.read_text())
    data = _fetch(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data))
    return data


def fold(text: str) -> str:
    """Lowercase and strip accents so 'Atlético' matches 'atletico'."""
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def competitions(refresh: bool = False) -> list[dict]:
    return cached("competitions.json", 0 if refresh else INDEX_MAX_AGE)


def match_index(refresh: bool = False) -> list[dict]:
    """One flat row per match across every open competition-season."""
    target = CACHE / "index.json"
    if not refresh and target.exists() and time.time() - target.stat().st_mtime < INDEX_MAX_AGE:
        return json.loads(target.read_text())

    comps = competitions(refresh=True)
    print(f"Building match index from {len(comps)} competition-seasons...", file=sys.stderr)

    def load(comp):
        path = f"matches/{comp['competition_id']}/{comp['season_id']}.json"
        try:
            return comp, _fetch(path)
        except requests.RequestException as exc:  # one missing file should not sink the index
            print(f"  skipped {path}: {exc}", file=sys.stderr)
            return comp, []

    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for comp, matches in pool.map(load, comps):
            for m in matches:
                rows.append(
                    {
                        "match_id": m["match_id"],
                        "date": m.get("match_date"),
                        "competition": comp["competition_name"],
                        "season": comp["season_name"],
                        "gender": comp.get("competition_gender"),
                        "stage": (m.get("competition_stage") or {}).get("name"),
                        "home": m["home_team"]["home_team_name"],
                        "away": m["away_team"]["away_team_name"],
                        "home_id": m["home_team"]["home_team_id"],
                        "away_id": m["away_team"]["away_team_id"],
                        "home_score": m.get("home_score"),
                        "away_score": m.get("away_score"),
                        "stadium": (m.get("stadium") or {}).get("name"),
                    }
                )
    rows.sort(key=lambda r: (r["date"] or "", r["match_id"]), reverse=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows))
    return rows


def match_info(match_id: int) -> dict:
    for refresh in (False, True):
        for row in match_index(refresh=refresh):
            if row["match_id"] == match_id:
                return row
    raise LookupError(
        f"Match {match_id} is not in StatsBomb Open Data. Use find_matches to search for a valid match_id."
    )


def events(match_id: int) -> list[dict]:
    return cached(f"events/{match_id}.json")


def lineups(match_id: int) -> list[dict]:
    return cached(f"lineups/{match_id}.json")
