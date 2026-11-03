"""Projections from live FPL data: the frozen pre-deadline snapshot, and the solver's input file."""

import pandas as pd

from . import appmodel

SOURCES = ["app_model", "fpl_ep_next", "form", "pts_per_start"]
POS_LETTER = {1: "G", 2: "D", 3: "M", 4: "F"}


def build(bootstrap: dict, fixtures: list, horizon: int = 8) -> tuple[int, list[int], pd.DataFrame, pd.DataFrame]:
    """Return (next_gw, gws, snapshot, solver_csv).

    snapshot: one row per player with every source's projection for the next gameweek.
      app_model      the FPL Planner app's model (appmodel/model.ts)
      fpl_ep_next    FPL's own expected points for the next gameweek
      form           FPL's form figure (points per match, roughly the last 30 days)
      pts_per_start  season points divided by starts
    solver_csv: FPL Review-style projections (ID, Pos, {gw}_Pts, {gw}_xMins) for the solver.
    """
    next_gw, gws, proj = appmodel.project(bootstrap, fixtures, horizon)
    els = pd.DataFrame(bootstrap["elements"])
    team = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    pos = {t["id"]: t["singular_name_short"] for t in bootstrap["element_types"]}
    nxt = proj[proj["gw"] == next_gw].set_index("id")
    starts = pd.to_numeric(els.get("starts", 0), errors="coerce").fillna(0)

    snapshot = pd.DataFrame({
        "id": els["id"],
        "web_name": els["web_name"],
        "team": els["team"].map(team),
        "pos": els["element_type"].map(pos),
        "price": els["now_cost"] / 10,
        "status": els["status"],
        "chance": els["chance_of_playing_next_round"],
        "news": els["news"].fillna(""),
        "app_model": els["id"].map(nxt["pts"]).fillna(0.0).round(3),
        "app_p60": els["id"].map(nxt["p60"]).fillna(0.0).round(3),
        "app_xmins": els["id"].map(nxt["xmins"]).fillna(0.0).round(1),
        "fpl_ep_next": pd.to_numeric(els["ep_next"], errors="coerce").fillna(0.0),
        "form": pd.to_numeric(els["form"], errors="coerce").fillna(0.0),
        "pts_per_start": (els["total_points"] / starts.where(starts > 0)).fillna(0.0).round(3),
    })

    solver = pd.DataFrame({
        "ID": els["id"],
        "Name": els["web_name"],
        "Pos": els["element_type"].map(POS_LETTER),
        "Team": els["team"].map(team),
        "Value": els["now_cost"] / 10,
    })
    for g in gws:
        at = proj[proj["gw"] == g].set_index("id")
        solver[f"{g}_Pts"] = els["id"].map(at["pts"]).fillna(0.0).round(3)
        solver[f"{g}_xMins"] = els["id"].map(at["xmins"]).fillna(0.0).round(1)
    return next_gw, gws, snapshot, solver
