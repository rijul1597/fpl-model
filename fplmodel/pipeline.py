"""One pipeline run (the scheduled GitHub Action calls this every hour).

1. Projections: run the app's model on live FPL data -> data/projections/latest.csv
2. Freeze: inside the window before a deadline, save every source's projection for that gameweek
   -> data/snapshots/gwNN.csv (+ .json). Each run overwrites it until the deadline passes, so the
   graded snapshot is the last one made before the deadline.
3. Grade: once FPL marks a frozen gameweek finished and checked, score each source against the
   actual points -> data/grades/gwNN.json and data/SCOREBOARD.md
4. Plan: run the multi-week solver for the team in config.json -> data/plans/latest.{json,md}

Usage: python -m fplmodel.pipeline [--no-solve]
"""

import argparse
import datetime as dt
import json

import pandas as pd

from . import DATA, ROOT, appmodel, fpl, live, metrics, scoreboard, solve

CONFIG = ROOT / "config.json"


def _parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _write(path, text: str) -> bool:
    """Write only if the content changed, so unchanged runs make no commit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def run(now: dt.datetime | None = None, solve_plan: bool = True) -> dict:
    cfg = json.loads(CONFIG.read_text())
    now = now or dt.datetime.now(dt.UTC)
    bootstrap = fpl.get("bootstrap-static/")
    fixtures = fpl.get("fixtures/")
    log, changed = [], False

    nxt = next((e for e in bootstrap["events"] if e["is_next"]), None)
    if nxt is None:
        return {"log": ["No next gameweek: the season is over."], "changed": False}
    gw, deadline = nxt["id"], _parse(nxt["deadline_time"])
    hours_left = (deadline - now).total_seconds() / 3600

    # 1. Projections for the app and the solver
    next_gw, gws, snap, solver_csv = live.build(bootstrap, fixtures, cfg["horizon_projection"])
    changed |= _write(DATA / "projections" / "latest.csv", solver_csv.to_csv(index=False))

    # 2. Freeze inside the window before the deadline
    if 0 < hours_left <= cfg["freeze_window_hours"]:
        name = f"gw{gw:02d}"
        if _write(DATA / "snapshots" / f"{name}.csv", snap.to_csv(index=False)):
            changed = True
            manifest = {
                "gw": gw,
                "deadline": nxt["deadline_time"],
                "frozen_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hours_before_deadline": round(hours_left, 2),
                "model_version": appmodel.model_version(),
                "sources": live.SOURCES,
            }
            _write(DATA / "snapshots" / f"{name}.json", json.dumps(manifest, indent=2) + "\n")
            log.append(f"Froze GW{gw} projections, {hours_left:.1f}h before the deadline.")
        else:
            log.append(f"GW{gw} snapshot unchanged.")
    else:
        log.append(f"GW{gw} deadline in {hours_left:.1f}h; snapshots start {cfg['freeze_window_hours']}h before it.")

    # 3. Grade frozen gameweeks that FPL has finished and checked
    events = {e["id"]: e for e in bootstrap["events"]}
    for f in sorted((DATA / "snapshots").glob("gw*.csv")):
        g = int(f.stem[2:])
        out = DATA / "grades" / f"{f.stem}.json"
        ev = events.get(g, {})
        if out.exists() or not (ev.get("finished") and ev.get("data_checked")):
            continue
        played = fpl.get(f"event/{g}/live/")["elements"]
        actual = pd.DataFrame([{"id": e["id"], "points": e["stats"]["total_points"],
                                "minutes": e["stats"]["minutes"]} for e in played])
        frame = pd.read_csv(f).merge(actual, on="id", how="inner")
        result = metrics.grade(frame, live.SOURCES)
        manifest = json.loads((DATA / "snapshots" / f"{f.stem}.json").read_text())
        result = {"gw": g, "frozen_at": manifest["frozen_at"], "model_version": manifest["model_version"], **result}
        _write(out, json.dumps(result, indent=2) + "\n")
        changed = True
        best = min(result["sources"], key=lambda s: result["sources"][s]["mae60"])
        log.append(f"Graded GW{g}: lowest miss {best} ({result['sources'][best]['mae60']:.2f}).")
    changed |= _write(DATA / "SCOREBOARD.md", scoreboard.render())
    changed |= _write(DATA / "scoreboard.json", json.dumps(scoreboard.render_json(), indent=2) + "\n")

    # 4. Transfer plan
    team_id = cfg.get("team_id")
    plan_file = DATA / "plans" / "latest.json"
    if solve_plan and team_id:
        old = json.loads(plan_file.read_text()) if plan_file.exists() else None
        stale = (old is None or old.get("format") != solve.PLAN_FORMAT
                 or old.get("team_id") != team_id or old.get("next_gw") != gw
                 or (now - _parse(old["solved_at"])).total_seconds() > cfg["solve_every_hours"] * 3600)
        if stale:
            p = solve.plan(solver_csv, team_id=team_id, horizon=cfg["horizon_solver"], settings=cfg.get("solver_settings"))
            _write(plan_file, json.dumps(p, indent=2) + "\n")
            _write(DATA / "plans" / "latest.md", solve.to_markdown(p))
            changed = True
            first = p["weeks"][0]
            move = ", ".join(x["name"] for x in first["transfers_out"]) or "roll"
            log.append(f"Planned team {team_id}: GW{first['gw']} {move} -> "
                       f"{', '.join(x['name'] for x in first['transfers_in']) or '-'}; captain {first['captain']}.")

    status = {"next_gw": gw, "deadline": nxt["deadline_time"], "model_version": appmodel.model_version(),
              "solver_commit": solve.SOLVER_COMMIT, "log": log}
    if changed:
        status["last_change"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write(DATA / "status.json", json.dumps(status, indent=2) + "\n")
    return {"log": log, "changed": changed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-solve", action="store_true")
    args = ap.parse_args()
    res = run(solve_plan=not args.no_solve)
    print("\n".join(res["log"]))
    print("outputs changed" if res["changed"] else "no output changes")


if __name__ == "__main__":
    main()
