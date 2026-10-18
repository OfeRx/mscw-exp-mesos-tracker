"""Finding and reading the numbers in a real screenshot of the game, with the fonts the app
ships with: at the screenshot's own size, and enlarged as on a bigger screen."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maple_tracker.glyphs import GlyphStore, ink, parse_exp, parse_number, segment
from maple_tracker.locate import EXP_TEXT, MESOS_TEXT, Locator, find_count, gray

SHOT = Image.open(Path(__file__).parent / "frames" / "game_inventory.png").convert("RGB")


def shot(scale):
    im = SHOT if scale == 1 else SHOT.resize((round(SHOT.width * scale), round(SHOT.height * scale)),
                                             Image.BICUBIC)
    return np.asarray(im)


def cut(img, rect):
    x, y, w, h = rect
    return img[y:y + h, x:x + w]


@pytest.mark.parametrize("scale", [1, 1.72, 2.4])
def test_finds_exp_and_mesos_at_any_size(scale):
    """The labels are found at any window size. (Reading is checked on the sharp capture
    below: this screenshot was shrunk and compressed, and the app only keeps sharp examples.)"""
    img = shot(scale)
    loc = Locator()
    exp = loc.find_exp(gray(img))
    assert exp and exp.scale == pytest.approx(scale, rel=0.05)
    assert loc.find_mesos(gray(img))
    x, y, w, h = exp.rect(EXP_TEXT)
    assert len(segment(ink(cut(img, (x, y, w, h))))) == len("171,328[79.10%]")


def test_no_inventory_no_mesos():
    img = shot(1).copy()
    img[230:570, 255:500] = 120                     # inventory window closed
    loc = Locator()
    assert loc.find_exp(gray(img))
    assert loc.find_mesos(gray(img)) is None


NATIVE = np.asarray(Image.open(Path(__file__).parent / "frames" / "native.png").convert("RGB"))


def test_reads_a_full_resolution_capture():
    """The player's own screen (3440x1440): everything read with the fonts the app ships with."""
    loc, store = Locator(), GlyphStore()
    exp = loc.find_exp(gray(NATIVE))
    assert exp.scale == pytest.approx(1.72, abs=0.01)
    assert parse_exp(store.read("exp", cut(NATIVE, exp.rect(EXP_TEXT)))[0]) == (171561, 79.21)
    mesos = loc.find_mesos(gray(NATIVE))
    assert parse_number(store.read("mesos", cut(NATIVE, mesos.rect(MESOS_TEXT)))[0]) == 228935
    # Potion counts on the quickslot, picked by clicking on them.
    for (x, y), count in {(2325, 1280): 206, (2387, 1280): 12, (2240, 1205): 0}.items():
        box = find_count(NATIVE, x, y, exp.scale)
        assert box and parse_number(store.read("potion", cut(NATIVE, box))[0]) == count


def test_potion_box_follows_the_window_size():
    loc = Locator()
    loc.find_exp(gray(NATIVE))
    box = find_count(NATIVE, 2325, 1280, loc.exp.scale)          # "206" on the quickslot
    anchor = loc.to_exp(box)
    small = np.asarray(Image.fromarray(NATIVE).resize((2580, 1080), Image.LANCZOS))   # 0.75x
    loc2 = Locator()
    loc2.find_exp(gray(small))
    x, y, w, h = loc2.from_exp(anchor)
    assert x == pytest.approx(box[0] * 0.75, abs=2) and y == pytest.approx(box[1] * 0.75, abs=2)
    assert w == pytest.approx(box[2] * 0.75, abs=2)
