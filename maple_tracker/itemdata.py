"""The potion and food list, icons and prices, downloaded from NiaMeowDB on first run.

Each copy of the tracker fetches these for itself into data/items/ rather than shipping them:
NiaMeowDB (https://meowdb.com) asks to be contacted before its data is republished, and the
icons are Nexon's. Item names, icons and NPC sell-back prices come from its item database;
NPC shop prices from its NPC shop pages (below, as of 2026-10-18), credited in the README."""
from __future__ import annotations

import json
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
                Image.open(BytesIO(_get(ICON_URL.format(id=key)))).convert("RGBA").save(icon)
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


if __name__ == "__main__":
    n = download(progress=lambda i, total: print(f"\r{i}/{total}", end=""))
    print(f"\nSaved {n} items to {FOLDER}")
