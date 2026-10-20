"""The overlay drawn as one picture, in the look of the game's own windows: a brown and gold
frame, the level in orange number boxes, a green EXP bar, and the stats as big numbers.

Tk's own widgets can't do rounded, shaded, outlined art, so the whole card is drawn with Pillow
(at twice the size, then shrunk, for smooth edges) and shown in the window; clicks are matched
to the buttons by where they landed (render() says where everything is)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

KEY = (255, 0, 254)          # see-through: the window's corners outside the rounded frame
KEY_HEX = "#ff00fe"

S = 2                         # drawn at this many times the size, then shrunk
W = 480

# The gold theme, after the game's windows.
FRAME = (139, 104, 55)
FRAME_HI = (214, 172, 98)
PANEL_TOP, PANEL_BOTTOM = (54, 41, 29), (31, 24, 17)
HEADER_TOP, HEADER_BOTTOM = (86, 64, 41), (53, 40, 27)
TITLE = (244, 210, 135)
LABEL = (196, 172, 138)
VALUE = (252, 248, 240)
MUTED = (150, 132, 108)
GOLD = (255, 206, 92)
GREEN = (150, 232, 120)
RED = (255, 128, 112)
AMBER = (255, 196, 92)
TRACK = (22, 16, 11)
BAR_TOP, BAR_BOTTOM = (204, 250, 82), (106, 186, 20)
BOX_TOP, BOX_BOTTOM = (255, 186, 72), (226, 104, 18)
INK = (46, 26, 10)            # outlines around white numbers
BUTTON_TOP, BUTTON_BOTTOM = (92, 70, 47), (61, 46, 31)
PRIMARY_TOP, PRIMARY_BOTTOM = (255, 178, 64), (214, 98, 18)
STATE_COLORS = {"tracking": (120, 220, 110), "idle": (255, 196, 92), "paused": (255, 196, 92),
                "finishing": (255, 196, 92), "off": (150, 132, 108)}

FONTS = Path(r"C:\Windows\Fonts")


def _font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(str(FONTS / name), size * S)
        except OSError:
            continue
    return ImageFont.load_default(size * S)


TITLE_FONT = _font(["seguibl.ttf", "segoeuib.ttf"], 14)
LABEL_FONT = _font(["segoeuib.ttf"], 11)
VALUE_FONT = _font(["seguibl.ttf", "segoeuib.ttf"], 24)
SMALL_FONT = _font(["segoeuib.ttf"], 13)
TEXT_FONT = _font(["segoeui.ttf"], 13)
BAR_FONT = _font(["segoeuib.ttf"], 15)
EXP_WORD_FONT = _font(["seguibli.ttf", "segoeuiz.ttf", "segoeuib.ttf"], 15)
DIGIT_FONT = _font(["seguibl.ttf", "segoeuib.ttf"], 21)
LV_FONT = _font(["seguibli.ttf", "segoeuiz.ttf", "segoeuib.ttf"], 15)
BUTTON_FONT = _font(["segoeuib.ttf"], 13)


@dataclass
class View:
    """What the card shows. Text is ready to draw; colours come from the theme above."""
    state: str = "off"                    # tracking, idle, paused, finishing, off
    state_text: str = "Not tracking"
    clock: str = ""                       # active time, shown in the header
    level: int | None = None
    exp: int | None = None
    pct: float | None = None
    tiles: list = field(default_factory=list)       # (label, value, colour[, note]) x 6
    mesos: int | None = None              # current meso count
    meso_tiles: list = field(default_factory=list)  # (label, value, colour[, note]) x 3
    meso_extra: tuple | None = None       # (text, colour) beside the meso count: the potion bill
    meso_hint: tuple | None = None        # (title, line) in place of the meso numbers, when unread
    details: list = field(default_factory=list)     # lines about each potion
    expanded: bool = False
    message: str = ""
    message_clickable: bool = False
    bar_note: str = "Looking for the EXP bar…"   # in the EXP bar while there's no reading
    buttons: list = field(default_factory=list)     # (name, text, primary, enabled)
    hover: str | None = None
    pressed: str | None = None
    sections: tuple = ("bar", "exp", "exp2", "mesos", "buttons")   # which parts to show


def _grad(size, top, bottom):
    w, h = size
    t = np.linspace(0, 1, max(1, h))[:, None, None]
    rows = (np.array(top)[None, None, :] * (1 - t) + np.array(bottom)[None, None, :] * t)
    return Image.fromarray(np.repeat(rows, max(1, w), axis=1).astype(np.uint8), "RGB")


def _panel(img, box, radius, top, bottom, outline=None, width=0):
    """A rounded rectangle filled top to bottom with a gradient, at drawing scale."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    img.paste(_grad((w, h), top, bottom), (x0, y0), mask)
    if outline:
        ImageDraw.Draw(img).rounded_rectangle(box, radius, outline=outline, width=width)


