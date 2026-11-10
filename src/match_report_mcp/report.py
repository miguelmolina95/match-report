"""Analyse a StatsBomb Open Data match and render it as a one-page report.

Panels: passing networks, headline stats, shot maps and an xG race chart.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from mplsoccer import VerticalPitch  # noqa: E402

from . import data as sbdata  # noqa: E402

BG = "#fbfaf7"
INK = "#1c1c1c"
MUTED = "#77736c"
LINE = "#c9c5bc"
DEFAULT_HOME = "#1f5fbf"
DEFAULT_AWAY = "#d1495b"

# Nominal kick-off minute of each period. StatsBomb's `minute` keeps counting
# through stoppage time, so 45+3 and the 48th minute of the second half share
# minute 47; a continuous clock has to be rebuilt per period.
PERIOD_START = {1: 0, 2: 45, 3: 90, 4: 105}
ON_TARGET = {"Goal", "Saved", "Saved to Post", "Saved To Post"}
NOT_AN_ATTEMPT = {"Unknown", "Injury Clearance"}
PARTICLES = {"di", "de", "da", "do", "dos", "van", "der", "den", "la", "le", "el", "al", "del", "von", "ten", "ter", "mac", "st."}


# ---------------------------------------------------------------- helpers

def etype(e):
    return e["type"]["name"]


def clock(e) -> float:
    return e["minute"] + e["second"] / 60


def minute_label(e) -> str:
    """Football-style minute: 0-based data minute 22 is 'the 23rd minute'."""
    start = PERIOD_START.get(e["period"], 0)
    cap = {1: 45, 2: 90, 3: 105, 4: 120}.get(e["period"], 120)
    shown = e["minute"] + 1
    return f"{cap}+{shown - cap}'" if shown > cap and e["minute"] >= start else f"{shown}'"


def short_name(name: str) -> str:
    parts = name.split()
    if len(parts) <= 1:
        return name
    keep = [parts[-1]]
    for p in reversed(parts[:-1]):
        if p.lower() in PARTICLES:
            keep.insert(0, p)
        else:
            break
    return " ".join(keep)


def text_on(color: str) -> str:
    r, g, b = to_rgb(color)
    return INK if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else "white"


# ---------------------------------------------------------------- analysis

def analyse(match_id: int) -> dict:
    info = sbdata.match_info(match_id)
    all_events = sorted(sbdata.events(match_id), key=lambda e: e["index"])
    # Period 5 is the penalty shootout: its kicks are not shots in open play and
    # would inflate goals, shots and xG if they were left in.
    events = [e for e in all_events if e["period"] <= 4]
    shootout = [e for e in all_events if e["period"] == 5 and etype(e) == "Shot"]

    names = {}
    numbers = {}
    for side in sbdata.lineups(match_id):
        for p in side["lineup"]:
            names[p["player_id"]] = p.get("player_nickname") or p["player_name"]
            numbers[p["player_id"]] = p.get("jersey_number")

    # Continuous match clock.
    lengths = {}
    for p in sorted({e["period"] for e in events}):
        lengths[p] = max(clock(e) for e in events if e["period"] == p) - PERIOD_START[p]
    offsets, total = {}, 0.0
    for p in sorted(lengths):
        offsets[p] = total
        total += lengths[p]

    def t(e):
        return offsets[e["period"]] + clock(e) - PERIOD_START[e["period"]]

    teams = {}
    for key in ("home", "away"):
        tid = info[f"{key}_id"]
        mine = [e for e in events if e["team"]["id"] == tid]
        shots = [e for e in mine if etype(e) == "Shot"]
        passes = [e for e in mine if etype(e) == "Pass" and e["pass"].get("outcome", {}).get("name") not in NOT_AN_ATTEMPT]
        completed = [e for e in passes if "outcome" not in e["pass"]]

        goals = []
        for e in shots:
            if e["shot"]["outcome"]["name"] == "Goal":
                goals.append({"t": t(e), "minute": minute_label(e), "scorer": names.get(e["player"]["id"], e["player"]["name"]),
                              "penalty": e["shot"]["type"]["name"] == "Penalty", "own_goal": False, "index": e["index"]})
        # Own goals are their own event pair, not shots: "Own Goal For" belongs to
        # the team that benefits, "Own Goal Against" names the player.
        for e in mine:
            if etype(e) == "Own Goal For":
                culprit = next((o for o in events if etype(o) == "Own Goal Against" and abs(o["index"] - e["index"]) <= 3), None)
                who = names.get(culprit["player"]["id"], culprit["player"]["name"]) if culprit and "player" in culprit else "Own goal"
                goals.append({"t": t(e), "minute": minute_label(e), "scorer": who, "penalty": False, "own_goal": True, "index": e["index"]})
        goals.sort(key=lambda g: g["index"])

        xg = sum(e["shot"]["statsbomb_xg"] for e in shots)
        teams[key] = {
            "name": info[key],
            "id": tid,
            "events": mine,
            "shots": shots,
            "goals": goals,
            "stats": {
                "goals": len(goals),
                "xg": round(xg, 2),
                "np_xg": round(sum(e["shot"]["statsbomb_xg"] for e in shots if e["shot"]["type"]["name"] != "Penalty"), 2),
                "shots": len(shots),
                "shots_on_target": sum(e["shot"]["outcome"]["name"] in ON_TARGET for e in shots),
                "passes_attempted": len(passes),
                "passes_completed": len(completed),
                "pass_accuracy": round(100 * len(completed) / len(passes), 1) if passes else 0.0,
                "corners": sum(e["pass"].get("type", {}).get("name") == "Corner" for e in passes),
                "fouls": sum(etype(e) == "Foul Committed" for e in mine),
            },
            "shootout": sum(e["shot"]["outcome"]["name"] == "Goal" for e in shootout if e["team"]["id"] == tid),
            "network": pass_network(mine, names, numbers),
        }

    return {"info": info, "teams": teams, "t": t, "offsets": offsets, "lengths": lengths,
            "total": total, "names": names, "had_shootout": bool(shootout)}


def pass_network(team_events: list[dict], names: dict, numbers: dict) -> dict:
    """Average positions and pass links for one settled XI.

    The network covers kick-off until the first substitution made after half-time
    (or full time). Averaging positions across a substitution blurs two different
    shapes together; a forced change before the break is handled by swapping the
    replacement in rather than cutting the window to a few minutes.
    """
    xi = next((e for e in team_events if etype(e) == "Starting XI"), None)
    if not xi:
        return {"nodes": [], "links": [], "until": None}
    on_pitch = {p["player"]["id"] for p in xi["tactics"]["lineup"]}
    for p in xi["tactics"]["lineup"]:
        numbers.setdefault(p["player"]["id"], p.get("jersey_number"))

    cutoff, until = float("inf"), None
    for sub in (e for e in team_events if etype(e) == "Substitution"):
        if sub["period"] == 1:
            on_pitch.discard(sub["player"]["id"])
            on_pitch.add(sub["substitution"]["replacement"]["id"])
        else:
            cutoff, until = sub["index"], minute_label(sub)
            break

    spots = defaultdict(list)
    made = Counter()
    pairs = Counter()
    for e in team_events:
        if etype(e) != "Pass" or e["index"] >= cutoff or "outcome" in e["pass"]:
            continue
        # The data names the receiver; inferring it from "whoever acts next" miscounts
        # whenever a foul, duel or opposition touch sits between pass and reception.
        passer, receiver = e["player"]["id"], e["pass"].get("recipient", {}).get("id")
        if passer not in on_pitch or receiver not in on_pitch:
            continue
        spots[passer].append(e["location"])
        spots[receiver].append(e["pass"]["end_location"])
        made[passer] += 1
        pairs[tuple(sorted((passer, receiver)))] += 1

    nodes = [
        {"id": pid, "name": short_name(names.get(pid, "")), "number": numbers.get(pid),
         "x": sum(p[0] for p in pts) / len(pts), "y": sum(p[1] for p in pts) / len(pts), "passes": made[pid]}
        for pid, pts in spots.items()
    ]
    links = [{"a": a, "b": b, "n": n} for (a, b), n in pairs.items()]
    return {"nodes": nodes, "links": links, "until": until}


# ---------------------------------------------------------------- drawing

def draw_network(ax, team: dict, color: str) -> None:
    pitch = VerticalPitch(pitch_type="statsbomb", pitch_color=BG, line_color=LINE, linewidth=1)
    pitch.draw(ax=ax)
    net = team["network"]
    until = f"to first second-half sub ({net['until']})" if net["until"] else "full match"
    ax.set_title(f"Passing network · {until}", fontsize=10, color=MUTED, pad=6)
    if not net["nodes"]:
        return
    pos = {n["id"]: n for n in net["nodes"]}
    most = max((l["n"] for l in net["links"]), default=1)
    for l in net["links"]:
        if l["n"] < 3:  # one-off passes are noise at this scale
            continue
        a, b, w = pos[l["a"]], pos[l["b"]], l["n"] / most
        pitch.lines(a["x"], a["y"], b["x"], b["y"], lw=0.8 + 6 * w, color=color, alpha=0.2 + 0.6 * w, zorder=2, ax=ax)
    top = max(n["passes"] for n in net["nodes"]) or 1
    for n in net["nodes"]:
        pitch.scatter(n["x"], n["y"], s=260 + 620 * n["passes"] / top, color=color, edgecolors=INK, linewidth=1.2, zorder=3, ax=ax)
        pitch.annotate(str(n["number"] or ""), xy=(n["x"], n["y"]), ha="center", va="center", fontsize=9,
                       fontweight="bold", color=text_on(color), zorder=4, ax=ax)
        pitch.annotate(n["name"], xy=(n["x"] - 5.2, n["y"]), ha="center", va="center", fontsize=7.5, color=INK, zorder=5, ax=ax,
                       path_effects=[pe.withStroke(linewidth=2.2, foreground=BG)])


def draw_shots(ax, team: dict, color: str) -> None:
    pitch = VerticalPitch(pitch_type="statsbomb", half=True, pitch_color=BG, line_color=LINE, linewidth=1)
    pitch.draw(ax=ax)
    s = team["stats"]
    ax.set_title(f"Shots · {s['shots']} for {s['xg']:.2f} xG", fontsize=10, color=MUTED, pad=6)
    for e in sorted(team["shots"], key=lambda e: -e["shot"]["statsbomb_xg"]):
        goal = e["shot"]["outcome"]["name"] == "Goal"
        # A shot from the taker's own half (an empty-net breakaway) is pinned to the halfway line
        # so it stays on the half-pitch instead of floating below it.
        pitch.scatter(max(e["location"][0], 61), e["location"][1], s=40 + 900 * e["shot"]["statsbomb_xg"],
                      color=color if goal else BG, edgecolors=INK if goal else color,
                      linewidth=1.2, alpha=1 if goal else 0.85, zorder=3 if goal else 2, ax=ax)
    ax.text(0.5, -0.03, "filled = goal · size = xG", transform=ax.transAxes, ha="center", va="top", fontsize=8, color=MUTED)


def draw_xg_race(ax, m: dict, colors: dict) -> None:
    t, total = m["t"], m["total"]
    ax.set_facecolor(BG)
    ax.set_title("xG race", fontsize=10, color=MUTED, pad=6)
    peak = 0.0
    for key in ("home", "away"):
        team, color = m["teams"][key], colors[key]
        xs, ys, running = [0.0], [0.0], 0.0
        at = {}
        for e in team["shots"]:
            running += e["shot"]["statsbomb_xg"]
            xs.append(t(e)); ys.append(running); at[e["index"]] = running
        xs.append(total); ys.append(running)
        peak = max(peak, running)
        ax.plot(xs, ys, drawstyle="steps-post", color=color, lw=2.2, label=f"{team['name']}  {running:.2f}", zorder=3)
        for i, g in enumerate(team["goals"]):
            # An own goal has no shot behind it, so it sits on the line at the xG so far.
            y = at.get(g["index"], max([v for x, v in zip(xs, ys) if x <= g["t"]], default=0))
            ax.scatter(g["t"], y, s=70, color=color, edgecolors=INK, linewidth=1.2, zorder=5)
            tag = short_name(g["scorer"]) + (" (pen)" if g["penalty"] else " (og)" if g["own_goal"] else "")
            # Two quick goals by one side would print their labels on top of each other.
            crowded = i > 0 and g["t"] - team["goals"][i - 1]["t"] < 6
            ax.annotate(f"{tag} {g['minute']}", (g["t"], y), xytext=(6, -3) if crowded else (-4, 7), textcoords="offset points",
                        ha="left" if crowded else "right", va="top" if crowded else "bottom", fontsize=7.5, color=INK, zorder=6,
                        path_effects=[pe.withStroke(linewidth=2.2, foreground=BG)])

    ticks, labels = [0.0], ["KO"]
    periods = sorted(m["offsets"])
    for p in periods[1:]:
        ticks.append(m["offsets"][p]); labels.append({2: "HT", 3: "90'", 4: "ET HT"}[p])
        ax.axvline(m["offsets"][p], color=LINE, lw=1, ls="--", zorder=1)
    ticks.append(total); labels.append("FT" if periods[-1] <= 2 else "120'")
    ax.set_xticks(ticks, labels)
    ax.set_xlim(0, total)
    ax.set_ylim(0, max(peak * 1.18, 0.5))
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.grid(axis="y", color=LINE, lw=0.6, alpha=0.6)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=INK)


def draw_stats(ax, m: dict, colors: dict) -> None:
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    h, a = m["teams"]["home"]["stats"], m["teams"]["away"]["stats"]
    rows = [
        ("xG", h["xg"], a["xg"], "{:.2f}"),
        ("Shots", h["shots"], a["shots"], "{}"),
        ("On target", h["shots_on_target"], a["shots_on_target"], "{}"),
        ("Passes completed", h["passes_completed"], a["passes_completed"], "{}"),
        ("Pass accuracy", h["pass_accuracy"], a["pass_accuracy"], "{:.0f}%"),
        ("Corners", h["corners"], a["corners"], "{}"),
        ("Fouls", h["fouls"], a["fouls"], "{}"),
    ]
    step = 0.9 / len(rows)
    for i, (label, hv, av, fmt) in enumerate(rows):
        y = 0.93 - i * step
        ax.text(0.5, y, label, ha="center", va="center", fontsize=10, color=MUTED)
        ax.text(0.08, y, fmt.format(hv), ha="left", va="center", fontsize=15, color=INK, fontweight="bold" if hv > av else "normal")
        ax.text(0.92, y, fmt.format(av), ha="right", va="center", fontsize=15, color=INK, fontweight="bold" if av > hv else "normal")
        share = hv / (hv + av) if hv + av else 0.5
        yb = y - step * 0.36
        ax.plot([0.08, 0.08 + 0.84 * share - 0.004], [yb, yb], color=colors["home"], lw=4, solid_capstyle="butt")
        ax.plot([0.08 + 0.84 * share + 0.004, 0.92], [yb, yb], color=colors["away"], lw=4, solid_capstyle="butt")


def render(m: dict, colors: dict, out: Path, dpi: int = 160) -> None:
    info, home, away = m["info"], m["teams"]["home"], m["teams"]["away"]
    fig = plt.figure(figsize=(16, 11.5), facecolor=BG)
    gs = fig.add_gridspec(2, 3, height_ratios=[1.5, 1], width_ratios=[1, 0.95, 1],
                          left=0.03, right=0.97, top=0.845, bottom=0.07, hspace=0.16, wspace=0.08)

    for key, team, x, ha in (("home", home, 0.445, "right"), ("away", away, 0.555, "left")):
        fig.text(x, 0.935, f" {team['name']} ", ha=ha, va="center", fontsize=25, fontweight="bold", color=text_on(colors[key]),
                 bbox=dict(boxstyle="round,pad=0.25", facecolor=colors[key], edgecolor="none"))
    fig.text(0.5, 0.935, f"{home['stats']['goals']}–{away['stats']['goals']}", ha="center", va="center",
             fontsize=30, fontweight="bold", color=INK)
    sub = " · ".join(x for x in (f"{info['competition']} {info['season']}", info["stage"], info["date"], info["stadium"]) if x)
    if m["had_shootout"]:
        sub = f"{home['shootout']}–{away['shootout']} on penalties · " + sub
    fig.text(0.5, 0.888, sub, ha="center", va="center", fontsize=11.5, color=MUTED)

    draw_network(fig.add_subplot(gs[0, 0]), home, colors["home"])
    draw_stats(fig.add_subplot(gs[0, 1]), m, colors)
    draw_network(fig.add_subplot(gs[0, 2]), away, colors["away"])
    draw_shots(fig.add_subplot(gs[1, 0]), home, colors["home"])
    draw_xg_race(fig.add_subplot(gs[1, 1]), m, colors)
    draw_shots(fig.add_subplot(gs[1, 2]), away, colors["away"])

    fig.text(0.97, 0.022, "Data: StatsBomb Open Data", ha="right", va="center", fontsize=9, color=MUTED)
    fig.text(0.03, 0.022, "Both teams shown attacking upwards", ha="left", va="center", fontsize=9, color=MUTED)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, facecolor=BG)
    plt.close(fig)


# ---------------------------------------------------------------- summary

def slug(m: dict) -> str:
    info = m["info"]
    return re.sub(r"[^a-z0-9]+", "-", sbdata.fold(f"{info['home']}-{info['away']}-{info['date']}")).strip("-")


def summarise(m: dict) -> dict:
    """The numbers behind the report, as plain data that can be quoted exactly."""
    info, home, away = m["info"], m["teams"]["home"], m["teams"]["away"]
    goals = sorted(
        ({"team": tm["name"], "scorer": g["scorer"], "minute": g["minute"], "penalty": g["penalty"],
          "own_goal": g["own_goal"], "_i": g["index"]} for tm in (home, away) for g in tm["goals"]),
        key=lambda g: g["_i"],
    )
    for g in goals:
        del g["_i"]
    # The score is counted from events; the match listing is an independent record of it.
    listed = (info["home_score"], info["away_score"])
    counted = (home["stats"]["goals"], away["stats"]["goals"])
    return {
        "match": {k: info[k] for k in ("match_id", "date", "competition", "season", "stage", "stadium")},
        "home": {"team": home["name"], **home["stats"]},
        "away": {"team": away["name"], **away["stats"]},
        "goals": goals,
        "shootout": {home["name"]: home["shootout"], away["name"]: away["shootout"]} if m["had_shootout"] else None,
        "network_window": {tm["name"]: tm["network"]["until"] or "full match" for tm in (home, away)},
        "score_matches_listing": listed == counted,
    }


def shot_list(m: dict) -> list[dict]:
    """Every non-shootout shot in match order, for analysis beyond the standard report."""
    rows = []
    for tm in m["teams"].values():
        for e in tm["shots"]:
            sh = e["shot"]
            rows.append({
                "team": tm["name"],
                "player": m["names"].get(e["player"]["id"], e["player"]["name"]),
                "minute": minute_label(e),
                "xg": round(sh["statsbomb_xg"], 3),
                "outcome": sh["outcome"]["name"],
                "type": sh["type"]["name"],
                "body_part": sh.get("body_part", {}).get("name"),
                "x": e["location"][0], "y": e["location"][1],
                "_i": e["index"],
            })
    rows.sort(key=lambda r: r["_i"])
    for r in rows:
        del r["_i"]
    return rows
