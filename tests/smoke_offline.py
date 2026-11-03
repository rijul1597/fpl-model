"""Offline end-to-end check of the pipeline using the public vaastav dataset instead of the live API.

  1. Pre-GW6 state rebuilt from the dataset: run the pipeline inside the freeze window -> GW6 snapshot.
  2. Post-GW6 state (the dataset's real players_raw snapshot) plus GW6 results as event/6/live:
     run again -> GW6 graded, scoreboard written.
  3. Solve a transfer plan for a fixed 15-man squad on the post-GW6 state.

Usage: FPL_SOLVER_DIR=<solver clone> python tests/smoke_offline.py <vaastav season dir> <work dir>
"""

import datetime as dt
import json
import math
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

season_dir, work = Path(sys.argv[1]), Path(sys.argv[2])
shutil.rmtree(work, ignore_errors=True)
(work / "api_pre6").mkdir(parents=True)
(work / "api_post6").mkdir(parents=True)
os.environ["FPL_DATA_DIR"] = str(work / "data")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplmodel import fpl, history, live, pipeline, solve  # noqa: E402

ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP", "plural_name": "Goalkeepers", "squad_select": 2, "squad_min_play": 1, "squad_max_play": 1},
    {"id": 2, "singular_name_short": "DEF", "plural_name": "Defenders", "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5},
    {"id": 3, "singular_name_short": "MID", "plural_name": "Midfielders", "squad_select": 5, "squad_min_play": 2, "squad_max_play": 5},
    {"id": 4, "singular_name_short": "FWD", "plural_name": "Forwards", "squad_select": 3, "squad_min_play": 1, "squad_max_play": 3},
]


def clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    return v.item() if hasattr(v, "item") else v


def save(folder, path, obj):
    (work / folder / (path.strip("/").replace("/", "_") + ".json")).write_text(json.dumps(obj))


season = history.load_season(season_dir)

# 1. Pre-GW6 state
b6, fx6 = history.bootstrap_at(season, 6)
for e in b6["elements"]:
    e["ep_next"] = e["form"]  # the dataset has no clean pre-deadline ep_next; form stands in
b6["element_types"] = ELEMENT_TYPES
for t, row in zip(b6["teams"], season.teams.itertuples()):
    t["code"] = int(row.code)
save("api_pre6", "bootstrap-static/", b6)
save("api_pre6", "fixtures/", fx6)
deadline6 = pipeline._parse(next(e for e in b6["events"] if e["id"] == 6)["deadline_time"])
os.environ["FPL_LOCAL_DIR"] = str(work / "api_pre6")
fpl._cache.clear()
r1 = pipeline.run(now=deadline6 - dt.timedelta(hours=5), solve_plan=False)
print("run 1:", r1["log"])
assert (work / "data" / "snapshots" / "gw06.csv").exists()

# 2. Post-GW6 state from the real players_raw snapshot, with GW6 results available
elements = [{k: clean(v) for k, v in row.items()} for row in season.players.to_dict("records")]
events = [dict(e, is_current=e["id"] == 6, is_next=e["id"] == 7, finished=e["id"] <= 6, data_checked=e["id"] <= 6)
          for e in b6["events"]]
fx7 = [dict(f, finished=bool(f["event"] and f["event"] <= 6)) for f in history.bootstrap_at(season, 7)[1]] \
    if 7 in season.rounds else [
    {**f, "finished": bool(f["event"] and f["event"] <= 6),
     "team_h_score": clean(row.team_h_score) if f["event"] and f["event"] <= 6 else None,
     "team_a_score": clean(row.team_a_score) if f["event"] and f["event"] <= 6 else None}
    for f, row in zip(fx6, season.fixtures.itertuples())]
b7 = {"elements": elements, "teams": b6["teams"], "element_types": ELEMENT_TYPES, "events": events,
      "chips": [], "game_config": b6["game_config"]}
live6 = history.actuals(season, 6)
save("api_post6", "bootstrap-static/", b7)
save("api_post6", "fixtures/", fx7)
save("api_post6", "event/6/live/", {"elements": [
    {"id": int(r.id), "stats": {"total_points": int(r.points), "minutes": int(r.minutes)}} for r in live6.itertuples()]})
deadline7 = pipeline._parse(next(e for e in events if e["id"] == 7)["deadline_time"])
os.environ["FPL_LOCAL_DIR"] = str(work / "api_post6")
fpl._cache.clear()
r2 = pipeline.run(now=deadline7 - dt.timedelta(hours=60), solve_plan=False)
print("run 2:", r2["log"])
grade = json.loads((work / "data" / "grades" / "gw06.json").read_text())
print("GW6 avg miss (60+):", {s: v["mae60"] for s, v in grade["sources"].items()})

# 3. Solver on the post-GW6 state for a fixed squad (team 895045's GW8 squad, by name)
squad = [("Raya", "ARS"), ("Forster", "BOU"), ("Gabriel", "ARS"), ("Konsa", "ARS"), ("Hall", "NEW"),
         ("O'Shea", "IPS"), ("De Cuyper", "BHA"), ("Rogers", "CHE"), ("Palmer", "CHE"), ("Groß", "BHA"),
         ("Schade", "BRE"), ("Slater", "HUL"), ("Haaland", "MCI"), ("Gonzalo", "FUL"), ("João Pedro", "CHE")]
short = {t["id"]: t["short_name"] for t in b7["teams"]}
els = pd.DataFrame(elements)
ids = []
for name, team in squad:
    hit = els[(els["web_name"] == name) & (els["team"].map(short) == team)]
    if hit.empty:
        hit = els[els["web_name"].str.contains(name.split()[-1], regex=False)]
    ids.append(int(hit.iloc[0]["id"]))
team_json = {"chips": [], "transfers": {"bank": 11, "limit": 1, "made": 0}, "picks": [
    {"element": i, "purchase_price": int(els.set_index("id").loc[i, "now_cost"]),
     "selling_price": int(els.set_index("id").loc[i, "now_cost"]),
     "element_type": int(els.set_index("id").loc[i, "element_type"])} for i in ids]}
_, _, _, solver_csv = live.build(b7, fx7, 8)
p = solve.plan(solver_csv, team_id=895045, team_json=team_json, horizon=6, settings={"secs": 120})
print(solve.to_markdown(p))
