"""Finding the EXP and meso numbers on screen without the player drawing boxes.

The status bar's "EXP." label and the inventory's "MESOS" label look the same every time, so
they're searched for in a screenshot of the game, and the numbers sit at a fixed offset from
them. The game scales its UI with the window, so the EXP label is searched for at a range of
sizes; once its size is known, everything else is looked for at that size, and potion counts
the player picked are kept as offsets from it."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ASSETS = Path(__file__).parent / "assets"


def _load(name):
    return cv2.cvtColor(np.asarray(Image.open(ASSETS / name).convert("RGB")), cv2.COLOR_RGB2GRAY)


EXP_LABEL = _load("exp_label.png")
MESOS_LABEL = _load("mesos_label.png")
LV_LABEL = _load("lv_label.png")
LV_DX = 499         # the LV. label is this far left of the EXP label (scale 1)

# Where each number is from its label's top-left, as (dx, dy, w, h) at the size the labels
# were cut at (scale 1).
EXP_TEXT = (30, -1, 108, 16)
MESOS_TEXT = (-166, -1, 161, 14)

# Game pixels per pixel of the reference screenshot the labels were cut from: the game draws
# its UI at locator scale x this (2x on a 3440x1440 screen, where the locator scale is 1.72).
GAME_PX = 2 / 1.7196


def game_px(scale):
    """Game pixels per screen pixel, from the locator's scale. The game enlarges its UI by whole
    (or half) steps, so a measurement a few percent off one (small labels on a small screen
    measure less precisely) is that step."""
    px = scale * GAME_PX
    step = round(px * 2) / 2
    return step if step and abs(px - step) < 0.08 else px

SCALES = [0.5 * 1.08 ** i for i in range(25)]      # 0.5x .. 3.2x
MIN_SCORE = 0.65


@dataclass
class Found:
    x: float
    y: float
    scale: float
    score: float

    def rect(self, offset):
        dx, dy, w, h = offset
        s = self.scale
        return (round(self.x + dx * s), round(self.y + dy * s), max(4, round(w * s)), max(4, round(h * s)))


def gray(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def search(img, template, scales, min_score=MIN_SCORE):
    """Best match of a template at any of the sizes, or None. The screenshot is shrunk rather
    than the template enlarged, since shrinking blurs it the way the template was blurred."""
    best = None
    th, tw = template.shape
    for s in scales:
        small = img if abs(s - 1) < 1e-6 else cv2.resize(
            img, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA if s > 1 else cv2.INTER_LINEAR)
        if small.shape[0] < th or small.shape[1] < tw:
            continue
        res = np.nan_to_num(cv2.matchTemplate(small, template, cv2.TM_CCOEFF_NORMED))
        # Flat areas (the black bars beside the game, a blank screen) can score as perfect
        # matches by accident: only count places with some detail in them.
        f = small.astype(np.float32)
        mean = cv2.boxFilter(f, -1, (tw, th), anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        sq = cv2.boxFilter(f * f, -1, (tw, th), anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        std = np.sqrt(np.maximum(sq - mean * mean, 0))[:res.shape[0], :res.shape[1]]
        res[std < 8] = 0
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if best is None or score > best.score:
            best = Found((x + _subpixel(res[y, :], x)) * s, (y + _subpixel(res[:, x], y)) * s, s, score)
    return best if best and best.score >= min_score else None


def _subpixel(line, i):
    """Where the peak at line[i] really is, between pixels (a parabola through it and its
    neighbours): things far from the label, like potion counts, need it placed precisely."""
    if i <= 0 or i >= len(line) - 1:
        return 0.0
    a, b, c = float(line[i - 1]), float(line[i]), float(line[i + 1])
    d = a - 2 * b + c
    return 0.0 if d >= 0 else max(-0.5, min(0.5, 0.5 * (a - c) / d))


def find_count(img, x, y, scale):
    """The box around the item count the player clicked on, in the same coordinates as `img`,
    or None if there's no count there. It's left-aligned in its slot and room is left to the
    right for more digits."""
    from .glyphs import ink, segment
    s = scale
    x0, y0 = max(0, int(x - 24 * s)), max(0, int(y - 10 * s))
    x1, y1 = min(img.shape[1], int(x + 24 * s)), min(img.shape[0], int(y + 10 * s))
    glyphs = sorted((g for g in segment(ink(img[y0:y1, x0:x1], outlined=True)) if not g.small),
                    key=lambda g: g.box[0])
    if not glyphs:
        return None
    px, py = x - x0, y - y0

    def gap(g):
        bx0, by0, bx1, by1 = g.box
        return max(bx0 - px, 0, px - bx1) + max(by0 - py, 0, py - by1)
    seed = min(glyphs, key=gap)
    if gap(seed) > 8 * s:
        return None
    i = glyphs.index(seed)
    h = seed.box[3] - seed.box[1]
    lo = hi = i

    def same_line(a, b):
        overlap = min(a.box[3], b.box[3]) - max(a.box[1], b.box[1])
        return overlap >= 0.5 * h and abs(a.box[0] - b.box[2]) <= 0.6 * h or \
            overlap >= 0.5 * h and abs(b.box[0] - a.box[2]) <= 0.6 * h
    while lo > 0 and same_line(glyphs[lo - 1], glyphs[lo]):
        lo -= 1
    while hi < len(glyphs) - 1 and same_line(glyphs[hi], glyphs[hi + 1]):
        hi += 1
    run = glyphs[lo:hi + 1]
    left, top = min(g.box[0] for g in run), min(g.box[1] for g in run)
    bottom = max(g.box[3] for g in run)
    pad = max(1, round(2 * s))
    return (x0 + left - pad, y0 + top - pad, round(30 * s), bottom - top + 2 * pad)


class Locator:
    """Keeps track of where the EXP label is in the game's screenshots."""

    def __init__(self):
        self.exp: Found | None = None

    def find_exp(self, img):
        """The EXP label (Found) in a grayscale screenshot, or None. Checked cheaply where it
        was last time; searched for again at every size when it's moved or gone."""
        if self.exp:
            s, e = self.exp.scale, self.exp
            pad = round(8 * s)
            x0, y0 = max(0, int(e.x) - pad), max(0, int(e.y) - pad)
            x1 = min(img.shape[1], int(e.x + EXP_LABEL.shape[1] * s) + pad)
            y1 = min(img.shape[0], int(e.y + EXP_LABEL.shape[0] * s) + pad)
            f = search(img[y0:y1, x0:x1], EXP_LABEL, [s])
            if f:
                self.exp = Found(f.x + x0, f.y + y0, s, f.score)
                return self.exp
        top = int(img.shape[0] * 0.7)                      # the status bar is at the bottom
        f = search(img[top:], EXP_LABEL, SCALES)
        if f:
            fine = [f.scale * (1 + d / 100) for d in range(-4, 5)]
            f = search(img[top:], EXP_LABEL, fine) or f
            f.y += top
            f.scale = self._measure_scale(img, f)
        self.exp = f
        return f

    @staticmethod
    def _measure_scale(img, f):
        """The size of the UI, precisely. Matching one small label only tells it to a percent
        or two, which is several pixels out by the quickslot; the distance to the LV. label
        on the same bar, 500 pixels away, tells it to a fraction of that."""
        s = f.scale
        x0, x1 = max(0, int(f.x - (LV_DX + 40) * s)), max(0, int(f.x - (LV_DX - 40) * s))
        y0, y1 = max(0, int(f.y - 20 * s)), min(img.shape[0], int(f.y + 40 * s))
        if x1 - x0 < LV_LABEL.shape[1] * s or y1 - y0 < LV_LABEL.shape[0] * s:
            return s
        lv = search(img[y0:y1, x0:x1], LV_LABEL, [s])
        if not lv:
            return s
        measured = (f.x - (lv.x + x0)) / LV_DX
        return measured if abs(measured / s - 1) < 0.05 else s

    def find_mesos(self, img):
        """The MESOS label (only there while the inventory is open), or None."""
        if not self.exp:
            return None
        s = self.exp.scale
        return search(img, MESOS_LABEL, [s * 0.97, s, s * 1.03])

    def from_exp(self, offset):
        """A rectangle kept relative to the EXP label (potion counts), or None."""
        return self.exp.rect(offset) if self.exp else None

    def to_exp(self, rect):
        """The other way round: a screen-space rectangle as an offset from the EXP label."""
        x, y, w, h = rect
        s = self.exp.scale
        return ((x - self.exp.x) / s, (y - self.exp.y) / s, w / s, h / s)
