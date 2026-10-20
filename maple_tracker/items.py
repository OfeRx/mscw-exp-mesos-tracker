"""Recognising potions and food by their icons, and reading how many of each there are.

The item list, icons and NPC shop prices come from NiaMeowDB, downloaded into data/items/ on
first run (see itemdata.py).

The game draws icons pixel for pixel at a whole multiple of their size, so an icon is
recognised by how many of its pixels match exactly. What's drawn over it is left out of the
comparison: the count over its bottom-left corner, and on the quickslot the key name over its
top."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import itemdata
from .glyphs import parse_number
from .locate import find_count, game_px as _game_px

# Where items can be, at locator scale 1: the quickslot from the EXP label, the inventory's
# slots from its MESOS label.
QUICKSLOT = (235, -150, 195, 115)
INVENTORY = (-200, -260, 230, 250)

MIN_SCORE = 0.75        # share of an icon's uncovered pixels that must match
MIN_MARGIN = 0.25       # ahead of the next best item at the same spot
TOLERANCE = 24          # per colour channel


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    kind: str           # "Potion" or "Food"
    price: int          # NPC shop price
    estimated: bool     # no open shop sells it: 10x the sell-back price


@dataclass
class Spot:
    item: Item
    box: tuple          # x, y, w, h of the icon in the screenshot
    score: float

    def count_point(self, game_px):
        """Where the count is: over the slot's bottom-left corner."""
        x, y, w, h = self.box
        return x + w / 2 - 12 * game_px, y + h - 5 * game_px


class ItemLibrary:
    """The potions and food it can recognise: empty until the data has been downloaded."""

    def __init__(self, folder: Path = itemdata.FOLDER):
        self.folder = folder
        self.reload()

    def reload(self):
        folder = self.folder
        entries = json.loads((folder / "items.json").read_text("utf-8")) if itemdata.available(folder) else []
        items, icons = [], {}
        for e in entries:
            icon = folder / "icons" / f"{e['id']}.png"
            if "(Alt)" in e["name"] or not icon.exists():
                continue                    # the "(Alt)" ones look the same as the originals
            items.append(Item(e["id"], e["name"], e["kind"], e["price"], e["estimated"]))
            icons[e["id"]] = np.asarray(Image.open(icon).convert("RGBA"))
        self.items, self._icons = items, icons
        self.by_name = {i.name: i for i in items}
        self._scale, self._templates = None, []

    def icon(self, name):
        """An item's icon as a picture (RGBA), or None."""
        item = self.by_name.get(name)
        return Image.fromarray(self._icons[item.id]) if item else None

    def _build(self, game_px):
        if self._scale == round(game_px, 3):
            return self._templates
        templates = []
        for item in self.items:
            icon = self._icons[item.id]
            h, w = icon.shape[:2]
            size = (max(1, round(w * game_px)), max(1, round(h * game_px)))
            a = np.asarray(Image.fromarray(icon).resize(size, Image.NEAREST))
            core = a[..., 3] == 255
            th, tw = core.shape
            core[: int(th * 0.3)] = False                       # key name on the quickslot
            core[int(th * 0.6):, : int(tw * 0.8)] = False       # the count
            if core.sum() < 40:
                continue
            rgb = a[..., :3]
            templates.append((item, rgb.astype(np.int16), rgb.astype(np.float32), core,
                              np.dstack([core.astype(np.float32)] * 3)))
        self._scale, self._templates = round(game_px, 3), templates
        return templates

    def scan(self, img, rect, game_px):
        """Every potion and food icon inside rect (x, y, w, h) of a screenshot, as Spots."""
        x0, y0, w, h = (int(round(v)) for v in rect)
        x0, y0 = max(0, x0), max(0, y0)
        region = img[y0:y0 + h, x0:x0 + w]
        if region.shape[0] < 8 or region.shape[1] < 8:
            return []
        reg16, reg32 = region.astype(np.int16), region.astype(np.float32)
        found = []                                  # (score, item, x, y, w, h)
        for item, t16, t32, core, core3 in self._build(game_px):
            th, tw = core.shape
            if region.shape[0] < th or region.shape[1] < tw:
                continue
            res = cv2.matchTemplate(reg32, t32, cv2.TM_SQDIFF, mask=core3)
            rms = np.sqrt(np.maximum(res, 0) / (core.sum() * 3))
            # Candidate spots: local best fits that are at least roughly right.
            local = rms <= cv2.erode(rms, np.ones((9, 9), np.uint8))
            ys, xs = np.nonzero(local & (rms <= 70))
            order = np.argsort(rms[ys, xs])[:12]
            for y, x in zip(ys[order], xs[order]):
                score = _exact_share(reg16, t16, core, x, y)
                if score >= 0.35:
                    found.append((score, item, x + x0, y + y0, tw, th))
        found.sort(key=lambda f: -f[0])
        spots = []
        for score, item, x, y, tw, th in found:
            cx, cy = x + tw / 2, y + th
            near = [s for s in spots if abs(s.box[0] + s.box[2] / 2 - cx) < tw * 0.6
                    and abs(s.box[1] + s.box[3] - cy) < th * 0.6]
            if near:
                continue                            # a better fit is already here
            if score < MIN_SCORE:
                continue
            rival = max((f[0] for f in found if f[1] != item and abs(f[2] + f[4] / 2 - cx) < tw * 0.6
                         and abs(f[3] + f[5] - cy) < th * 0.6), default=0)
            if score - rival >= MIN_MARGIN:
                spots.append(Spot(item, (x, y, tw, th), score))
        return spots


