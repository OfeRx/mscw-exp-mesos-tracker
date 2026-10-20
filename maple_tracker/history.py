"""Past sessions, as a picture in the overlay's look: the best runs, then one row per session,
newest first."""
from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw

from . import card, fmt
from .card import (FRAME, FRAME_HI, GOLD, HEADER_BOTTOM, HEADER_TOP, LABEL, LABEL_FONT, MUTED, PANEL_BOTTOM,
                   PANEL_TOP, RED, S, SMALL_FONT, TEXT_FONT, TITLE, TITLE_FONT, VALUE, _coin, _panel, _text)
from .share import _hours

W = 600
SHOWN = 150                 # the newest this many: a picture of thousands would be huge
ROW = 32
SHORT = 5 * 60              # shorter sessions are drawn dimmed
BEST_FROM = 10 * 60         # and only ones at least this long count as a best


def _date(s):
    started = s.get("started")
    if not started:
        return "—"
    when = datetime.fromisoformat(started) if isinstance(started, str) else datetime.fromtimestamp(started)
    return when.strftime("%d %b  %H:%M")


def _levels(s):
    start, end = s.get("level_start"), s.get("level_end")
    if end and s["levels"] and start:
        return f"{start} → {end}"
    if end:
        return str(end)
    return f"+{s['levels']}" if s["levels"] else "—"


def best(records, key):
    """The record with the highest value for key, among sessions long enough to mean something
    (and with mesos read, for a meso rate), or None."""
    have = [r for r in records if r.get(key) is not None and r["active_seconds"] >= BEST_FROM
            and (r.get("mesos_start") is not None or not key.startswith("net"))]
    return max(have, key=lambda r: r[key], default=None)


def render(records):
    """(picture at card.S times the size, [(y0, y1, record)] for each row at screen size)."""
    pad = 16
    records = list(reversed(records))[:SHOWN]
    header, tiles_h, head_row = 44, 58, 28
    h = header + 8 + tiles_h + 10 + head_row + max(1, len(records)) * ROW + 34
    img = Image.new("RGB", (W * S, h * S), (20, 15, 10))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (x0 * S, y0 * S, x1 * S, y1 * S)

    _panel(img, box(0, 0, W, h), 14 * S, PANEL_TOP, PANEL_BOTTOM, outline=FRAME, width=2 * S)
    d.rounded_rectangle(box(3, 3, W - 3, h - 3), 11 * S, outline=(70, 54, 36), width=S)
    _panel(img, box(4, 4, W - 4, header), 10 * S, HEADER_TOP, HEADER_BOTTOM)
    d.line((6 * S, header * S, (W - 6) * S, header * S), fill=FRAME_HI, width=S)
    _coin(d, 24 * S, 24 * S, 8 * S)
    _text(d, (40 * S, 24 * S), "SESSION HISTORY", TITLE_FONT, TITLE, "lm")
    n = len(records)
    _text(d, ((W - pad) * S, 24 * S), f"{n} session{'s' if n != 1 else ''}", SMALL_FONT, LABEL, "rm")

    # The best runs, and the time spent in all.
    y = header + 8
    top_exp, top_mesos = best(records, "exp_per_hour"), best(records, "net_per_hour")
    card.stat_tiles(d, [
        ("Best EXP / h", fmt.short(top_exp["exp_per_hour"]) if top_exp else "—", None,
         _date(top_exp)[:6] if top_exp else ""),
        ("Best mesos / h", fmt.short(top_mesos["net_per_hour"], sign=True) if top_mesos else "—", GOLD,
         _date(top_mesos)[:6] if top_mesos else ""),
        ("Time grinding", _hours(sum(r["active_seconds"] for r in records)), None, "in all")],
        pad, y, W - 2 * pad, tiles_h)
    y += tiles_h + 10

    cols = [(pad + 10, "Date", "l"), (pad + 140, "Length", "l"), (pad + 220, "Level", "l"),
            (pad + 300, "EXP / h", "l"), (W - pad - 110, "Mesos / h", "r"), (W - pad - 10, "Net", "r")]
    d.line((pad * S, y * S, (W - pad) * S, y * S), fill=FRAME, width=S)
    for x, name, align in cols:
        _text(d, (x * S, (y + head_row / 2) * S), name.upper(), LABEL_FONT, LABEL, align + "m")
    y += head_row

    rows = []
    if not records:
        _text(d, ((pad + 10) * S, (y + ROW / 2) * S), "No sessions yet: press Start, grind a while, then Stop.",
              TEXT_FONT, LABEL, "lm")
    for i, r in enumerate(records):
        if i % 2 == 0:
            _panel(img, box(pad, y, W - pad, y + ROW), 6 * S, (62, 47, 32), (56, 42, 29))
        cy = (y + ROW / 2) * S
        has_mesos = r.get("mesos_start") is not None
        exp_rate = fmt.short(r["exp_per_hour"])
        cells = [_date(r), _hours(r["active_seconds"]), _levels(r), exp_rate,
                 fmt.short(r["net_per_hour"], sign=True) if has_mesos else "—",
                 fmt.short(r["net_mesos"], sign=True) if has_mesos else "—"]
        for j, ((x, _, align), text) in enumerate(zip(cols, cells)):
            color = VALUE
            if j == 3 and r is top_exp:
                color = GOLD
            elif j >= 4:
                color = MUTED if not has_mesos else GOLD if r["net_mesos"] >= 0 else RED
            if r["active_seconds"] < SHORT:
                color = MUTED
            _text(d, (x * S, cy), text, SMALL_FONT, color, align + "m")
        if r.get("pct_per_hour"):
            px = (cols[3][0]) * S + d.textlength(exp_rate, font=SMALL_FONT) + 5 * S
            _text(d, (px, cy), f"{r['pct_per_hour']:.1f}%", TEXT_FONT, LABEL, "lm")
        rows.append((y, y + ROW, r))
        y += ROW

    if records:
        _text(d, ((pad + 10) * S, (h - 16) * S), "Click a session to see it in full, right-click to delete it",
              TEXT_FONT, MUTED, "lm")
    return img, rows
