"""How well a set of projections matched what actually happened in a gameweek."""

import pandas as pd

MIN_MINUTES = 60  # same filter as Onside's open benchmark, so numbers are comparable
TOP_N = 20


def grade(frame: pd.DataFrame, sources: list[str]) -> dict:
    """frame: one row per player with 'points', 'minutes' and one projection column per source.

    Per source:
      mae60        mean absolute error on players who played 60+ minutes (lower is better)
      bias60       mean (projection - actual) on the same players; positive = too optimistic
      spearman60   rank correlation on the same players (higher is better)
      top20_pts    average actual points of the source's 20 highest projections, over all players
      captain_pts  actual points of the source's single highest projection
    """
    played = frame[frame["minutes"] >= MIN_MINUTES]
    out = {"n_players": int(len(frame)), "n60": int(len(played)), "sources": {}}
    for s in sources:
        err = played[s] - played["points"]
        ranked = frame.sort_values(s, ascending=False)
        out["sources"][s] = {
            "mae60": round(float(err.abs().mean()), 4),
            "bias60": round(float(err.mean()), 4),
            "spearman60": round(float(played[s].corr(played["points"], method="spearman")), 4),
            "top20_pts": round(float(ranked.head(TOP_N)["points"].mean()), 4),
            "captain_pts": float(ranked.iloc[0]["points"]),
            "captain_id": int(ranked.iloc[0]["id"]),
        }
    return out


def pool(per_gw: dict[int, dict], sources: list[str]) -> dict:
    """Combine per-gameweek grades, weighting each metric by the players it was computed on."""
    gws = sorted(per_gw)
    out = {"gameweeks": gws, "n60": sum(per_gw[g]["n60"] for g in gws), "sources": {}}
    for s in sources:
        w60 = [per_gw[g]["n60"] for g in gws]
        def wavg(key):
            return round(sum(per_gw[g]["sources"][s][key] * w for g, w in zip(gws, w60)) / max(sum(w60), 1), 4)
        out["sources"][s] = {
            "mae60": wavg("mae60"),
            "bias60": wavg("bias60"),
            "spearman60": wavg("spearman60"),
            "top20_pts": round(sum(per_gw[g]["sources"][s]["top20_pts"] for g in gws) / len(gws), 4),
            "captain_pts": round(sum(per_gw[g]["sources"][s]["captain_pts"] for g in gws) / len(gws), 4),
        }
    return out
