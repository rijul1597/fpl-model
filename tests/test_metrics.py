"""Self-test the workflow runs before the pipeline, with only requirements.txt installed.

It caught nothing the first time round because scipy happened to be installed locally; grading
GW10 then failed on GitHub because pandas' Spearman needs scipy. Run: python tests/test_metrics.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fplmodel import metrics  # noqa: E402

frame = pd.DataFrame({
    "id": [1, 2, 3, 4, 5],
    "points": [2, 9, 1, 6, 0],
    "minutes": [90, 90, 70, 90, 10],
    "good": [3.0, 7.0, 2.0, 5.0, 1.0],
    "bad": [5.0, 1.0, 6.0, 2.0, 9.0],
})
g = metrics.grade(frame, ["good", "bad"])
assert g["n60"] == 4
assert g["sources"]["good"]["spearman60"] == 1.0, g
assert g["sources"]["bad"]["spearman60"] == -1.0, g
assert g["sources"]["good"]["mae60"] < g["sources"]["bad"]["mae60"]
assert g["sources"]["good"]["captain_id"] == 2
# a constant projection has no defined rank correlation: report 0, don't crash
assert metrics.spearman(pd.Series([1.0, 1.0, 1.0]), pd.Series([1, 2, 3])) == 0.0
pooled = metrics.pool({10: g, 11: g}, ["good", "bad"])
assert pooled["n60"] == 8 and pooled["sources"]["good"]["mae60"] == g["sources"]["good"]["mae60"]
print("metrics self-test passed")
