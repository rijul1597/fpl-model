"""Rebuild what FPL's data looked like just before a past deadline, from the public vaastav dataset.

https://github.com/vaastav/Fantasy-Premier-League keeps one row per player per fixture with the
stats from that match. Summing the rows before gameweek g gives each player's season-to-date
numbers at the g deadline, which is what the app's model needs. Injury flags and news at the time
are not in the dataset, so every player is treated as available; grading on players who played
60+ minutes keeps that from mattering.

The dataset's own "xP" column is NOT used: it was recorded after the matches (it correlates
0.74-0.77 with the same week's actual points) or is missing, so it would leak the result.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

POSITIONS = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP", "plural_name": "Goalkeepers"},
    {"id": 2, "singular_name_short": "DEF", "plural_name": "Defenders"},
    {"id": 3, "singular_name_short": "MID", "plural_name": "Midfielders"},
    {"id": 4, "singular_name_short": "FWD", "plural_name": "Forwards"},
]
# FPL scoring for 2025/26 onward, in the shape the live API uses in game_config.scoring.
SCORING = {
    "long_play": 2,
    "short_play": 1,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "saves": 1,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}
SUM_COLS = [
    "minutes", "starts", "bonus", "saves", "total_points",
    "expected_goals", "expected_assists", "expected_goals_conceded", "defensive_contribution",
]


@dataclass
class Season:
    gws: pd.DataFrame
    fixtures: pd.DataFrame
    teams: pd.DataFrame
    players: pd.DataFrame

    @property
    def rounds(self) -> list[int]:
        return sorted(int(r) for r in self.gws["round"].unique())


def load_season(data_dir: str | Path) -> Season:
    d = Path(data_dir)
    return Season(
        gws=pd.read_csv(d / "gws" / "merged_gw.csv"),
        fixtures=pd.read_csv(d / "fixtures.csv"),
        teams=pd.read_csv(d / "teams.csv"),
        players=pd.read_csv(d / "players_raw.csv"),
    )


def _per90(total: float, minutes: float) -> float:
    return round(total * 90 / minutes, 2) if minutes > 0 else 0.0


def _deadlines(fixtures: pd.DataFrame) -> dict[int, str]:
    """FPL deadlines are 90 minutes before the first kickoff of the gameweek."""
    out = {}
    for event, grp in fixtures.dropna(subset=["event", "kickoff_time"]).groupby("event"):
        first = min(datetime.fromisoformat(k.replace("Z", "+00:00")) for k in grp["kickoff_time"])
        out[int(event)] = (first - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def bootstrap_at(season: Season, g: int) -> tuple[dict, list[dict]]:
    """bootstrap-static and fixtures as they would have looked just before the gameweek g deadline."""
    team_id = dict(zip(season.teams["name"], season.teams["id"]))
    web_name = dict(zip(season.players["id"], season.players["web_name"]))

    before = season.gws[season.gws["round"] < g]
    totals = before.groupby("element")[SUM_COLS].sum()
    per_round = before.groupby(["element", "round"])["total_points"].sum().unstack(fill_value=0)
    recent = [r for r in per_round.columns if r >= g - 4]
    form = per_round[recent].mean(axis=1) if recent else pd.Series(dtype=float)

    now = season.gws[season.gws["round"] == g].groupby("element").first()
    elements = []
    for eid, row in now.iterrows():
        t = totals.loc[eid] if eid in totals.index else pd.Series(0.0, index=SUM_COLS)
        mins = float(t["minutes"])
        elements.append({
            "id": int(eid),
            "web_name": web_name.get(eid, row["name"]),
            "first_name": "",
            "second_name": row["name"],
            "team": int(team_id[row["team"]]),
            "element_type": POSITIONS[row["position"]],
            "now_cost": int(row["value"]),
            "minutes": int(mins),
            "starts": int(t["starts"]),
            "saves": int(t["saves"]),
            "saves_per_90": _per90(float(t["saves"]), mins),
            "bonus": int(t["bonus"]),
            "form": f"{float(form.get(eid, 0.0)):.1f}",
            "status": "a",
            "news": "",
            "total_points": int(t["total_points"]),
            "chance_of_playing_next_round": None,
            "expected_goals": f"{float(t['expected_goals']):.2f}",
            "expected_goals_conceded": f"{float(t['expected_goals_conceded']):.2f}",
            "expected_goals_per_90": _per90(float(t["expected_goals"]), mins),
            "expected_assists_per_90": _per90(float(t["expected_assists"]), mins),
            "defensive_contribution_per_90": _per90(float(t["defensive_contribution"]), mins),
        })

    deadlines = _deadlines(season.fixtures)
    events = [
        {"id": e, "name": f"Gameweek {e}", "deadline_time": deadlines.get(e, ""),
         "is_current": e == g - 1, "is_next": e == g, "finished": e < g}
        for e in range(1, 39)
    ]
    teams = [
        {"id": int(r.id), "name": r.name, "short_name": r.short_name,
         "strength_attack_home": 0, "strength_attack_away": 0,
         "strength_defence_home": 0, "strength_defence_away": 0}
        for r in season.teams.itertuples()
    ]
    fixtures = []
    for f in season.fixtures.itertuples():
        done = pd.notna(f.event) and int(f.event) < g
        fixtures.append({
            "id": int(f.id), "event": int(f.event) if pd.notna(f.event) else None,
            "team_h": int(f.team_h), "team_a": int(f.team_a),
            "team_h_difficulty": int(f.team_h_difficulty), "team_a_difficulty": int(f.team_a_difficulty),
            "finished": bool(done), "kickoff_time": f.kickoff_time if pd.notna(f.kickoff_time) else None,
            "team_h_score": int(f.team_h_score) if done and pd.notna(f.team_h_score) else None,
            "team_a_score": int(f.team_a_score) if done and pd.notna(f.team_a_score) else None,
        })
    bootstrap = {
        "elements": elements, "teams": teams, "element_types": ELEMENT_TYPES,
        "events": events, "chips": [], "game_config": {"scoring": SCORING},
    }
    return bootstrap, fixtures


def actuals(season: Season, g: int) -> pd.DataFrame:
    """Points and minutes each player actually got in gameweek g (doubles summed)."""
    rows = season.gws[season.gws["round"] == g]
    return (rows.groupby("element", as_index=False)
                .agg(points=("total_points", "sum"), minutes=("minutes", "sum"))
                .rename(columns={"element": "id"}))
