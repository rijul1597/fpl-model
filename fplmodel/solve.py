"""Multi-week transfer plan from Sertalp Bilal's open-source solver, fed with our projections.

Solver: https://github.com/sertalpbilal/FPL-Optimization-Tools (Apache-2.0), cloned into
vendor/solver at SOLVER_COMMIT by the workflow. It plans squad, transfers (with rolled free
transfers and hits), lineup, captain and chips across several gameweeks with HiGHS, and works out
your real selling prices and free transfers from your public FPL transfer history.
"""

import contextlib
import datetime as dt
import io
import os
import sys
from pathlib import Path

import pandas as pd

from . import ROOT, fpl

SOLVER_DIR = Path(os.environ.get("FPL_SOLVER_DIR", ROOT / "vendor" / "solver"))
SOLVER_COMMIT = "ec65f5e2b2be34441cb4b2a9efafea1ec0fe3b79"
THRESHOLD = 0.5
PLAN_FORMAT = 2  # bump when the plan JSON changes shape; the pipeline re-solves old plans


def _load_solver():
    if str(SOLVER_DIR) not in sys.path:
        sys.path.insert(0, str(SOLVER_DIR))
    import utils  # noqa: PLC0415  (solver modules live in vendor/solver)
    from dev import solver  # noqa: PLC0415

    # Route the solver's HTTP calls through our client: retries, proxy fallback, offline mode.
    utils.cached_request = fpl.get
    solver.cached_request = fpl.get
    return utils, solver


def plan(solver_csv: pd.DataFrame, team_id: int | None = None, team_json: dict | None = None,
         horizon: int = 6, settings: dict | None = None) -> dict:
    """Solve for one team. Pass team_id (live) or team_json (the solver's my_data shape, for tests)."""
    utils, solver = _load_solver()
    solver_csv.to_csv(SOLVER_DIR / "data" / "app_model.csv", index=False)
    options = utils.load_settings()
    options.update({"datasource": "app_model", "horizon": horizon, "verbose": False,
                    "team_id": team_id, **(settings or {})})
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        my_data = team_json if team_json is not None else solver.generate_team_json(team_id, options)
        data = solver.prep_data(my_data, options)
        results = solver.solve_multi_period_fpl(data, options)
    best = max(results, key=lambda r: r["score"])
    return _summarise(best, data, team_id, horizon, options)


def _names(df: pd.DataFrame) -> list[dict]:
    return [{"id": int(r.id), "name": r.name, "pos": r.pos, "team": r.team, "xp": round(float(r.xP), 2)}
            for r in df.itertuples()]


def _summarise(best: dict, data: dict, team_id, horizon: int, options: dict) -> dict:
    picks = best["picks"]
    weeks = []
    for w in sorted(picks["week"].unique()):
        wk = picks[picks["week"] == w]
        stats = best["statistics"].get(int(w), {})
        lineup = wk[wk["lineup"] > THRESHOLD].sort_values(["type", "xP"], ascending=[True, False])
        bench = wk[wk["bench"] >= 0].sort_values("bench")
        cap = wk[wk["captain"] > THRESHOLD]
        vice = wk[wk["vicecaptain"] > THRESHOLD]
        chip = wk.loc[wk["chip"] != "", "chip"]
        weeks.append({
            "gw": int(w),
            "chip": chip.iloc[0] if not chip.empty else None,
            "transfers_out": _names(wk[wk["transfer_out"] > THRESHOLD]),
            "transfers_in": _names(wk[wk["transfer_in"] > THRESHOLD]),
            "hits": int(round(stats.get("pt", 0))),
            "bank": round(float(stats.get("itb", 0)), 1),
            "free_transfers": int(round(stats.get("ft", 0))),
            "captain": cap.iloc[0]["name"] if not cap.empty else None,
            "captain_id": int(cap.iloc[0]["id"]) if not cap.empty else None,
            "vice_captain": vice.iloc[0]["name"] if not vice.empty else None,
            "vice_captain_id": int(vice.iloc[0]["id"]) if not vice.empty else None,
            "lineup_xp": round(float(stats.get("xP", lineup["xp_cont"].sum())), 2),
            "lineup": _names(lineup),
            "bench": _names(bench),
        })
    return {
        "format": PLAN_FORMAT,
        "team_id": team_id,
        "next_gw": int(data["next_gw"]),
        "horizon": horizon,
        "solved_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "solver_commit": SOLVER_COMMIT,
        "settings": {k: options.get(k) for k in ["decay_base", "no_transfer_last_gws", "ft_value_list", "xmin_lb", "ev_per_price_cutoff"]},
        "bank_now": round(float(data["itb"]), 1),
        "free_transfers_now": int(data["ft"]),
        "total_xp": round(float(best["total_xp"]), 2),
        "weeks": weeks,
    }


def to_markdown(p: dict) -> str:
    lines = [
        f"# Transfer plan for team {p['team_id']}",
        "",
        f"Planned {p['solved_at']} for GW{p['next_gw']}–GW{p['next_gw'] + p['horizon'] - 1}, "
        f"from the FPL Planner model's projections. Bank £{p['bank_now']}m, {p['free_transfers_now']} free transfer(s).",
        "",
        "| GW | Move | Hits | Captain | Lineup xP |",
        "|---|---|---|---|---|",
    ]
    for w in p["weeks"]:
        outs = ", ".join(x["name"] for x in w["transfers_out"])
        ins = ", ".join(x["name"] for x in w["transfers_in"])
        move = f"{outs} → {ins}" if outs or ins else "Roll the transfer"
        if w["chip"]:
            move = f"**{w['chip']}** " + move
        lines.append(f"| {w['gw']} | {move} | {'-' + str(4 * w['hits']) if w['hits'] else '0'} | {w['captain']} | {w['lineup_xp']} |")
    first = p["weeks"][0]
    lines += ["", f"## GW{first['gw']} team", ""]
    for label, key in [("Starting XI", "lineup"), ("Bench", "bench")]:
        lines.append(f"**{label}:** " + ", ".join(f"{x['name']} ({x['xp']})" for x in first[key]))
        lines.append("")
    lines.append(f"Solver: [FPL-Optimization-Tools](https://github.com/sertalpbilal/FPL-Optimization-Tools) at `{p['solver_commit'][:7]}`.")
    return "\n".join(lines) + "\n"
