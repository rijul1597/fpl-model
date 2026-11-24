# Scoreboard

How each set of projections did against actual FPL points. **Avg miss** is the mean absolute error on players who played 60+ minutes (lower is better, same filter as [Onside's open benchmark](https://onsidearena.com/vs/fantasy-football-hub)). **Bias** above zero means too optimistic. The last two columns are decision checks: the actual points of each source's 20 highest projections and of its single top pick.

## Live: projections frozen before each deadline

2 gameweek(s), 407 player-gameweeks with 60+ minutes.

| Source | Avg miss, 60+ min players | Bias | Rank corr. | Avg pts of top-20 picks | Avg captain pts |
|---|---|---|---|---|---|
| FPL Planner model | 2.45 | -0.95 | 0.17 | 5.22 | 5.0 |
| FPL's own projection (ep_next) | 2.71 | -0.81 | 0.08 | 4.90 | 5.0 |
| Form (FPL's form figure) | 2.72 | -0.79 | 0.08 | 4.97 | 5.0 |
| Season points per start | 2.82 | +0.17 | 0.13 | 1.68 | 1.0 |

Avg miss by gameweek:

| GW | FPL Planner model | FPL's own projection (ep_next) | Form (FPL's form figure) | Season points per start |
|---|---|---|---|---|
| 10 | 2.30 | 2.54 | 2.55 | 2.54 |
| 11 | 2.61 | 2.87 | 2.88 | 3.09 |

## Backtest: 2026-27, GW2–GW6

Rebuilt from the public vaastav dataset; injury flags at the time are unavailable, so every player is treated as fit. FPL's own projection is excluded because the dataset's copy was recorded after the matches. 1035 player-gameweeks with 60+ minutes.

| Source | Avg miss, 60+ min players | Bias | Rank corr. | Avg pts of top-20 picks | Avg captain pts |
|---|---|---|---|---|---|
| FPL Planner model | 2.47 | -0.99 | 0.09 | 4.05 | 3.6 |
| Form (FPL's form figure) | 2.83 | -0.54 | 0.11 | 3.95 | 2.8 |
| Season points per start | 2.92 | -0.17 | 0.11 | 4.00 | 0.6 |

Avg miss by gameweek:

| GW | FPL Planner model | Form (FPL's form figure) | Season points per start |
|---|---|---|---|
| 2 | 2.44 | 3.10 | 3.25 |
| 3 | 2.27 | 2.97 | 3.12 |
| 4 | 2.66 | 2.73 | 2.70 |
| 5 | 2.53 | 2.77 | 2.87 |
| 6 | 2.47 | 2.55 | 2.65 |
