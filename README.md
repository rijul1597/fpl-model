# fpl-model

The modelling pipeline behind the [FPL Planner](https://fpl-gameweek-planner.lovable.app) app. Every hour a GitHub Action:

1. **Projects** every player's points for the next 8 gameweeks with the app's model → [`data/projections/latest.csv`](data/projections/latest.csv)
2. **Freezes** each source's projections in the 36 hours before a deadline (the last pre-deadline version stands) → `data/snapshots/`
3. **Grades** each frozen gameweek once FPL has finished and checked it → [`data/SCOREBOARD.md`](data/SCOREBOARD.md)
4. **Plans** transfers, captaincy and bench across 6 gameweeks with an open-source solver → [`data/plans/latest.md`](data/plans/latest.md)

## What gets graded

| Source | What it is |
|---|---|
| `app_model` | The FPL Planner model: xG/xA per 90 shrunk toward position averages, minutes from start rate and injury news, opponent ratings from season xG, Poisson clean sheets, saves and goals conceded. [`appmodel/model.ts`](appmodel/model.ts) is a verbatim copy of the app's `src/lib/model.ts` and runs here through Node. |
| `fpl_ep_next` | FPL's own expected points for the next gameweek |
| `form` | FPL's form figure (points per match, roughly the last 30 days) |
| `pts_per_start` | Season points divided by starts |

Metrics, per source:
- **Avg miss:** mean absolute error on players who played 60+ minutes. That's the filter [Onside's open benchmark](https://onsidearena.com/vs/fantasy-football-hub) uses, so the numbers are comparable.
- **Bias:** whether a source runs too optimistic or too pessimistic.
- **Rank correlation:** how well it orders players.
- **Decision checks:** the actual points of each source's top-20 picks and of its top captain pick.

### Backtest

`python -m fplmodel.backtest <season dir>` rebuilds each past deadline of the season from the public [vaastav dataset](https://github.com/vaastav/Fantasy-Premier-League) and grades the app model against the two naive baselines.

Two caveats:
- **No injury flags:** the flags in force at each deadline aren't in the dataset, so every player counts as fit. The 60+ minute filter keeps that from skewing the error metric.
- **No FPL baseline:** the dataset's copy of FPL's projection (`xP`) was recorded after the matches. It correlates 0.74–0.77 with the same week's points, so it would leak the result, and it's excluded. FPL's own projection is only compared live, frozen before each deadline.

## The solver

Plans come from [FPL-Optimization-Tools](https://github.com/sertalpbilal/FPL-Optimization-Tools) by Sertalp Bilal and contributors (Apache-2.0). The workflow clones it at a pinned commit; nothing is vendored into this repo.
- **Inputs:** our projections plus your team ID. It works out your selling prices and free transfers from your public FPL transfer history.
- **Model:** a mixed-integer program solved with HiGHS, covering rolled free transfers, hits, lineup, captain and chips.

To plan for a different team, change `team_id` in [`config.json`](config.json).

## Run it locally

Needs Python 3.13+ and Node 22+ (Node runs the TypeScript model directly).

```bash
pip install -r requirements.txt
git clone https://github.com/sertalpbilal/FPL-Optimization-Tools.git vendor/solver
git -C vendor/solver checkout ec65f5e2b2be34441cb4b2a9efafea1ec0fe3b79
python -m fplmodel.pipeline              # needs access to the FPL API
python -m fplmodel.backtest <vaastav>/data/2026-27
FPL_SOLVER_DIR=vendor/solver python tests/smoke_offline.py <vaastav>/data/2026-27 /tmp/fpl-smoke
```

If the official API refuses a request, the client falls back to the FPL Planner app's read-only proxy for the paths that proxy allows.

## Next

- Calibrate the projections. They're compressed: about a point low on players who play, with too little gap between premium attackers and defenders.
- A minutes model (gradient boosting), then an LLM news agent feeding it, each kept only if it beats the graded baselines.
- Blend in betting odds for team goals, and weight the sources by their graded record.
