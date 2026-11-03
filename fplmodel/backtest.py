"""Backtest this season: rebuild each past deadline, project with the app's model, grade against what happened.

Usage: python -m fplmodel.backtest <vaastav season dir> [--first 2]
Writes data/backtest/<season>.json.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from . import DATA, appmodel, history, metrics

SOURCES = ["app_model", "form", "pts_per_start"]


def run(season_dir: str, first: int = 2) -> dict:
    season = history.load_season(season_dir)
    per_gw = {}
    for g in [r for r in season.rounds if r >= first]:
        bootstrap, fixtures = history.bootstrap_at(season, g)
        next_gw, _, proj = appmodel.project(bootstrap, fixtures, horizon=1)
        assert next_gw == g, (next_gw, g)
        els = pd.DataFrame(bootstrap["elements"])
        frame = els[["id", "web_name", "form", "total_points", "starts"]].copy()
        frame["app_model"] = frame["id"].map(proj[proj["gw"] == g].set_index("id")["pts"]).fillna(0.0)
        frame["form"] = frame["form"].astype(float)
        frame["pts_per_start"] = (frame["total_points"] / frame["starts"].where(frame["starts"] > 0)).fillna(0.0)
        frame = frame.merge(history.actuals(season, g), on="id", how="inner")
        per_gw[g] = metrics.grade(frame, SOURCES)
    return {
        "season": Path(season_dir).name,
        "note": "Rebuilt from the public vaastav dataset; injury flags at the time are unavailable, "
                "so every player is treated as fit. FPL's own projection is excluded because the "
                "dataset's copy was recorded after the matches.",
        "model_version": appmodel.model_version(),
        "per_gw": per_gw,
        "pooled": metrics.pool(per_gw, SOURCES),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("season_dir")
    ap.add_argument("--first", type=int, default=2)
    args = ap.parse_args()
    res = run(args.season_dir, args.first)
    out = DATA / "backtest" / f"{res['season']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    rows = [{"source": s, **v} for s, v in res["pooled"]["sources"].items()]
    print(f"Backtest {res['season']} GW{res['pooled']['gameweeks'][0]}-{res['pooled']['gameweeks'][-1]}, "
          f"{res['pooled']['n60']} player-gameweeks with 60+ minutes")
    print(pd.DataFrame(rows).to_string(index=False))
    for g, r in res["per_gw"].items():
        print(f"GW{g}: " + "  ".join(f"{s} {v['mae60']:.2f}" for s, v in r["sources"].items()))


if __name__ == "__main__":
    main()
