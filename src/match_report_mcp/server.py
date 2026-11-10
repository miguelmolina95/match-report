"""MCP server: football match reports from StatsBomb Open Data.

Runs locally over stdio. All tools are read-only against public data; the only
thing written to disk is a cache of downloaded JSON and the rendered PNGs.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Annotated

from pydantic import Field

import requests

try:  # mcp 2.x
    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x, where the same class was called FastMCP
    from mcp.server.fastmcp import FastMCP as MCPServer
    from mcp.server.fastmcp import Image
    from mcp.server.fastmcp.exceptions import ToolError

from . import data, report

INSTRUCTIONS = """\
Football (soccer) match analysis from StatsBomb Open Data: a free, curated sample of
about 4,000 matches (World Cups, Euros, Copa America, much of Messi's La Liga career,
single seasons of a few leagues, a lot of women's football). It is not a live feed and
most recent club matches are absent; when a match is missing, say so rather than
substituting another one.

Typical flow: find_matches -> match_report (image) or match_summary (numbers only).
Quote figures from the tool output, not from memory. xG measures shot quality, not a
deserved score; check np_xg before calling a side dominant, since each penalty is worth
about 0.78 xG. Published graphics must credit StatsBomb.
"""

server = MCPServer("match-report", instructions=INSTRUCTIONS)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _index() -> list[dict]:
    try:
        return data.match_index()
    except requests.RequestException as exc:
        raise ToolError(f"Could not download the StatsBomb match index from GitHub: {exc}") from exc


def _analyse(match_id: int) -> dict:
    # ToolError is the only exception whose message reaches the model, so the two
    # failures a caller can act on (wrong id, no network) are translated into it.
    try:
        return report.analyse(match_id)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
    except requests.RequestException as exc:
        raise ToolError(f"Could not download match {match_id} from StatsBomb Open Data on GitHub: {exc}") from exc


def _words(query: str) -> list[str]:
    return data.fold(query).split()


@server.tool()
def list_competitions(
    query: Annotated[str, Field(description="Optional filter words, e.g. 'women' or 'la liga 2015'")] = "",
) -> dict:
    """List the competition-seasons that have free event data, with match counts.

    Use this to answer "what can I look at?" or to explain why a match was not found.
    """
    words = _words(query)
    counts = Counter((r["competition"], r["season"], r["gender"]) for r in _index())
    rows = [
        {"competition": c, "season": s, "gender": g, "matches": n}
        for (c, s, g), n in counts.items()
        if all(w in data.fold(f"{c} {s} {g}") for w in words)
    ]
    rows.sort(key=lambda r: (r["competition"], r["season"]))
    return {"total_matches": sum(r["matches"] for r in rows), "competitions": rows}


@server.tool()
def find_matches(
    query: Annotated[str, Field(description="Words that must all match: team names, year, competition, stage. E.g. 'argentina france 2022 final'")],
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum matches to return")] = 20,
) -> dict:
    """Search for matches and get their match_id, teams, score, date and competition.

    Matching ignores case and accents. Team names are StatsBomb's ("Bayern Munich",
    "Spain Women's"). If several matches fit and the user's wording does not pick one,
    show the candidates and ask instead of guessing.
    """
    words = _words(query)

    def haystack(r):
        return data.fold(f"{r['home']} {r['away']} {r['competition']} {r['season']} {r['stage']} {r['date']} {r['gender']}")

    hits = [r for r in _index() if all(w in haystack(r) for w in words)]
    keep = ("match_id", "date", "home", "away", "home_score", "away_score", "competition", "season", "stage")
    return {"total_found": len(hits), "matches": [{k: r[k] for k in keep} for r in hits[:limit]]}


@server.tool()
def match_summary(
    match_id: Annotated[int, Field(description="StatsBomb match id from find_matches")],
) -> dict:
    """Headline numbers for one match: score, scorers with minutes, xG, shots, passing.

    Extra time is included; penalty shootouts are reported separately and excluded from
    goals, shots and xG. `score_matches_listing` is false if goals counted from events
    disagree with the official result, which should be mentioned to the user.
    """
    return report.summarise(_analyse(match_id))


@server.tool()
def match_shots(
    match_id: Annotated[int, Field(description="StatsBomb match id from find_matches")],
) -> dict:
    """Every shot in a match in order: player, minute, xG, outcome, type and location.

    Coordinates are StatsBomb's: x 0-120 towards the goal being attacked, y 0-80 across,
    so both teams' shots sit near x = 120. Shootout kicks are excluded.
    """
    return {"shots": report.shot_list(_analyse(match_id))}


@server.tool()
def match_report(
    match_id: Annotated[int, Field(description="StatsBomb match id from find_matches")],
    home_color: Annotated[str, Field(description="Hex colour for the home team, e.g. '#6CACE4'")] = report.DEFAULT_HOME,
    away_color: Annotated[str, Field(description="Hex colour for the away team, e.g. '#1D2A5B'")] = report.DEFAULT_AWAY,
) -> list:
    """Render a one-page match report image and return it with the numbers behind it.

    The image shows both passing networks, both shot maps, an xG race with goal markers
    and a stats comparison. The data has no kit colours, so pass each team's recognisable
    colour; the two must differ clearly and both must show on an off-white background
    (for a team in white, use its secondary colour). Each passing network covers one
    settled XI, from kick-off to that team's first substitution after half-time.

    Returns the PNG, the summary, and the path of a full-resolution copy on disk.
    """
    for label, value in (("home_color", home_color), ("away_color", away_color)):
        if not HEX.match(value):
            raise ToolError(f"{label} must be a hex colour like '#1D2A5B', got {value!r}")
    m = _analyse(match_id)
    colors = {"home": home_color, "away": away_color}
    out_dir = data.CACHE / "reports"
    full = out_dir / f"{report.slug(m)}.png"
    preview = out_dir / f"{report.slug(m)}-preview.png"
    report.render(m, colors, full, dpi=160)
    # Inline tool results have tight size limits in most clients, so a lighter copy
    # goes over the wire and the print-quality file stays on disk.
    report.render(m, colors, preview, dpi=90)
    summary = report.summarise(m)
    summary["full_resolution_png"] = str(full)
    return [Image(path=str(preview)), summary]


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
