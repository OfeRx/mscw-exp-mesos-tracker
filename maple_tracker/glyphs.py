"""Reading the game's numbers by matching each character against examples the player taught.

The game draws its numbers in small fixed fonts, and general OCR does badly on those (Windows'
built-in engine drops most of the digits). So each character is cut out, scaled to a standard
size and compared with saved examples. Commas and periods are told apart from digits by size
alone and read as '.', so they never need teaching."""
from __future__ import annotations

import base64
import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

NORM_W, NORM_H = 10, 14
SMALL = 0.6          # characters shorter than this share of the line are punctuation
MAX_DIST = 0.25      # farther than this from every example: not recognised
# Item counts are a crisp pixel font, the same digit drawn identically every time, while two
# different digits can differ by one stroke: only near-exact matches are believed, and
# anything else is asked about once rather than miscounted as potions drunk.
MAX_DIST_FOR = {"potion": 0.1}
# EXP and mesos are crisp pixel fonts too, where 3, 6, 8 and 9 sit about 0.06-0.09 apart:
# anything short of a near-exact match must also beat every other character by a wide margin,
# so a digit with no sharp example yet is asked about instead of read as its neighbour.
MARGIN_FOR = {"exp": 0.2, "mesos": 0.2}
PER_CHAR = 6         # examples kept per character
DEFAULTS = Path(__file__).parent / "assets" / "fonts.json"    # made by tools/build_assets.py


# --------------------------------------------------------------------------- cutting out characters

def otsu(gray):
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    p = hist / max(1, hist.sum())
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega))
    return int(np.argmax(np.nan_to_num(sigma)))


