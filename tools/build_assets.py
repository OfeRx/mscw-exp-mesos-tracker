"""Builds maple_tracker/assets/fonts.json, the fonts the app starts with, so players don't have
to teach them. They're stored at the game's own size (one pixel per game pixel) and the app
draws them at whatever size the player's screen shows the game at:

- EXP numbers (one font with HP and MP) and item counts: from tests/frames/native.png, a
  full-resolution capture (3440x1440, the game's pixels drawn at 2x). Only sharp examples are
  kept; the EXP font's one digit missing there (3) is worked out by the app by elimination.
- The meso count: the game draws it in Tahoma 11 without smoothing, at 2x, so all ten digits
  are drawn here the same way (checked pixel for pixel against the capture)."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from maple_tracker.glyphs import DEFAULTS, GlyphStore, font_entry  # noqa: E402
from maple_tracker.locate import EXP_TEXT, MESOS_TEXT, Locator, find_count, gray  # noqa: E402


def load(name):
    return np.asarray(Image.open(ROOT / "tests" / "frames" / name).convert("RGB"))


def cut(img, rect):
    x, y, w, h = (int(round(v)) for v in rect)
    return img[y:y + h, x:x + w]


def tahoma(ch, scale=2):
    """A character as the game draws the meso count: Tahoma 11, no smoothing, enlarged by
    whole pixels, dark on the white field."""
    font = ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / "tahoma.ttf"), 11)
    im = Image.new("1", (30, 30), 0)
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    d.text((5, 5), ch, font=font, fill=1)
    a = np.asarray(im)
    rows, cols = np.flatnonzero(a.any(axis=1)), np.flatnonzero(a.any(axis=0))
    a = np.kron(a[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1], np.ones((scale, scale), bool))
    rgb = np.full((a.shape[0] + 8, a.shape[1] + 8, 3), 255, np.uint8)
    rgb[4:-4, 4:-4][a] = 0
    return rgb


native = load("native.png")
loc = Locator()
loc.find_exp(gray(native))
s = loc.exp.scale

samples = [   # kind, image, what it shows
    ("exp", cut(native, loc.exp.rect(EXP_TEXT)), "171,561 [79.21%]"),
    ("exp", native[1375:1403, 1388:1522], "[1288/1288]"),              # HP
    ("exp", native[1375:1403, 1613:1730], "[847/1072]"),               # MP
    ("mesos", cut(native, loc.find_mesos(gray(native)).rect(MESOS_TEXT)), "228,935"),
]
samples += [("mesos", tahoma(ch), ch) for ch in "0123456789"]
# Item counts: inventory (Use tab) slots, then the quickslot.
inventory = [["46", "516", "500", "500", "500"], ["500", "500", "500", "27", "100"],
             ["34", "15", "50", "17", "3"], ["4", "17", "27", "12", "89"],
             ["100", "100", "6", "38", "4"], ["5", "3", "3", "1", "3"]]
spots = [(x, y, inventory[r][c]) for r, y in enumerate((544, 612, 682, 750, 818, 886))
         for c, x in enumerate((472, 544, 616, 686, 758))]
spots += [(2325, 1280, "206"), (2387, 1280, "12"), (2240, 1205, "0")]
for x, y, text in spots:
    samples.append(("potion", cut(native, find_count(native, x, y, s)), text))

store = GlyphStore(None, defaults=None)                  # learn into memory only
failed = 0
for kind, img, text in samples:
    ok, msg = store.learn(kind, img, text)
    if not ok:
        failed += 1
        print(f"  {kind} {text!r}: {msg}")
for kind in ("exp", "mesos", "potion"):
    print(kind, "knows", "".join(store.known(kind)))
print(f"{len(samples) - failed}/{len(samples)} samples taught")

# Down to the game's own size: everything in the capture is drawn as exact 2x2 blocks.
fonts, inexact = {}, 0
for kind, temps in store.templates.items():
    for t in temps:
        base = t.mask[::2, ::2]
        exact = t.mask.shape == (base.shape[0] * 2, base.shape[1] * 2) and \
            (np.kron(base, np.ones((2, 2), bool)) == t.mask).all()
        if not exact:
            inexact += 1
            continue                    # not cleanly 2x (a stray pixel): leave it out
        entry = font_entry(t.char, base, t.rel_h, t.rel_mid)
        if entry not in fonts.setdefault(kind, []):
            fonts[kind].append(entry)
DEFAULTS.write_text(json.dumps(fonts), "utf-8")
for kind, entries in fonts.items():
    print(f"{kind}: {len(entries)} shapes, {''.join(sorted({e['char'] for e in entries}))}")
print(f"left out {inexact} examples that weren't exact 2x; wrote {DEFAULTS.name}")
