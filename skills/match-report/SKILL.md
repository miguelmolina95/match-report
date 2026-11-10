---
name: match-report
description: Build a one-page football (soccer) match report image - passing networks, shot maps, xG race chart and headline stats - from free StatsBomb event data, and find matches in that data. Use this whenever someone asks for a match report, match dashboard, post-match graphic, xG chart, shot map or pass network for a specific game ("show me the 2022 World Cup final", "make a dashboard for Leverkusen v Bayern", "what did the xG look like in that Euro 2024 semi"), asks what matches or competitions have free event data, or wants to analyse a single match visually - even if they never say "StatsBomb" or "report".
---

# Match report

Turns "Argentina v France, 2022 final" into a finished PNG: both passing networks, both shot maps, an xG race with goal markers, and a stats comparison. Two scripts do the work so the numbers are computed the same way every time; your job is to find the right match, choose colours, run them, and tell the user what the picture shows.

Scripts live in `scripts/` next to this file (`${CLAUDE_SKILL_DIR}/scripts`). They need `requests`, `matplotlib` and `mplsoccer` (`pip install requests matplotlib mplsoccer`). Data is cached under `~/.cache/match-report`, so only the first run is slow.

## Workflow

**1. Find the match.**

```bash
python3 scripts/find_match.py argentina france 2022
```

Every word must match something in the team names, competition, season, stage or date, so add a year, opponent or round to narrow a long list. Names are StatsBomb's ("Bayern Munich", "Spain Women's"), matched without accents or case.

If several matches fit and the user's wording doesn't settle it, show the candidates and ask. Guessing between two legs of a tie gives a confident report on the wrong game.

**2. Check it's covered.** StatsBomb Open Data is a curated free sample, not a live feed: roughly 80 competition-seasons and about 4,000 matches (World Cups, Euros, Copa América, most of Messi's La Liga career, one full season of a few leagues, a lot of women's football). Most recent club matches are *not* in it. When a match is missing, say so plainly and offer what is close (`find_match.py --competitions` lists everything). Don't substitute a different match without saying so, and don't fall back to scraping another site to fill the gap; see `references/sources.md` for why that is unreliable.

**3. Pick colours.** The data has no kit colours, so pass them:

```bash
python3 scripts/match_report.py 3869685 --home-color "#6CACE4" --away-color "#1D2A5B"
```

Use each team's recognisable colour, with two constraints that matter more than accuracy: the two must be clearly different from each other, and each must be visible on an off-white background. So for a team that plays in white or pale yellow, use its secondary colour (England navy, Real Madrid's dark trim). If two teams share a colour, give the away side its change kit. Without flags the script falls back to a neutral blue and red.

`--out path.png` sets the destination; by default the file lands in the current directory.

**4. Look at it, then report.** Open the PNG yourself before presenting it; a clash of colours or a network squashed by an odd lineup is easier to catch by eye than to predict. Then show the user the image and add a few sentences on what it says. The script prints a JSON summary (score, scorers and minutes, xG, shots, passing, the window each network covers); quote numbers from that rather than reading them off the image or recalling them from memory.

## Reading the report honestly

These are the points people most often get wrong when describing these charts:

- **xG is shot quality, not a "deserved" score.** Say "Germany created 2.13 xG from 13 shots", not "should have scored 2". Penalties are worth about 0.78 xG each, so check `np_xg` before calling a side dominant; a team with 2.3 xG and two penalties did not create much from open play.
- **Own goals count on the scoreboard but carry no xG.** They appear on the xG race tagged "(og)" on the benefiting team's line.
- **Shootouts are excluded** from goals, shots and xG, and shown as "4–2 on penalties" in the header. Extra time is included.
- **Each passing network covers one settled XI**: kick-off until that team's first substitution after half-time. The panel title states the minute. It describes how the side set up, not the whole match, so don't use it to explain something that happened after the window closed. A first-half injury replacement is swapped in rather than ending the window.
- **Node position is the average location of a player's passes and receptions**, and both teams are drawn attacking upwards. A full-back who looks "high" may simply have seen most of the ball in the opposition half.
- **Minutes are football minutes** ("23'" is the 23rd minute, "45+2'" is stoppage time).

`score_matches_listing` in the summary confirms that goals counted from events equal the official result. If it is ever false, tell the user rather than presenting the report as correct.

## Beyond the standard report

For a different view of the same match (one player's passes, a heatmap, pressures), reuse `scripts/sbdata.py`, which returns the raw event list for a match id, and draw with `mplsoccer`. StatsBomb coordinates run 0–120 along the pitch and 0–80 across, always in the direction that team is attacking, so a team's shots sit near x = 120 in both halves with no flipping needed.

If the user wants data from another provider, or asks why a scraper stopped working, read `references/sources.md`.

## Attribution

StatsBomb's open-data licence asks that published work credits them. The image carries a "Data: StatsBomb Open Data" footer; keep it, and if the user is posting the graphic publicly mention that StatsBomb also ask for their logo to be shown.
