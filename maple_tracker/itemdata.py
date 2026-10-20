"""The potion and food list, icons and prices, and the EXP table, downloaded from NiaMeowDB on
first run.

Each copy of the tracker fetches these for itself into data/ rather than shipping them:
NiaMeowDB (https://meowdb.com) asks to be contacted before its data is republished, and the
icons are Nexon's. Item names, icons and NPC sell-back prices come from its item database;
NPC shop prices from its NPC shop pages (below, as of 2026-10-18), credited in the README."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

from . import config

FOLDER = config.DATA / "items"
LIST_URL = ("https://meowdb.com/msclassic/api/items?type=Use&subtype=Potion%2CFood&ossyria=1"
            "&page={page}&limit=25&locale=en")
ICON_URL = "https://meowdb.com/msclassic/api/assets/icons/{id}"
EXP_URL = "https://meowdb.com/msclassic/guides/exp-table-level-1-to-100"
EXP_FILE = config.DATA / "exp_table.json"
HEADERS = {"User-Agent": "MapleTracker (personal EXP and meso tracker)"}

# What NPC shops charge, from NiaMeowDB's NPC shop pages: the Victoria Road grocers and
# pharmacies, the Sleepywood sauna and Florina Beach. Anything else is estimated at 10x what
# an NPC pays for it, which is how every price here works out.
SHOP_PRICES = {
    "Red Potion": 50, "Orange Potion": 150, "White Potion": 350, "Blue Potion": 220,
    "Apple": 20, "Meat": 80, "Orange": 50, "Lemon": 150, "Egg": 30, "Pure Water": 1120,
    "Unagi": 1000, "Fried Chicken": 60, "Hot Dog": 180, "Pizza": 252, "Hamburger": 350,
    "Hot Dog Supreme": 480, "Ice Cream Pop": 1500, "Salad": 220, "Red Bean Sundae": 2250,
    "Cake": 150, "Watermelon": 1920,
}


def available(folder=FOLDER):
    return (folder / "items.json").exists()


def _get(url, timeout=20):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def download(folder: Path = FOLDER, progress=None):
    """Fetch the list and every icon into `folder`. Returns how many items were saved."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "icons").mkdir(exist_ok=True)
    entries, page = [], 1
    while True:
        data = json.loads(_get(LIST_URL.format(page=page)).decode("utf-8"))
        entries += data["items"]
        if not data.get("hasMore"):
            break
        page += 1
    items = []
    for i, e in enumerate(entries, 1):
        if progress:
            progress(i, len(entries))
        key, name = e["iconKey"], e["name"]
        icon = folder / "icons" / f"{key}.png"
        if not icon.exists():
            try:
                Image.open(BytesIO(_get(ICON_URL.format(id=key), timeout=8))).convert("RGBA").save(icon)
            except Exception:
                continue                    # no icon (a few items have none): leave it out
            time.sleep(0.15)                # go easy on their server
        stats = json.loads(e.get("stats") or "{}")
        sell = stats.get("price") or 0
        shop = SHOP_PRICES.get(name)
        items.append({"id": key, "name": name, "kind": e["subtype"], "price": shop or sell * 10,
                      "estimated": shop is None, "sell": sell})
    (folder / "items.json").write_text(json.dumps(items, indent=1), "utf-8")
    return len(items)


def exp_table(path: Path = EXP_FILE):
    """level -> EXP to the next level, or {} until it's been downloaded."""
    if not path.exists():
        return {}
    return {int(level): need for level, need in json.loads(path.read_text("utf-8")).items()}


def parse_exp_table(html):
    """The rows of the EXP table page: level, EXP to next level, ..."""
    table = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) >= 2 and cells[0].isdigit() and re.fullmatch(r"[\d,]+", cells[1]):
            table[int(cells[0])] = int(cells[1].replace(",", ""))
    return table


def download_exp_table(path: Path = EXP_FILE):
    """Fetch the EXP table and save it. Returns how many levels it has."""
    table = parse_exp_table(_get(EXP_URL).decode("utf-8", "replace"))
    levels = sorted(table)
    if len(levels) < 50 or any(table[a] > table[b] for a, b in zip(levels, levels[1:])):
        raise ValueError("the EXP table page didn't look as expected")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table), "utf-8")
    return len(table)


if __name__ == "__main__":
    n = download(progress=lambda i, total: print(f"\r{i}/{total}", end=""))
    print(f"\nSaved {n} items to {FOLDER}")
    print(f"Saved the EXP table for {download_exp_table()} levels to {EXP_FILE}")