def _exact_share(region, template, core, x, y):
    """Share of the icon's uncovered pixels that match exactly here (or one pixel off)."""
    th, tw = core.shape
    best = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            yy, xx = y + dy, x + dx
            if yy < 0 or xx < 0 or yy + th > region.shape[0] or xx + tw > region.shape[1]:
                continue
            same = np.abs(region[yy:yy + th, xx:xx + tw] - template).max(axis=2) <= TOLERANCE
            best = max(best, float((same & core).sum() / core.sum()))
    return best


@dataclass
class Count:
    value: int | None   # None: not (fully) read
    text: str           # what was read, '?' for each character not recognised
    img: object         # the count's picture, to learn from


def read_count(img, spot, scale, store):
    """The count over an item found in a screenshot, or None if there's no count there."""
    px, py = spot.count_point(_game_px(scale))
    box = find_count(img, px, py, scale)
    if not box:
        return None
    x, y, w, h = box
    crop = img[max(0, y):y + h, max(0, x):x + w]
    text, _ = store.read("potion", crop)
    return Count(parse_number(text), text, crop)


def fits(text, value):
    """Whether a partly read count (like '1?1') can be `value`: same number of digits, and
    every digit that was read is the same. At least one must have been read."""
    digits = text.replace(".", "")
    target = str(value)
    return (len(digits) == len(target) and any(c != "?" for c in digits)
            and all(c in ("?", t) for c, t in zip(digits, target)))


def teach_counts(store, quick, stacks):
    """Learn count digits without asking, from what the game shows twice: the quickslot's
    count is the total of that item's stacks in the inventory. A quickslot count that can't
    be read is taught the inventory total; one stack that can't be read is taught the
    quickslot count minus the other stacks. Only when the digits that were read agree.

    quick: item -> Count; stacks: item -> [Count] (inventory open). Returns the items taught."""
    taught = []
    for name, counts in stacks.items():
        q = quick.get(name)
        unread = [c for c in counts if c.value is None]
        known = sum(c.value for c in counts if c.value is not None)
        if q is not None and q.value is None and not unread:
            lesson = (q, known)
        elif q is not None and q.value is not None and len(unread) == 1 and q.value - known >= 1:
            lesson = (unread[0], q.value - known)
        else:
            continue
        count, value = lesson
        if fits(count.text, value) and store.learn("potion", count.img, str(value), strict=True)[0]:
            taught.append(name)
    return taught


def combine(quick, inventory, unsure, unlinked):
    """How many of each item there are, from one scan.

    The quickslot shows the total of that item in the inventory, live. The inventory (Use tab,
    while open) shows every stack in view. When the quickslot shows more, some stacks are out
    of view (scrolled), so the quickslot is right. When it shows fewer, the quickslot holds a
    different item that looks the same (one you have none of), so it's not trusted until the
    two agree again. `unlinked` is that set of untrusted quickslot items, updated in place.
    `inventory` is None when it's closed or on another tab."""
    counts = {}
    if inventory is not None:
        counts.update(inventory)
        for name, n in quick.items():
            if name in unsure:
                continue
            if n >= inventory.get(name, 0):
                unlinked.discard(name)
            else:
                unlinked.add(name)
    for name, n in quick.items():
        if name not in unlinked and n >= counts.get(name, 0):
            counts[name] = n
    return counts
