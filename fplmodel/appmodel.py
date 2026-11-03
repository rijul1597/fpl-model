"""Run the app's TypeScript model (appmodel/model.ts) from Python via Node."""

import hashlib
import json
import subprocess
import tempfile

import pandas as pd

from . import ROOT

MODEL_TS = ROOT / "appmodel" / "model.ts"
RUNNER_TS = ROOT / "appmodel" / "run.ts"


def model_version() -> str:
    """Short hash of model.ts, recorded with every snapshot so grades can be tied to a model version."""
    return hashlib.sha256(MODEL_TS.read_bytes()).hexdigest()[:12]


def project(bootstrap: dict, fixtures: list, horizon: int = 8) -> tuple[int, list[int], pd.DataFrame]:
    """Return (next_gw, gws, frame) with one row per player per gameweek: id, gw, pts, xmins, p60, fixtures."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"bootstrap": bootstrap, "fixtures": fixtures, "horizon": horizon}, f)
        path = f.name
    out = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(RUNNER_TS), path],
        check=True,
        capture_output=True,
        text=True,
    )
    res = json.loads(out.stdout)
    rows = [
        {"id": p["id"], "gw": int(gw), **vals}
        for p in res["players"]
        for gw, vals in p["byGw"].items()
    ]
    frame = pd.DataFrame(rows, columns=["id", "gw", "pts", "xmins", "p60", "fixtures"])
    return res["nextGw"], res["gws"], frame
