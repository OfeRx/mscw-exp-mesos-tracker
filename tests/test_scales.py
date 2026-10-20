"""Other screen sizes: the numbers from the player's 2x screen, shown at the game's own size (1x)
and at 3x, read with the app's fonts drawn at that size."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maple_tracker.glyphs import GlyphStore, parse_exp, parse_number

FRAMES = Path(__file__).parent / "frames"
WANT = {"exp_2135": (194097, 89.61), "exp_2220": (19590, 8.15), "mesos_2135": 243249,
        "count_2135_lemon": 151, "count_2135_orange_potion": 108, "count_2135_blue_potion": 0,
        "count_2220_lemon": 63, "count_2220_orange_potion": 83}


def at(name, k):
    """A crop from the 2x screen as a screen showing the game at k x would: every game pixel is
    a 2x2 block there, so taking every other pixel gives the game's own size."""
    base = np.asarray(Image.open(FRAMES / f"{name}.png").convert("RGB"))[::2, ::2]
    return np.ascontiguousarray(np.kron(base, np.ones((k, k, 1), np.uint8)))


@pytest.mark.parametrize("k", [1, 2, 3])
def test_numbers_read_at_any_whole_size(k):
    store = GlyphStore()
    store.set_scale(k)
    for name, want in WANT.items():
        kind = "exp" if name.startswith("exp") else "mesos" if name.startswith("mesos") else "potion"
        text, _ = store.read(kind, at(name, k))
        got = parse_exp(text) if kind == "exp" else parse_number(text)
        assert got == want, (k, name, text)


@pytest.mark.skipif(not __import__("maple_tracker.itemdata").itemdata.available(),
                    reason="item data not downloaded yet")
@pytest.mark.parametrize("k", [1, 3])
def test_whole_screen_at_other_sizes(k):
    """The full-resolution capture as a 1x or 3x screen would show it: labels found, every
    number read, every potion recognised and counted."""
    from collections import defaultdict
    from maple_tracker.items import INVENTORY, QUICKSLOT, ItemLibrary, read_count
    from maple_tracker.locate import EXP_TEXT, MESOS_TEXT, Locator, game_px, gray
    base = np.asarray(Image.open(FRAMES / "native.png").convert("RGB"))[::2, ::2]
    img = np.ascontiguousarray(np.kron(base, np.ones((k, k, 1), np.uint8)))
    loc, store, lib = Locator(), GlyphStore(), ItemLibrary()
    exp, mesos = loc.find_exp(gray(img)), loc.find_mesos(gray(img))
    px = game_px(exp.scale)
    assert px == k
    store.set_scale(px)
    x, y, w, h = exp.rect(EXP_TEXT)
    assert parse_exp(store.read("exp", img[y:y + h, x:x + w])[0]) == (171561, 79.21)
    x, y, w, h = mesos.rect(MESOS_TEXT)
    assert parse_number(store.read("mesos", img[y:y + h, x:x + w])[0]) == 228935
    quick = {s.item.name: read_count(img, s, exp.scale, store).value
             for s in lib.scan(img, exp.rect(QUICKSLOT), px)}
    assert quick == {"Lemon": 206, "Blue Potion": 0, "Meat": 12}
    totals = defaultdict(int)
    for s in lib.scan(img, mesos.rect(INVENTORY), px):
        totals[s.item.name] += read_count(img, s, exp.scale, store).value
    assert totals == {"Meat": 12, "Lemon": 206, "Red Potion": 27, "Orange Potion": 134,
                      "White Potion": 15, "Blue Potion": 50, "Orange": 89}


def test_own_windows_are_blacked_out_of_what_is_read():
    from maple_tracker.screen import blank_own
    img = np.full((100, 200, 3), 255, np.uint8)
    frame = (1000, 500, 200, 100)                     # where the screenshot was taken from
    # The overlay sits partly over it (screen coordinates), another window elsewhere.
    out = blank_own(img, frame, [(1150, 450, 100, 100), (0, 0, 50, 50)])
    assert (out[0:50, 150:200] == 0).all() and (out[50:, :] == 255).all() and (out[:, :150] == 255).all()
    assert (img == 255).all()                         # the screenshot itself is left alone
    assert blank_own(img, frame, []) is img
