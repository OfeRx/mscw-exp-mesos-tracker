"""Sharing a session: as text to paste into Discord or WhatsApp, or as a picture of the stats.

Text is plain with a few emoji: Discord and WhatsApp mark bold differently (**x** and *x*), and
either one shows up as stray asterisks in the other."""
from __future__ import annotations

import ctypes
import io
from ctypes import wintypes
from datetime import datetime

from PIL import Image, ImageDraw

from . import fmt


def _hours(seconds):
    m = int(seconds or 0) // 60
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _when(started):
    if isinstance(started, str):
        started = datetime.fromisoformat(started)
    elif started is not None:
        started = datetime.fromtimestamp(started)
    return started.strftime("%d %b, %H:%M") if started else ""


def potions_line(s):
    used = [p for p in s["potions"] if p["used"]]
    if not used:
        return "none drunk"
    detail = ", ".join(f"{p['name']} ×{p['used']}" for p in sorted(used, key=lambda p: -p["cost"]))
    return f"{fmt.commas(s['potion_cost'])} mesos ({detail})"


def summary_text(s, live=False):
    """A session (Session.summary(), or a saved record) as a few lines to paste."""
    title = "🍁 MapleStory Classic grind" + (" (so far)" if live else "")
    lines = [f"{title} · {_hours(s['active_seconds'])}"]
    exp = f"⭐ EXP {fmt.short(s['exp_per_hour'])}/h"
    if s.get("pct_per_hour"):
        exp += f" ({s['pct_per_hour']:.1f}%/h)"
    if s.get("exp_per_hour_real"):
        exp += f", {fmt.short(s['exp_per_hour_real'])}/h real time"
    exp += f" · {fmt.commas(s['exp_gained'])} gained"
    if s["levels"]:
        exp += f" · +{s['levels']} level{'s' if s['levels'] > 1 else ''}"
    lines.append(exp)
    if s["mesos_start"] is not None:
        real = f", {fmt.short(s['net_per_hour_real'], sign=True)}/h real time" \
            if s.get("net_per_hour_real") is not None else ""
        lines.append(f"💰 Mesos {fmt.short(s['net_per_hour'], sign=True)}/h{real} · "
                     f"{fmt.short(s['net_mesos'], sign=True)} net")
    lines.append(f"🧪 Potions {potions_line(s)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- the picture

CARD_W = 520


def _changes(p):
    parts = [f"{p['used']} drunk"] if p["used"] else []
    parts += [f"+{p['added']} bought"] if p["added"] else []
    parts += [f"{p['removed']} put away"] if p.get("removed") else []
    return " · ".join(parts)


def _span(s):
    """'20 Oct · 21:30 – 23:06'"""
    start = s.get("started")
    if not start:
        return ""
    start = datetime.fromisoformat(start) if isinstance(start, str) else datetime.fromtimestamp(start)
    end = s.get("ended")
    end = datetime.fromisoformat(end) if isinstance(end, str) else datetime.fromtimestamp(end) if end else None
    return start.strftime("%d %b · %H:%M") + (end.strftime(" – %H:%M") if end else "")


def summary_card(s, live=False, icon=None):
    """A session as a picture in the overlay's look, for the summary window and to paste into a
    chat: the levels gained, EXP and mesos per hour, and what each potion cost. `icon(name)`
    gives an item's icon, when known. Drawn at twice the size (card.S), for a sharp paste."""
    from . import card
    from .card import (AMBER, BAR_FONT, EXP_WORD_FONT, FRAME, FRAME_HI, GOLD, GREEN, HEADER_BOTTOM,
                       HEADER_TOP, LABEL, LABEL_FONT, MUTED, PANEL_BOTTOM, PANEL_TOP, RED, S, SMALL_FONT,
                       TEXT_FONT, TITLE, TITLE_FONT, VALUE, VALUE_FONT, _coin, _panel, _text)
    W, pad = CARD_W, 16
    changed = sorted((p for p in s["potions"] if p["used"] or p["added"] or p.get("removed")),
                     key=lambda p: (-p["cost"], p["name"]))
    unchanged = [p["name"] for p in s["potions"] if p not in changed]
    has_mesos = s["mesos_start"] is not None
    header, hero, tile_h, section, row_h = 44, 64, 58, 32, 30
    h = header + hero + tile_h + section + (tile_h if has_mesos else 40)
    h += 10 + max(1, len(changed)) * row_h + (22 if unchanged else 0) + (34 if changed else 0) + 30

    img = Image.new("RGB", (W * S, h * S), (20, 15, 10))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (x0 * S, y0 * S, x1 * S, y1 * S)

    def divider(y):
        d.line(((pad + 4) * S, y * S, (W - pad - 4) * S, y * S), fill=(66, 51, 35), width=S)

    _panel(img, box(0, 0, W, h), 14 * S, PANEL_TOP, PANEL_BOTTOM, outline=FRAME, width=2 * S)
    d.rounded_rectangle(box(3, 3, W - 3, h - 3), 11 * S, outline=(70, 54, 36), width=S)

    # Header: the coin, the title, and when.
    _panel(img, box(4, 4, W - 4, header), 10 * S, HEADER_TOP, HEADER_BOTTOM)
    d.line((6 * S, header * S, (W - 6) * S, header * S), fill=FRAME_HI, width=S)
    _coin(d, 24 * S, 24 * S, 8 * S)
    _text(d, (40 * S, 24 * S), "SESSION SO FAR" if live else "SESSION SUMMARY", TITLE_FONT, TITLE, "lm")
    _text(d, ((W - pad) * S, 24 * S), _span(s), SMALL_FONT, LABEL, "rm")

    # The levels, and the EXP gained.
    y = header + 14
    x = pad
    start, end = s.get("level_start"), s.get("level_end")
    if end:
        if s["levels"] and start:
            x += card.level_badge(img, x, y, start, digit_color=((120, 104, 84), (84, 72, 58))) + 8
            ax, ay = x + 6, y + 18
            d.polygon([(ax * S, (ay - 7) * S), ((ax + 10) * S, ay * S), (ax * S, (ay + 7) * S)], fill=GOLD)
            x += 24
        x += card.level_badge(img, x, y, end) + 18
    gained = f"+{fmt.commas(s['exp_gained'])}" if s["exp_gained"] > 0 else fmt.commas(s["exp_gained"])
    _text(d, (x * S, (y + 18) * S), gained, VALUE_FONT, VALUE, "ls", stroke=1)
    gx = x * S + d.textlength(gained, font=VALUE_FONT) + 6 * S
    _text(d, (gx, (y + 18) * S), "EXP", EXP_WORD_FONT, (255, 240, 170), "ls", stroke=1)
    if s["levels"]:
        note, color = f"+{s['levels']} level{'s' if s['levels'] > 1 else ''}!", GREEN
    else:
        note, color = "gained this session", LABEL
    _text(d, (x * S, (y + 33) * S), note, BAR_FONT if s["levels"] else TEXT_FONT, color, "lm")
    y = header + hero

    # EXP per hour, both ways, and the time.
    divider(y)
    pct, pct_real = s.get("pct_per_hour"), s.get("pct_per_hour_real")
    card.stat_tiles(d, [
        ("EXP / h · grinding", fmt.short(s["exp_per_hour"]), None, f"{pct:.1f}%" if pct else ""),
        ("EXP / h · real time", fmt.short(s.get("exp_per_hour_real")), None,
         f"{pct_real:.1f}%" if pct_real else ""),
        ("Time grinding", _hours(s["active_seconds"]), None,
         f"of {_hours(s.get('real_seconds', s['total_seconds']))}")], pad, y, W - 2 * pad, tile_h)
    y += tile_h

    # Mesos.
    y += 6
    d.line((pad * S, y * S, (W - pad) * S, y * S), fill=FRAME, width=S)
    _coin(d, (pad + 10) * S, (y + 14) * S, 6 * S)
    _text(d, ((pad + 22) * S, (y + 14) * S), "MESOS & POTIONS", LABEL_FONT, TITLE, "lm")
    if has_mesos:
        wallet = f"{fmt.commas(s['mesos_start'])} → {fmt.commas(s['mesos_end'])}"
        _text(d, ((W - pad) * S, (y + 14) * S), wallet, SMALL_FONT, GOLD, "rm")
    y += section - 6
    if has_mesos:
        color = GOLD if s["net_mesos"] >= 0 else RED
        real = s.get("net_per_hour_real")
        card.stat_tiles(d, [
            ("Mesos / h · grinding", fmt.short(s["net_per_hour"], sign=True), color),
            ("Mesos / h · real time", fmt.short(real, sign=True) if real is not None else "—", color),
            ("Net mesos", fmt.short(s["net_mesos"], sign=True), color)], pad, y, W - 2 * pad, tile_h)
        y += tile_h
    else:
        _text(d, ((pad + 10) * S, (y + 20) * S), "Mesos weren't read: open your inventory during a session "
              "to count them.", TEXT_FONT, AMBER, "lm")
        y += 40

    # Each potion and food that changed, with its icon and what it cost.
    y += 10
    if not changed:
        _text(d, ((pad + 10) * S, (y + row_h / 2) * S), "No potions or food drunk.", TEXT_FONT, LABEL, "lm")
        y += row_h
    for i, p in enumerate(changed):
        if i % 2 == 0:
            _panel(img, box(pad, y, W - pad, y + row_h), 6 * S, (62, 47, 32), (56, 42, 29))
        pic = icon(p["name"]) if icon else None
        if pic is not None:
            k = 22 * S / max(pic.size)
            pic = pic.convert("RGBA").resize((max(1, round(pic.width * k)), max(1, round(pic.height * k))),
                                             Image.NEAREST)
            img.paste(pic, (round((pad + 19) * S - pic.width / 2), round((y + row_h / 2) * S - pic.height / 2)),
                      pic)
        cy = (y + row_h / 2) * S
        _text(d, ((pad + 38) * S, cy), p["name"], SMALL_FONT, VALUE, "lm")
        _text(d, ((pad + 210) * S, cy), _changes(p), TEXT_FONT, LABEL, "lm")
        cost = f"-{fmt.commas(p['cost'])}" if p["cost"] else "—"
        _text(d, ((W - pad - 10) * S, cy), cost, SMALL_FONT, RED if p["cost"] else MUTED, "rm")
        y += row_h
    if unchanged:
        line = "Unchanged: " + ", ".join(unchanged)
        while d.textlength(line, font=TEXT_FONT) > (W - 2 * pad - 20) * S:
            line = line[:line.rfind(",")] + ", …"
            if line.count(",") <= 1:
                break
        _text(d, ((pad + 10) * S, (y + 11) * S), line, TEXT_FONT, MUTED, "lm")
        y += 22
    if changed:
        divider(y + 6)
        _text(d, ((pad + 10) * S, (y + 22) * S), "POTION COST", LABEL_FONT, LABEL, "lm")
        total = f"-{fmt.commas(s['potion_cost'])} mesos" if s["potion_cost"] else "0"
        _text(d, ((W - pad - 10) * S, (y + 22) * S), total, BAR_FONT, RED if s["potion_cost"] else LABEL, "rm",
              stroke=1)
        y += 34

    _text(d, ((W - pad) * S, (h - 12) * S), "Maple Tracker", LABEL_FONT, MUTED, "rs")
    return img


# --------------------------------------------------------------------------- the clipboard

def copy_text(root, text):
    """Put text on the clipboard (through tkinter, which keeps it there while the app runs)."""
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32.GlobalAlloc.restype, _k32.GlobalAlloc.argtypes = wintypes.HGLOBAL, (wintypes.UINT, ctypes.c_size_t)
_k32.GlobalLock.restype, _k32.GlobalLock.argtypes = ctypes.c_void_p, (wintypes.HGLOBAL,)
_k32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
_k32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
_u32.OpenClipboard.argtypes = (wintypes.HWND,)
_u32.SetClipboardData.restype = wintypes.HANDLE
_u32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
CF_DIB, GMEM_MOVEABLE = 8, 0x0002


def dib_bytes(img):
    """A picture as a device-independent bitmap: a .bmp without its 14-byte file header."""
    out = io.BytesIO()
    img.convert("RGB").save(out, "BMP")
    return out.getvalue()[14:]


def copy_image(img):
    """Put a picture on the clipboard, for pasting with Ctrl+V. Returns whether it worked."""
    data = dib_bytes(img)
    handle = _k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    ptr = _k32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    _k32.GlobalUnlock(handle)
    for _ in range(10):                     # another program may have it open for a moment
        if _u32.OpenClipboard(None):
            break
        _k32.Sleep(20)
    else:
        _k32.GlobalFree(handle)
        return False
    try:
        _u32.EmptyClipboard()
        if not _u32.SetClipboardData(CF_DIB, handle):     # on success Windows owns the memory
            _k32.GlobalFree(handle)
            return False
        return True
    finally:
        _u32.CloseClipboard()
