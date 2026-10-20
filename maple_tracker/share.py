"""Sharing a session: as text to paste into Discord or WhatsApp, or as a picture of the stats.

Text is plain with a few emoji: Discord and WhatsApp mark bold differently (**x** and *x*), and
either one shows up as stray asterisks in the other."""
from __future__ import annotations

import ctypes
import io
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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

BG, PANEL, FG, MUTED = (31, 24, 17), (54, 41, 29), (252, 248, 240), (196, 172, 138)
GOLD, GREEN, BLUE, RED = (255, 206, 92), (150, 232, 120), (252, 248, 240), (255, 128, 112)
FONTS = Path(r"C:\Windows\Fonts")


def _font(name, size):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def summary_card(s, live=False):
    """The session's stats as a picture, to paste into a chat."""
    w, pad = 640, 28
    title, big, small = _font("seguibl.ttf", 26), _font("seguisb.ttf", 30), _font("segoeui.ttf", 17)
    label = _font("segoeuib.ttf", 15)
    tiles = [("EXP / HOUR", fmt.short(s["exp_per_hour"]), BLUE,
              f"{fmt.short(s['exp_per_hour_real'])}/h in real time" if s.get("exp_per_hour_real")
              else f"{s['pct_per_hour']:.1f}% of a level" if s.get("pct_per_hour") else ""),
             ("EXP GAINED", fmt.commas(s["exp_gained"]), BLUE,
              f"+{s['levels']} level{'s' if s['levels'] > 1 else ''}" if s["levels"] else "")]
    if s["mesos_start"] is not None:
        real = s.get("net_per_hour_real")
        tiles += [("MESOS / HOUR", fmt.short(s["net_per_hour"], sign=True), GOLD,
                   f"{fmt.short(real, sign=True)}/h in real time" if real is not None else "net, after potions"),
                  ("MESOS NET", fmt.short(s["net_mesos"], sign=True), GOLD,
                   f"{fmt.short(s['mesos_delta'], sign=True)} in your wallet")]
    rows = (len(tiles) + 1) // 2
    tile_h, gap = 104, 14
    h = pad + 40 + 26 + rows * (tile_h + gap) + 70 + pad
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    # A coin by the title, like the overlay's header.
    cy, r = pad + 17, 11
    d.ellipse((pad, cy - r, pad + 2 * r, cy + r), fill=(240, 176, 48), outline=(122, 76, 16), width=2)
    d.ellipse((pad + 5, cy - r + 5, pad + 2 * r - 5, cy + r - 5), outline=(255, 226, 140), width=2)
    d.text((pad + 2 * r + 10, pad), "MapleStory Classic grind" + (" (so far)" if live else ""),
           font=title, fill=(244, 210, 135))
    d.text((pad, pad + 40), f"{_when(s.get('started'))}  ·  {_hours(s['active_seconds'])} grinding",
           font=small, fill=MUTED)
    y = pad + 40 + 34
    tw = (w - 2 * pad - gap) // 2
    for i, (name, value, color, note) in enumerate(tiles):
        x = pad + (i % 2) * (tw + gap)
        ty = y + (i // 2) * (tile_h + gap)
        d.rounded_rectangle((x, ty, x + tw, ty + tile_h), 12, fill=PANEL)
        d.text((x + 16, ty + 12), name, font=label, fill=MUTED)
        d.text((x + 16, ty + 32), value, font=big, fill=color)
        if note:
            d.text((x + 16, ty + 74), note, font=small, fill=MUTED)
    y += rows * (tile_h + gap) + 4
    d.text((pad, y), "POTIONS", font=label, fill=MUTED)
    lines = _wrap(d, potions_line(s), small, w - 2 * pad)
    for i, line in enumerate(lines):
        d.text((pad, y + 22 + i * 22), line, font=small, fill=RED if s["potion_cost"] else FG)
    bottom = y + 22 + len(lines) * 22 + 30
    if bottom > h:                          # a long potion list: make room for it
        img = img.crop((0, 0, w, bottom))
        img.paste(BG, (0, h, w, bottom))
        d = ImageDraw.Draw(img)
        h = bottom
    d.text((w - pad, h - 12), "Maple Tracker", font=label, fill=MUTED, anchor="rs")
    # The overlay's gold frame.
    d.rectangle((0, 0, w - 1, h - 1), outline=(139, 104, 55), width=3)
    d.rectangle((4, 4, w - 5, h - 5), outline=(70, 54, 36), width=1)
    return img


def _wrap(d, text, font, width):
    """Split text into lines that fit, breaking after commas."""
    lines, line = [], ""
    for part in text.split(", "):
        candidate = f"{line}, {part}" if line else part
        if line and d.textlength(candidate, font=font) > width:
            lines.append(line + ",")
            line = part
        else:
            line = candidate
    return lines + [line]


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
