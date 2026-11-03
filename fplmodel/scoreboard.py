"""Render data/SCOREBOARD.md from the live grades and the backtest."""

import json

from . import DATA, metrics

LABELS = {
    "app_model": "FPL Planner model",
    "fpl_ep_next": "FPL's own projection (ep_next)",
    "form": "Form (FPL's form figure)",
    "pts_per_start": "Season points per start",
}


def _table(pooled: dict) -> list[str]:
    rows = sorted(pooled["sources"].items(), key=lambda kv: kv[1]["mae60"])
    out = [
        "| Source | Avg miss, 60+ min players | Bias | Rank corr. | Avg pts of top-20 picks | Avg captain pts |",
        "|---|---|---|---|---|---|",
    ]
    for s, v in rows:
        out.append(f"| {LABELS.get(s, s)} | {v['mae60']:.2f} | {v['bias60']:+.2f} | {v['spearman60']:.2f} | "
                   f"{v['top20_pts']:.2f} | {v['captain_pts']:.1f} |")
    return out


def _per_gw(per_gw: dict, sources: list[str]) -> list[str]:
    head = "| GW | " + " | ".join(LABELS.get(s, s) for s in sources) + " |"
    out = [head, "|---|" + "---|" * len(sources)]
    for g in sorted(per_gw, key=int):
        out.append(f"| {g} | " + " | ".join(f"{per_gw[g]['sources'][s]['mae60']:.2f}" for s in sources) + " |")
    return out


def _live_grades() -> dict[str, dict]:
    grades = {}
    for f in sorted((DATA / "grades").glob("gw*.json")):
        g = json.loads(f.read_text())
        grades[str(g["gw"])] = g
    return grades


def render_json() -> dict:
    """The same numbers as SCOREBOARD.md, for the app (data/scoreboard.json)."""
    out = {"labels": LABELS, "live": None, "backtests": []}
    grades = _live_grades()
    if grades:
        sources = list(next(iter(grades.values()))["sources"])
        pooled = metrics.pool({int(k): v for k, v in grades.items()}, sources)
        out["live"] = {
            "gameweeks": pooled["gameweeks"],
            "n60": pooled["n60"],
            "pooled": pooled["sources"],
            "per_gw": {g: {s: v["sources"][s]["mae60"] for s in sources} for g, v in grades.items()},
        }
    for f in sorted((DATA / "backtest").glob("*.json")):
        bt = json.loads(f.read_text())
        out["backtests"].append({
            "season": bt["season"],
            "note": bt["note"],
            "gameweeks": bt["pooled"]["gameweeks"],
            "n60": bt["pooled"]["n60"],
            "pooled": bt["pooled"]["sources"],
            "per_gw": {str(g): {s: v["sources"][s]["mae60"] for s in v["sources"]} for g, v in bt["per_gw"].items()},
        })
    return out


def render() -> str:
    lines = [
        "# Scoreboard",
        "",
        "How each set of projections did against actual FPL points. **Avg miss** is the mean absolute "
        "error on players who played 60+ minutes (lower is better, same filter as "
        "[Onside's open benchmark](https://onsidearena.com/vs/fantasy-football-hub)). **Bias** above zero "
        "means too optimistic. The last two columns are decision checks: the actual points of each "
        "source's 20 highest projections and of its single top pick.",
        "",
        "## Live: projections frozen before each deadline",
        "",
    ]
    grades = {}
    for f in sorted((DATA / "grades").glob("gw*.json")):
        g = json.loads(f.read_text())
        grades[str(g["gw"])] = g
    if grades:
        sources = list(next(iter(grades.values()))["sources"])
        pooled = metrics.pool({int(k): v for k, v in grades.items()}, sources)
        lines += [f"{len(grades)} gameweek(s), {pooled['n60']} player-gameweeks with 60+ minutes.", ""]
        lines += _table(pooled) + ["", "Avg miss by gameweek:", ""] + _per_gw(grades, sources)
    else:
        lines.append("No gameweek graded yet. The first live grade lands after the first frozen gameweek finishes.")

    for f in sorted((DATA / "backtest").glob("*.json")):
        bt = json.loads(f.read_text())
        gws = bt["pooled"]["gameweeks"]
        lines += [
            "",
            f"## Backtest: {bt['season']}, GW{gws[0]}–GW{gws[-1]}",
            "",
            f"{bt['note']} {bt['pooled']['n60']} player-gameweeks with 60+ minutes.",
            "",
        ]
        lines += _table(bt["pooled"]) + ["", "Avg miss by gameweek:", ""]
        lines += _per_gw({str(k): v for k, v in bt["per_gw"].items()}, list(bt["pooled"]["sources"]))
    return "\n".join(lines) + "\n"
