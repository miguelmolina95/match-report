# Free football data sources: what works

Status below was checked on 2026-11-09 with plain HTTP requests (no browser). These sites change their defences often, so treat a row as a starting assumption and re-test before relying on it.

| Source | What it has | Status with a plain request | Notes |
|---|---|---|---|
| StatsBomb Open Data | Full event data (every pass, shot, pressure, with xG) for ~80 competition-seasons | Works | Static JSON on GitHub. Stable, licensed for public use with attribution. This skill uses it. |
| FBref | Season and match tables for hundreds of leagues | 403, Cloudflare challenge | `pandas.read_html(url)` no longer gets through. |
| Sofascore | Shot maps, ratings, live scores via an internal API | 403 from `api.sofascore.com` | Undocumented API, blocks non-browser clients. |
| FotMob | Shot maps, match stats via an internal API | 404 on `matchDetails` without a signed header | Tutorials that fetch that header from a third-party server should not be followed: it means trusting an unknown host for credentials. |
| Understat | Shot-level xG for six leagues | Page loads, but the inline `shotsData` JSON older scrapers parse is gone | Regex-on-HTML scrapers return nothing. |

## Practical guidance

- **Prefer StatsBomb when the match is covered.** It is the only one of these intended for reuse, so it will still work next year.
- **A missing match is a real limit, not a bug to route around.** Recent club seasons are mostly outside the open data. Tell the user; don't quietly switch to a scraper that may return partial or stale numbers.
- **If the user insists on another source**, test it first with one request and show them the result. Respect robots.txt and rate limits, and never work around a bot challenge: a 403 from a challenge page is the site saying no.
- **Don't mix providers in one chart.** xG models differ between StatsBomb, Opta and Understat by enough to change a narrative, and coordinate systems differ too (StatsBomb 120x80, Opta 100x100, others in 0-1 fractions).
- **Maintained libraries** such as `soccerdata`, `ScraperFC` and `kloppy` track these changes better than hand-rolled requests. Check their issue trackers for the current state of a source before writing new scraping code.