def _text(d, xy, text, font, fill, anchor="la", stroke=0):
    d.text(xy, text, font=font, fill=fill, anchor=anchor,
           stroke_width=stroke * S, stroke_fill=INK if stroke else None)


def _coin(d, cx, cy, r):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(240, 176, 48), outline=(122, 76, 16), width=S)
    d.ellipse((cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55), outline=(255, 226, 140), width=S)


def level_badge(img, x, y, level, digit_color=None):
    """The game's level badge, "LV." and orange number boxes, 36 high at (x, y) (drawing size
    / S). Grey "??" when the level isn't known. Returns its width."""
    d = ImageDraw.Draw(img)
    digits = str(level) if level else "??"
    w = 44 + 24 * len(digits)
    _panel(img, (x * S, y * S, (x + w) * S, (y + 36) * S), 8 * S, (30, 22, 15), (18, 13, 9),
           outline=(98, 74, 46), width=S)
    _text(d, ((x + 8) * S, (y + 18) * S), "LV.", LV_FONT, VALUE, "lm", stroke=1)
    for i, ch in enumerate(digits):
        x0 = x + 38 + 24 * i
        top, bottom = digit_color or ((BOX_TOP, BOX_BOTTOM) if level else ((120, 104, 84), (84, 72, 58)))
        _panel(img, (x0 * S, (y + 5) * S, (x0 + 21) * S, (y + 31) * S), 5 * S, top, bottom,
               outline=(120, 56, 8), width=S)
        _text(d, ((x0 + 10.5) * S, (y + 18) * S), ch, DIGIT_FONT, VALUE, "mm", stroke=1)
    return w


def stat_tiles(d, row, x, y, width, height=58):
    """A row of stats side by side: a small label over a big number (and a note after it)."""
    col_w = width / max(1, len(row))
    for i, (label, value, color, *note) in enumerate(row):
        x0 = x + i * col_w
        if i:
            d.line((x0 * S, (y + 10) * S, x0 * S, (y + height - 8) * S), fill=(78, 60, 40), width=S)
        _text(d, ((x0 + 10) * S, (y + 8) * S), label.upper(), LABEL_FONT, LABEL)
        base = (y + 48) * S
        _text(d, ((x0 + 10) * S, base), value, VALUE_FONT, color or VALUE, "ls", stroke=1)
        if note and note[0]:
            nx = (x0 + 10) * S + d.textlength(value, font=VALUE_FONT) + 5 * S
            _text(d, (nx, base), note[0], SMALL_FONT, LABEL, "ls")


