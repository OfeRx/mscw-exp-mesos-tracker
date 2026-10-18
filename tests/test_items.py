"""Finding potions and food by their icons in a full-resolution capture of the game."""
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maple_tracker import itemdata
from maple_tracker.glyphs import GlyphStore
from maple_tracker.items import INVENTORY, QUICKSLOT, ItemLibrary, combine, read_count
from maple_tracker.locate import Locator, game_px, gray

# Recognising items needs the data from NiaMeowDB, downloaded on the app's first run.
needs_items = pytest.mark.skipif(not itemdata.available(), reason="item data not downloaded yet")

NATIVE = np.asarray(Image.open(Path(__file__).parent / "frames" / "native.png").convert("RGB"))


def scan(region):
    loc, lib, store = Locator(), ItemLibrary(), GlyphStore()
    g = gray(NATIVE)
    exp = loc.find_exp(g)
    rect = exp.rect(QUICKSLOT) if region == "quickslot" else loc.find_mesos(g).rect(INVENTORY)
    totals = defaultdict(int)
    for spot in lib.scan(NATIVE, rect, game_px(exp.scale)):
        totals[spot.item.name] += read_count(NATIVE, spot, exp.scale, store).value
    return dict(totals)


@needs_items
def test_quickslot():
    assert scan("quickslot") == {"Blue Potion": 0, "Lemon": 206, "Meat": 12}


@needs_items
def test_inventory_use_tab():
    # Arrows, throwing stars and scrolls aren't potions or food, so they're left out; the three
    # stacks of Lemons add up to what the quickslot shows.
    assert scan("inventory") == {"Red Potion": 27, "Orange Potion": 134, "White Potion": 15,
                                 "Blue Potion": 50, "Meat": 12, "Orange": 89, "Lemon": 206}


@needs_items
def test_prices_come_with_the_items():
    lib = ItemLibrary()
    assert lib.by_name["Lemon"].price == 150 and not lib.by_name["Lemon"].estimated
    assert lib.by_name["White Potion"].price == 350
    assert lib.by_name["Elixir"].estimated


def test_combining_quickslot_and_inventory():
    unlinked = set()
    # Inventory closed: the quickslot's counts are all there is.
    assert combine({"Lemon": 206, "Blue Potion": 0}, None, [], unlinked) == {"Lemon": 206, "Blue Potion": 0}
    # Inventory open: its totals win; the quickslot's Blue Potion says 0 while the inventory
    # has 50, so that slot holds something else that looks the same and isn't trusted after.
    counts = combine({"Lemon": 206, "Blue Potion": 0}, {"Lemon": 206, "Blue Potion": 50}, [], unlinked)
    assert counts == {"Lemon": 206, "Blue Potion": 50} and unlinked == {"Blue Potion"}
    assert combine({"Lemon": 205, "Blue Potion": 0}, None, [], unlinked) == {"Lemon": 205}


class FakeStore:
    """Stands in for the font: remembers what it was taught."""

    def __init__(self):
        self.taught = []

    def learn(self, kind, img, text, strict=False):
        self.taught.append(text)
        return True, ""


def test_counts_teach_each_other():
    from maple_tracker.items import Count, fits, teach_counts
    assert fits("1?1", 151) and fits("1??", 108) and not fits("1?1", 152)
    assert not fits("???", 108)                    # nothing read: nothing to check it against
    assert not fits("12", 108)                     # different number of digits
    store = FakeStore()
    # The quickslot's Lemon count couldn't be read; the inventory's two stacks could.
    quick = {"Lemon": Count(None, "1?1", None)}
    stacks = {"Lemon": [Count(100, "100", None), Count(51, "51", None)]}
    assert teach_counts(store, quick, stacks) == ["Lemon"] and store.taught == ["151"]
    # One stack couldn't be read; the quickslot says how many in all.
    store = FakeStore()
    quick = {"Orange Potion": Count(134, "134", None)}
    stacks = {"Orange Potion": [Count(100, "100", None), Count(None, "3?", None)]}
    assert teach_counts(store, quick, stacks) == ["Orange Potion"] and store.taught == ["34"]
    # A quickslot lookalike (it shows 0, the inventory has 50): nothing that fits, nothing taught.
    store = FakeStore()
    quick = {"Blue Potion": Count(None, "?", None)}
    stacks = {"Blue Potion": [Count(50, "50", None)]}
    assert teach_counts(store, quick, stacks) == [] and store.taught == []


def test_inventory_on_another_tab_says_nothing_about_potions():
    unlinked = set()
    combine({"Lemon": 151, "Blue Potion": 0}, {"Lemon": 151, "Blue Potion": 67}, [], unlinked)
    assert unlinked == {"Blue Potion"}               # the quickslot's 0 is a lookalike
    # Inventory switched to the Etc tab: no inventory totals at all (None), so the lookalike
    # quickslot 0 must not turn into "you have no Blue Potions".
    assert combine({"Lemon": 150, "Blue Potion": 0}, None, [], unlinked) == {"Lemon": 150}


def test_scrolled_inventory_trusts_the_quickslot():
    unlinked = set()
    # One stack of Lemons scrolled out of view: the inventory shows 100, the quickslot 151.
    assert combine({"Lemon": 151}, {"Lemon": 100}, [], unlinked) == {"Lemon": 151}
    assert not unlinked


@needs_items
def test_scanner_sees_another_tab_as_unknown():
    from maple_tracker.app import ItemScanner
    img = NATIVE.copy()
    img[495:915, 440:830] = (225, 223, 213)          # the slots, as on a tab with no potions
    class FakeScreen:
        def frame_rect(self):
            return (0, 0, img.shape[1], img.shape[0]), True

        def grab(self, rect):
            return img
    out = ItemScanner(GlyphStore(), ItemLibrary(), None).scan_once(FakeScreen())
    assert out["inventory_open"] and out.get("other_tab") and out["inventory"] is None
    assert out["quick"] == {"Lemon": 206, "Blue Potion": 0, "Meat": 12}
