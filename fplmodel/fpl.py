"""FPL API client: retries, then falls back through the FPL Planner app's read-only proxy.

Set FPL_LOCAL_DIR to a folder of saved responses (entry/1/history/ -> entry_1_history.json)
to run the pipeline offline in tests.
"""

import json
import os
import re
import time
from pathlib import Path

import requests

OFFICIAL = "https://fantasy.premierleague.com/api/"
APP_PROXY = "https://fpl-gameweek-planner.lovable.app/api/public/fpl?path="
# Paths the app's proxy forwards (it rejects everything else).
PROXY_OK = re.compile(r"^(bootstrap-static/|fixtures/|entry/\d+/|entry/\d+/history/|entry/\d+/event/\d+/picks/|element-summary/\d+/)$")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; fpl-model pipeline)", "Accept": "application/json"}

_cache: dict[str, object] = {}


def _path(url_or_path: str) -> str:
    p = url_or_path.removeprefix(OFFICIAL).removeprefix("https://fantasy.premierleague.com/api").lstrip("/")
    return p if p.endswith("/") else p + "/"


def _local(path: str):
    d = os.environ.get("FPL_LOCAL_DIR")
    if not d:
        return None
    f = Path(d) / (path.strip("/").replace("/", "_") + ".json")
    if not f.exists():
        raise FileNotFoundError(f"offline mode: no saved response for {path} ({f})")
    return json.loads(f.read_text())


def get(url_or_path: str):
    """GET an FPL API path (e.g. 'bootstrap-static/') or full URL and return parsed JSON."""
    path = _path(url_or_path)
    if path in _cache:
        return _cache[path]
    data = _local(path)
    if data is None:
        data = _fetch(path)
    _cache[path] = data
    return data


def _fetch(path: str):
    last = "no attempt"
    for attempt in range(4):
        try:
            r = requests.get(OFFICIAL + path, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                break
        except requests.RequestException as e:
            last = repr(e)
        time.sleep(3 * (attempt + 1))
    if PROXY_OK.match(path):
        try:
            r = requests.get(APP_PROXY + path, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                print(f"[fpl] {path}: official API failed ({last}); used the app proxy")
                return r.json()
            last += f"; proxy HTTP {r.status_code}"
        except requests.RequestException as e:
            last += f"; proxy {e!r}"
    raise RuntimeError(f"FPL request failed for {path}: {last}")