def _wrap(d, text, font, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and d.textlength(candidate, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + ([line] if line else [])


SECTIONS = ("bar", "exp", "exp2", "mesos", "buttons")   # the parts that can be hidden


def render(v: View, zoom=1.0):
    """(picture, {name: (x0, y0, x1, y1)}) at screen size: the card, and where its buttons
    and other clickable parts are. `zoom` sizes the whole card (0.6 to 1.5); parts not in
    v.sections are left out, and without the buttons a Start/Stop control sits in the header."""
    pad = 12
    show = set(v.sections)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    message_lines = _wrap(measure, v.message, TEXT_FONT, (W - 2 * pad - 8) * S) if v.message else []
    detail_lines = v.details if v.expanded and "mesos" in show else []
    main = next((b for b in v.buttons if b[0] == "main"), None)

    # Heights, top to bottom.
    header, level_row, tile_row, meso_head, button_row = 40, 50, 58, 26, 44
    h = header + (level_row if "bar" in show else 6)
    h += tile_row * (("exp" in show) + ("exp2" in show))
    if "mesos" in show:
        h += 8 + meso_head + tile_row + 4 + (22 if v.details else 0)
        h += len(detail_lines) * 18 + (6 if detail_lines else 0)
    h += len(message_lines) * 18 + (8 if message_lines else 0)
    h += button_row if "buttons" in show else 6

    img = Image.new("RGB", (W * S, h * S), KEY)
    d = ImageDraw.Draw(img)
    hits = {}

    def box(x0, y0, x1, y1):
        return (x0 * S, y0 * S, x1 * S, y1 * S)

    def button(name, text, primary, enabled, b):
        top, bottom = (PRIMARY_TOP, PRIMARY_BOTTOM) if primary else (BUTTON_TOP, BUTTON_BOTTOM)
        if not enabled:
            top, bottom = (58, 46, 33), (46, 36, 26)
        elif v.pressed == name:
            top, bottom = bottom, top
        elif v.hover == name:
            top = tuple(min(255, c + 22) for c in top)
        _panel(img, box(*b), 8 * S, top, bottom, outline=(150, 112, 60) if enabled else (78, 60, 40), width=S)
        color = VALUE if enabled else MUTED
        _text(d, ((b[0] + b[2]) / 2 * S, (b[1] + b[3]) / 2 * S), text, BUTTON_FONT, color, "mm",
              stroke=1 if enabled and primary else 0)
        if enabled:
            hits[name] = b

    # Frame and panel.
    _panel(img, box(0, 0, W, h), 14 * S, PANEL_TOP, PANEL_BOTTOM, outline=FRAME, width=2 * S)
    d.rounded_rectangle(box(3, 3, W - 3, h - 3), 11 * S, outline=(70, 54, 36), width=S)

    # Header: coin, title, state, close (and Start/Stop when the buttons are hidden).
    _panel(img, box(4, 4, W - 4, header), 10 * S, HEADER_TOP, HEADER_BOTTOM)
    d.line((6 * S, header * S, (W - 6) * S, header * S), fill=FRAME_HI, width=S)
    _coin(d, 24 * S, 22 * S, 8 * S)
    _text(d, (40 * S, 22 * S), "MAPLE TRACKER", TITLE_FONT, TITLE, "lm")
    close = (W - 34, 9, W - 10, 33)
    hits["close"] = close
    cx, cy = (close[0] + close[2]) / 2, (close[1] + close[3]) / 2
    xcol = VALUE if v.hover == "close" else LABEL
    for dx in (-5, 5):
        d.line(((cx - 5) * S, (cy - dx) * S, (cx + 5) * S, (cy + dx) * S), fill=xcol, width=2 * S)
    right = W - 42
    if main and "buttons" not in show:
        bw = measure.textlength(main[1], font=BUTTON_FONT) / S + 20
        button(*main, (int(right - bw), 9, int(right), 33))
        right -= bw + 10
    state_color = STATE_COLORS.get(v.state, MUTED)
    if v.clock:
        _text(d, (right * S, 22 * S), v.clock, SMALL_FONT, VALUE, "rm")
        right -= measure.textlength(v.clock, font=SMALL_FONT) / S + 12
    _text(d, (right * S, 22 * S), v.state_text, SMALL_FONT, state_color, "rm")
    dot_x = right - measure.textlength(v.state_text, font=SMALL_FONT) / S - 10
    d.ellipse(((dot_x - 4) * S, 18 * S, (dot_x + 4) * S, 26 * S), fill=state_color)

    # Level badge and EXP bar.
    if "bar" in show:
        y = header + 8
        badge_w = level_badge(img, pad, y, v.level)
        bx0, bx1 = pad + badge_w + 10, W - pad
        _panel(img, box(bx0, y + 3, bx1, y + 33), 8 * S, (12, 9, 6), TRACK, outline=(98, 74, 46), width=S)
        if v.pct is not None:
            fill_w = max(0, min(1, v.pct / 100)) * (bx1 - bx0 - 6)
            if fill_w >= 4:
                _panel(img, box(bx0 + 3, y + 6, int(bx0 + 3 + fill_w), y + 30), 6 * S, BAR_TOP, BAR_BOTTOM)
                d.line(((bx0 + 7) * S, (y + 9) * S, (bx0 + fill_w - 2) * S, (y + 9) * S),
                       fill=(236, 255, 180), width=S)
        if v.exp is not None:
            number = f"{v.exp:,}" + (f" [{v.pct:.2f}%]" if v.pct is not None else "")
            total_w = measure.textlength("EXP ", font=EXP_WORD_FONT) + measure.textlength(number, font=BAR_FONT)
            tx = ((bx0 + bx1) * S - total_w) / 2
            _text(d, (tx, (y + 18) * S), "EXP", EXP_WORD_FONT, (255, 240, 170), "lm", stroke=1)
            _text(d, (tx + measure.textlength("EXP ", font=EXP_WORD_FONT), (y + 18) * S), number,
                  BAR_FONT, VALUE, "lm", stroke=1)
        else:
            _text(d, ((bx0 + bx1) / 2 * S, (y + 18) * S), v.bar_note, SMALL_FONT, MUTED, "mm")
        y = header + level_row
    else:
        y = header + 6

    def tiles(row, y0):
        stat_tiles(d, row, pad, y0, W - 2 * pad, tile_row)

    # EXP tiles: up to two rows of three.
    first = True
    for name, row in (("exp", v.tiles[:3]), ("exp2", v.tiles[3:6])):
        if name not in show:
            continue
        if "bar" in show or not first:
            d.line(((pad + 8) * S, y * S, (W - pad - 8) * S, y * S), fill=(66, 51, 35), width=S)
        tiles(row, y)
        y += tile_row
        first = False

    # Mesos and potions.
    if "mesos" in show:
        y += 8
        d.line((pad * S, y * S, (W - pad) * S, y * S), fill=FRAME, width=S)
        _coin(d, (pad + 10) * S, (y + 13) * S, 6 * S)
        _text(d, ((pad + 22) * S, (y + 13) * S), "MESOS & POTIONS", LABEL_FONT, TITLE, "lm")
        right = W - pad
        if v.mesos is not None:
            count = f"{v.mesos:,}"
            _text(d, (right * S, (y + 13) * S), count, SMALL_FONT, GOLD, "rm", stroke=1)
            right -= measure.textlength(count, font=SMALL_FONT) / S + 14
        if v.meso_extra:
            _text(d, (right * S, (y + 13) * S), v.meso_extra[0], SMALL_FONT, v.meso_extra[1], "rm")
        y += meso_head
        if v.meso_hint:
            # In place of the empty numbers: what to do to fill them in.
            _panel(img, box(pad + 4, y + 6, W - pad - 4, y + tile_row - 4), 8 * S, (66, 48, 24), (44, 32, 18),
                   outline=(150, 110, 50), width=S)
            kx, ky = pad + 16, y + tile_row // 2 + 1
            _panel(img, box(kx, ky - 14, kx + 28, ky + 14), 6 * S, (250, 240, 220), (196, 180, 150),
                   outline=(90, 66, 36), width=S)
            _text(d, ((kx + 14) * S, ky * S), "I", BAR_FONT, INK, "mm")
            title, rest = v.meso_hint
            _text(d, ((kx + 40) * S, (ky - 9) * S), title, BUTTON_FONT, AMBER, "lm")
            _text(d, ((kx + 40) * S, (ky + 9) * S), rest, TEXT_FONT, LABEL, "lm")
        else:
            tiles(v.meso_tiles[:3], y)
        y += tile_row + 4

        # Potion details, folded away until asked for.
        if v.details:
            hits["details"] = (pad, y, W - pad, y + 20)
            color = VALUE if v.hover == "details" else LABEL
            ax, ay = (pad + 8) * S, (y + 10) * S
            r = 4 * S
            arrow = [(ax - r, ay - r // 2), (ax + r, ay - r // 2), (ax, ay + r)] if v.expanded else \
                [(ax - r // 2, ay - r), (ax - r // 2, ay + r), (ax + r, ay)]
            d.polygon(arrow, fill=color)
            _text(d, ((pad + 18) * S, (y + 10) * S), "Potion and food counts", SMALL_FONT, color, "lm")
            y += 22
            for line in detail_lines:
                _text(d, ((pad + 18) * S, (y + 9) * S), line, TEXT_FONT, LABEL, "lm")
                y += 18
            if detail_lines:
                y += 6

    # A message, if there's something to say.
    if message_lines:
        y0 = y
        for line in message_lines:
            _text(d, ((pad + 4) * S, (y + 9) * S), line, TEXT_FONT, AMBER, "lm")
            y += 18
        if v.message_clickable:
            hits["message"] = (pad, y0, W - pad, y)
        y += 8

    # Buttons.
    if "buttons" in show:
        n = len(v.buttons)
        gap = 6
        bw = (W - 2 * pad - gap * (n - 1)) / max(1, n)
        for i, (name, text, primary, enabled) in enumerate(v.buttons):
            x0 = pad + i * (bw + gap)
            button(name, text, primary, enabled, (int(x0), y + 4, int(x0 + bw), y + 34))

    # Down to screen size, at the chosen zoom.
    zw, zh = max(1, round(W * zoom)), max(1, round(h * zoom))
    small = img.resize((zw, zh), Image.LANCZOS)
    # Corners outside the frame: exactly the see-through colour, with no blended edge.
    outside = Image.new("L", (zw, zh), 0)
    ImageDraw.Draw(outside).rounded_rectangle((0, 0, zw - 1, zh - 1), max(4, round(14 * zoom)), fill=255)
    small.paste(Image.new("RGB", (zw, zh), KEY), (0, 0), Image.eval(outside, lambda a: 255 - a))
    hits = {name: tuple(round(c * zoom) for c in b) for name, b in hits.items()}
    return small, hits


def hit(hits, x, y):
    """The name of what's at (x, y) on the card, or None."""
    for name, (x0, y0, x1, y1) in hits.items():
        if x0 <= x < x1 and y0 <= y < y1:
            return name
    return None