def ink(rgb, outlined=False):
    """How much each pixel is text, 0..1. Text is whichever of light/dark covers less of the
    box; keeping the in-between shades (rather than just text / not text) keeps small
    anti-aliased digits apart."""
    if outlined:
        return _outlined_ink(rgb)
    gray = rgb[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    if gray.max() - gray.min() < 40:
        return np.zeros(gray.shape, np.float32)
    fg = gray > otsu(gray)
    if fg.mean() > 0.5:
        fg = ~fg
    text, back = float(np.median(gray[fg])), float(np.median(gray[~fg]))
    return np.clip((gray - back) / (text - back), 0, 1)


def _outlined_ink(rgb):
    """Item counts are drawn as strokes one font-pixel wide, white fading to pale blue, inside a
    pure black outline, over the item's picture. Text is pixels of those colours lying in a gap
    exactly one stroke wide between outline pixels, across or down: that leaves out the item's
    picture, the slot behind, and the hole inside a '0' (wider than a stroke)."""
    px = rgb[..., :3].astype(np.int16)
    dark = px.max(axis=2) <= 40
    r, g, b = px[..., 0], px[..., 1], px[..., 2]
    colour = (b >= 250) & (g >= 195) & (r >= 145)
    stroke = _stroke_width(dark)
    return (colour & (_gaps(dark, stroke) | _gaps(dark.T, stroke).T)).astype(np.float32)


def _gaps(dark, longest):
    """Pixels in each row lying in a gap of at most `longest` between two dark pixels."""
    out = np.zeros_like(dark)
    for r in range(dark.shape[0]):
        idx = np.flatnonzero(dark[r])
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= longest + 1:
                out[r, a + 1:b] = True
    return out


def _stroke_width(dark):
    """The commonest gap between dark pixels: the stroke width at this size (2 pixels for a
    font drawn at twice its size)."""
    lengths = []
    for line in (*dark, *dark.T):
        idx = np.flatnonzero(line)
        lengths += [d - 1 for d in np.diff(idx) if 1 < d <= 8]
    return int(np.bincount(lengths).argmax()) if lengths else 2


# Which kinds of box use which kind of text.
OUTLINED = {"potion"}
NUMBERS = {"mesos", "potion"}           # nothing but digits (and commas)
ELIMINATE = NUMBERS | {"exp"}           # where a last missing digit can be worked out


def _components(mask):
    """Groups of touching text pixels (8-connected): (pixel list, x0, x1) each."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        stack, pixels = [(y0, x0)], []
        while stack:
            y, x = stack.pop()
            pixels.append((y, x))
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        xs = [p[1] for p in pixels]
        comps.append((pixels, min(xs), max(xs) + 1))
    return comps


@dataclass
class Glyph:
    box: tuple            # x0, y0, x1, y1 in the image
    bitmap: np.ndarray    # NORM_H x NORM_W, 0..1
    aspect: float         # width / height
    rel_h: float          # height / line height
    rel_mid: float        # vertical centre relative to the line's, in line heights
    crop: np.ndarray      # this character's own shading, for splitting it
    line: tuple           # (line height, line centre y) of the text it's in

    @property
    def small(self):
        return self.rel_h < SMALL

    @property
    def mask(self):
        """The character's pixels exactly as on screen."""
        return self.crop >= 0.5


def _glyph(crop, x0, y0, line):
    """A Glyph from a character's shading, trimmed to where it has ink."""
    rows = np.flatnonzero((crop >= 0.5).any(axis=1))
    cols = np.flatnonzero((crop >= 0.5).any(axis=0))
    if not len(rows) or not len(cols):
        return None
    crop = crop[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    x0, y0 = x0 + int(cols[0]), y0 + int(rows[0])
    h, w = crop.shape
    img = Image.fromarray((crop * 255).astype(np.uint8))
    bitmap = np.asarray(img.resize((NORM_W, NORM_H), Image.BILINEAR), np.float32) / 255
    line_h, line_mid = line
    return Glyph((x0, y0, x0 + w, y0 + h), bitmap, w / h, h / line_h, (y0 + h / 2 - line_mid) / line_h,
                 crop, line)


def split(g, k):
    """Cut a character that's really k touching ones, at the columns with the least ink."""
    w = g.crop.shape[1]
    ink_per_col = g.crop.sum(axis=0)
    cuts, prev = [], 0
    for i in range(1, k):
        lo = max(prev + 1, round(w * (i - 0.4) / k))
        hi = min(w - 1, round(w * (i + 0.4) / k))
        if lo >= hi:
            return None
        cuts.append(prev := lo + int(np.argmin(ink_per_col[lo:hi])))
    parts = []
    for a, b in zip([0] + cuts, cuts + [w]):
        part = _glyph(g.crop[:, a:b], g.box[0] + a, g.box[1], g.line)
        if part is None:
            return None
        parts.append(part)
    return parts


def segment(strength):
    """Characters left to right. Each is a group of touching pixels, plus any others stacked
    above or below it (the parts of '%', ':' or 'i')."""
    comps = sorted(_components(strength >= 0.5), key=lambda c: c[1])
    groups = []                                   # [x0, x1, pixels]
    for pixels, x0, x1 in comps:
        if groups:
            g = groups[-1]
            overlap = min(g[1], x1) - max(g[0], x0)
            heights = (_height(g[2]), _height(pixels))
            small, big = (g[2], pixels) if heights[0] < heights[1] else (pixels, g[2])
            # A smaller piece within the bigger one's height belongs to it (the circles of '%',
            # a dot inside a '0'); one sticking out above or below is a speck of something else.
            stacked = overlap >= 2 and min(heights) < 0.7 * max(heights)
            side = overlap >= 0.5 * min(g[1] - g[0], x1 - x0)
            if overlap > 0 and (side or stacked) and _within(small, big):
                g[0], g[1] = min(g[0], x0), max(g[1], x1)
                g[2].extend(pixels)
                continue
        groups.append([x0, x1, list(pixels)])
    if not groups:
        return []
    boxes = []
    for x0, x1, pixels in groups:
        ys = [p[0] for p in pixels]
        boxes.append((x0, min(ys), x1, max(ys) + 1))
    # Line height from the tall pieces only: specks (bits of an item's picture) can outnumber
    # the characters.
    heights = [y1 - y0 for _, y0, _, y1 in boxes]
    line_h = float(np.median([h for h in heights if h >= 0.5 * max(heights)]))
    tall = [(y0 + y1) / 2 for _, y0, _, y1 in boxes if y1 - y0 >= 0.8 * line_h]
    line = (line_h, float(np.median(tall)))
    glyphs = []
    for (x0, y0, x1, y1), (_, _, pixels) in zip(boxes, groups):
        # This character's shading only: neighbours reaching into its box are blanked out.
        own = np.zeros((y1 - y0, x1 - x0), bool)
        for y, x in pixels:
            own[y - y0, x - x0] = True
        g = _glyph(np.where(_grow(own), strength[y0:y1, x0:x1], 0), x0, y0, line)
        if g:
            glyphs.append(g)
    return glyphs


def _within(small, big):
    """Whether the small group of pixels lies within the big one's rows (give or take one)."""
    sy, by = [p[0] for p in small], [p[0] for p in big]
    return min(sy) >= min(by) - 1 and max(sy) <= max(by) + 1


def first_run(glyphs):
    """An item count's characters only: counts are left-aligned in their slot, so it's the
    first characters close together, and anything after a gap is the item's picture."""
    out = []
    for g in sorted(glyphs, key=lambda g: g.box[0]):
        if not out:
            if not g.small:
                out.append(g)
        elif g.box[0] - out[-1].box[2] <= 0.5 * g.line[0]:
            out.append(g)
        else:
            break
    return out


def _height(pixels):
    ys = [p[0] for p in pixels]
    return max(ys) - min(ys) + 1


def _grow(mask):
    """The mask plus every pixel next to it, to keep a character's anti-aliased edge."""
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= out[:, :-1].copy()
    out[:, :-1] |= out[:, 1:].copy()
    return out


# --------------------------------------------------------------------------- matching

@dataclass
class Template:
    char: str
    bitmap: np.ndarray
    aspect: float
    rel_h: float
    rel_mid: float
    mask: np.ndarray | None = None      # the example's pixels as they were on screen

    @classmethod
    def from_glyph(cls, char, g):
        return cls(char, g.bitmap, g.aspect, g.rel_h, g.rel_mid, g.mask.copy())

    def to_json(self):
        data = base64.b64encode((self.bitmap * 255).round().astype(np.uint8).tobytes()).decode()
        d = {"char": self.char, "bitmap": data, "aspect": self.aspect, "rel_h": self.rel_h,
             "rel_mid": self.rel_mid}
        if self.mask is not None:
            d["mask"] = base64.b64encode(np.packbits(self.mask).tobytes()).decode()
            d["mask_shape"] = list(self.mask.shape)
        return d

    @classmethod
    def from_json(cls, d):
        raw = np.frombuffer(base64.b64decode(d["bitmap"]), np.uint8).reshape(NORM_H, NORM_W)
        mask = None
        if "mask" in d:
            h, w = d["mask_shape"]
            bits = np.unpackbits(np.frombuffer(base64.b64decode(d["mask"]), np.uint8))
            mask = bits[: h * w].reshape(h, w).astype(bool)
        return cls(d["char"], raw.astype(np.float32) / 255, d["aspect"], d["rel_h"], d["rel_mid"], mask)


def distance(g, t):
    """How different two characters look, 0 for identical. When both are at the same size,
    which is always the case for the game's own fonts on one screen, their pixels are compared
    exactly: digits that differ by one stroke (3, 5, 6, 8, 9) are then far apart. Otherwise
    their shapes are compared scaled to a standard size."""
    exact = _pixel_distance(getattr(g, "mask", None), getattr(t, "mask", None))
    if exact is not None:
        return exact
    return (float(np.abs(g.bitmap - t.bitmap).mean())
            + 0.3 * abs(math.log(g.aspect / t.aspect))
            + 0.5 * abs(g.rel_h - t.rel_h)
            + 0.5 * abs(g.rel_mid - t.rel_mid))


def _pixel_distance(a, b):
    """Share of the two characters' pixels that differ (at the best alignment, give or take a
    pixel), or None if they aren't the same size."""
    if a is None or b is None:
        return None
    (ha, wa), (hb, wb) = a.shape, b.shape
    if 0 <= ha - hb <= 1 and 2 <= wa - wb <= 4:
        return _with_stray_edge(a, b)
    if abs(ha - hb) > 1 or abs(wa - wb) > 1:
        return None
    h, w = max(ha, hb) + 2, max(wa, wb) + 2
    big = np.zeros((h, w), bool)
    big[1:1 + ha, 1:1 + wa] = a
    best = 1.0
    for dy in range(h - hb + 1):
        for dx in range(w - wb + 1):
            other = np.zeros((h, w), bool)
            other[dy:dy + hb, dx:dx + wb] = b
            union = (big | other).sum()
            if union:
                best = min(best, float((big ^ other).sum() / union))
    return best


def _with_stray_edge(a, b):
    """Like _pixel_distance, for a character a few pixels wider than the example because
    something stray clings to its side (on a crowded quickslot): the example is slid along
    it, and pixels left over outside count half."""
    (ha, wa), (hb, wb) = a.shape, b.shape
    best = 1.0
    for dx in range(wa - wb + 1):
        for dy in range(ha - hb + 1):
            window = a[dy:dy + hb, dx:dx + wb]
            outside = int(a.sum()) - int(window.sum())
            union = int((window | b).sum()) + outside
            if union:
                best = min(best, (int((window ^ b).sum()) + 0.5 * outside) / union)
    return best


SURE = 0.06         # this close to an example: it's that character
MARGIN = 0.08       # otherwise, the best must beat every other character by this much


def _match(g, temps, limit=MAX_DIST, margin=None):
    """The character g is, or None. Some digits differ by one stroke, so a character never
    taught can sit close to one that was (an unseen 0 next to a 9): a loose match only counts
    when nothing else is nearly as close."""
    nearest = {}
    for t in temps:
        d = distance(g, t)
        if d < nearest.get(t.char, math.inf):
            nearest[t.char] = d
    if not nearest:
        return None
    ranked = sorted(nearest.items(), key=lambda kv: kv[1])
    best, best_d = ranked[0]
    if best_d > limit:
        return None
    # The lead is measured against every other character, however far: a match that's only
    # loose isn't trusted just because nothing else came within the limit.
    if best_d <= SURE or len(ranked) == 1 or ranked[1][1] - best_d >= (margin or MARGIN):
        return best
    return None


class GlyphStore:
    """Examples of each character, kept separately per kind of box ("exp", "mesos", "potion")
    since the game uses a different font for each. Shared between the reading threads and the
    UI.

    Two sources: the fonts that come with the app, stored at the game's own size (one screen
    pixel per game pixel) and redrawn at the size this screen shows the game at (set_scale);
    and what was learned while playing (taught, worked out, or learned from the inventory),
    kept as seen on this screen and saved in the player's file."""

    def __init__(self, path: Path | None = None, defaults: Path | None = DEFAULTS):
        self.path = path
        self.lock = threading.Lock()
        self.templates: dict[str, list[Template]] = {}      # learned while playing
        if path and path.exists():
            data = json.loads(path.read_text("utf-8"))
            self.templates = {k: [Template.from_json(t) for t in v] for k, v in data.items()}
        self.base = load_fonts(defaults) if defaults and defaults.exists() else {}
        self.scale = 2.0                    # game pixels per screen pixel, until measured
        self._drawn = {}                    # (kind, scale) -> the base fonts drawn at that size

    def set_scale(self, game_px):
        """The size this screen shows the game at, measured from the EXP bar."""
        self.scale = round(float(game_px), 2)

    def all(self, kind):
        """Every example of this kind: learned ones and the app's fonts at this screen's size."""
        scale = self.scale
        key = (kind, scale)
        with self.lock:
            if key not in self._drawn:
                self._drawn[key] = [draw_template(*entry, scale) for entry in self.base.get(kind, [])]
            return list(self.templates.get(kind, [])) + self._drawn[key]

    def known(self, kind):
        return sorted({t.char for t in self.all(kind)})

    def read(self, kind, rgb):
        """(text, glyphs), one character per glyph: '?' for any not taught yet."""
        temps = self.all(kind)
        digits = [t.aspect for t in temps if t.char.isdigit() and t.char != "1"]
        typical = float(np.median(digits)) if digits else None
        limit, margin = MAX_DIST_FOR.get(kind, MAX_DIST), MARGIN_FOR.get(kind)
        text, used = [], []
        glyphs = segment(ink(rgb, kind in OUTLINED))
        for g in first_run(glyphs) if kind in OUTLINED else glyphs:
            c = "." if g.small else _match(g, temps, limit, margin)
            if c is None and typical and g.aspect > 1.4 * typical:
                # Probably several characters touching: try cutting it up.
                guess = round(g.aspect / typical)
                for k in sorted({max(2, guess), max(2, guess - 1), guess + 1}):
                    parts = split(g, k) or []
                    chars = ["." if p.small else _match(p, temps, limit, margin) for p in parts]
                    if parts and None not in chars:
                        text += chars
                        used += parts
                        break
                else:
                    text.append("?")
                    used.append(g)
                continue
            text.append(c or "?")
            used.append(g)
        if "?" in text and kind in ELIMINATE:
            text = self._by_elimination(kind, temps, text, used)
        return "".join(text), used

    def _by_elimination(self, kind, temps, text, glyphs):
        """When every digit but one has been taught, a new character the size and shape of a
        digit can only be that one: learn it rather than ask."""
        digits = {t.char for t in temps if t.char.isdigit()}
        missing = set("0123456789") - digits
        if len(missing) != 1:
            return text
        known = [g for g, c in zip(glyphs, text) if c.isdigit()]
        unknown = [g for g, c in zip(glyphs, text) if c == "?"]
        if not known:
            return text
        height = float(np.median([g.box[3] - g.box[1] for g in known]))
        wide = [g.aspect for g, c in zip(glyphs, text) if c.isdigit() and c != "1"]
        aspect = float(np.median(wide)) if wide else None
        for g in unknown:
            if abs((g.box[3] - g.box[1]) - height) > 0.15 * height:
                return text                     # not the size of a digit
            if aspect and not 0.6 * aspect <= g.aspect <= 1.6 * aspect:
                return text
            if distance(g, Template.from_glyph("?", unknown[0])) > 0.1:
                return text                     # two different new characters: can't tell
            if min(distance(g, t) for t in temps if t.char.isdigit()) < 0.12:
                return text                     # looks like a digit it knows, just not enough
        digit = missing.pop()
        with self.lock:
            self.templates.setdefault(kind, []).append(Template.from_glyph(digit, unknown[0]))
            self._save()
        return [digit if c == "?" else c for c in text]

    def learn(self, kind, rgb, typed, strict=False):
        """Teach from a box and what the player says it shows. Returns (ok, message).

        strict (when the app teaches itself): only from a box that splits cleanly into exactly
        the characters expected, all the height of a digit, so nothing stray gets learned."""
        glyphs = segment(ink(rgb, kind in OUTLINED))
        glyphs = [g for g in (first_run(glyphs) if kind in OUTLINED else glyphs) if not g.small]
        chars = [c for c in typed if not c.isspace() and c not in ",."]
        if not glyphs:
            return False, "No text found in the box."
        if strict:
            heights = [g.box[3] - g.box[1] for g in glyphs]
            mid = float(np.median(heights))
            if len(glyphs) != len(chars) or any(abs(h - mid) > 0.1 * mid for h in heights):
                return False, "Not clean enough to learn from."
        while len(glyphs) < len(chars):
            # Characters drawn touching each other: cut the widest until the count matches.
            i = max(range(len(glyphs)), key=lambda j: glyphs[j].aspect)
            parts = split(glyphs[i], 2)
            if not parts:
                break
            glyphs[i:i + 1] = parts
        if len(chars) != len(glyphs):
            return False, (f"I see {len(glyphs)} characters (not counting , and .) but you typed "
                           f"{len(chars)}. Check the box is tight around the number.")
        everything = self.all(kind)
        with self.lock:
            temps = self.templates.setdefault(kind, [])
            for g, c in zip(glyphs, chars):
                # Examples of other characters that look just like this one were mistaught.
                temps[:] = [t for t in temps if t.char == c or distance(g, t) > 0.02]
                if any(t.char == c and distance(g, t) < 0.04 for t in everything + temps):
                    continue                    # already known as it looks here
                same = [t for t in temps if t.char == c]
                if len(same) >= PER_CHAR:
                    temps.remove(same[0])
                temps.append(Template.from_glyph(c, g))
            self._save()
        return True, f"Learned it ({len(glyphs)} characters)."

    def forget(self, kind):
        with self.lock:
            self.templates.pop(kind, None)
            self._save()

    def _save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: [t.to_json() for t in v] for k, v in self.templates.items()}
            self.path.write_text(json.dumps(data), "utf-8")


# --------------------------------------------------------------------------- the app's fonts

def load_fonts(path):
    """The app's fonts: per kind, (char, shape at the game's own size, rel_h, rel_mid)."""
    data = json.loads(path.read_text("utf-8"))
    fonts = {}
    for kind, entries in data.items():
        for e in entries:
            h, w = e["shape"]
            bits = np.unpackbits(np.frombuffer(base64.b64decode(e["mask"]), np.uint8))
            fonts.setdefault(kind, []).append((e["char"], bits[: h * w].reshape(h, w).astype(bool),
                                               e["rel_h"], e["rel_mid"]))
    return fonts


def font_entry(char, base, rel_h, rel_mid):
    return {"char": char, "shape": list(base.shape), "rel_h": rel_h, "rel_mid": rel_mid,
            "mask": base64.b64encode(np.packbits(base).tobytes()).decode()}


def draw_template(char, base, rel_h, rel_mid, scale):
    """A character from the app's fonts as this screen shows it: every game pixel drawn as a
    scale x scale block (the game enlarges its UI without smoothing)."""
    h, w = base.shape
    k = round(scale)
    if abs(scale - k) < 0.01 and k >= 1:
        mask = np.kron(base, np.ones((k, k), bool))
    else:
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        mask = np.asarray(Image.fromarray(base.astype(np.uint8) * 255).resize(size, Image.NEAREST)) > 127
    img = Image.fromarray(mask.astype(np.uint8) * 255)
    bitmap = np.asarray(img.resize((NORM_W, NORM_H), Image.BILINEAR), np.float32) / 255
    return Template(char, bitmap, mask.shape[1] / mask.shape[0], rel_h, rel_mid, mask)


# --------------------------------------------------------------------------- what the text means

_EXP = re.compile(r"(\d[\d.]*)\D*?(\d+)\.(\d{1,2})%")


def parse_exp(text):
    """'38.849[61.02%]' (commas read as '.') -> (38849, 61.02), or None. Anything after the
    '%' (the bracket, the edge of the bar) doesn't matter; everything before it must be read."""
    if text and "%" in text:
        text = text[:text.index("%") + 1]
    if not text or "?" in text:
        return None
    m = _EXP.search(text)
    if not m:
        return None
    pct = float(f"{m.group(2)}.{m.group(3)}")
    return (int(m.group(1).replace(".", "")), pct) if pct <= 100 else None


def parse_number(text):
    """'1.234.567' -> 1234567, or None if anything in it wasn't recognised."""
    if not text or "?" in text:
        return None
    digits = text.replace(".", "")
    return int(digits) if digits.isdigit() else None


def parse_typed_number(text):
    """What the player typed: '1,234,567', '1 234 567' or '1234567'."""
    digits = re.sub(r"[\s,.]", "", text or "")
    return int(digits) if digits.isdigit() else None
