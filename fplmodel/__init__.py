"""FPL model pipeline: freeze projections before each deadline, grade them after, and plan transfers."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FPL_DATA_DIR", ROOT / "data"))
