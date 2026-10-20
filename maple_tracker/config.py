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
    "zoom": 1.0,            # the overlay's size, 0.6 .. 1.5
    "sections": ["bar", "exp", "exp2", "mesos", "buttons"],   # the parts of the overlay shown
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


def load_history():
    """Every saved session, oldest first (lines that can't be read are skipped)."""
    records = []
    if HISTORY.exists():
        for line in HISTORY.read_text("utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def delete_history(record):
    """Take one session out of the history (the first saved with the same start)."""
    kept, gone = [], False
    for r in load_history():
        if not gone and r.get("started") == record.get("started") and r.get("ended") == record.get("ended"):
            gone = True
            continue
        kept.append(r)
    tmp = HISTORY.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in kept), "utf-8")
    tmp.replace(HISTORY)
