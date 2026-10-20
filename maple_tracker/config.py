"""Settings, taught characters and session history, all kept in the data/ folder."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

# Run from source: the project folder. Packaged as MapleTracker.exe: the exe's own folder, so the
# data sits next to it (the packaged code itself is unpacked somewhere temporary).
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = DATA / "config.json"
GLYPHS = DATA / "glyphs.json"
HISTORY = DATA / "sessions.jsonl"

DEFAULTS = {
    "regions": {},          # "exp" / "mesos": box from screen.make_region
    "prices": {},           # item -> price, where the player's differs from the NPC shop's
    "idle_seconds": 60,     # no EXP for this long: stop counting time
    "overlay_pos": None,
    "alpha": 0.9,
}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG.exists():
        try:
            cfg.update(json.loads(CONFIG.read_text("utf-8")))
        except (OSError, ValueError):
            pass
    return cfg


def save(cfg):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    tmp.replace(CONFIG)


def append_history(record):
    DATA.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
