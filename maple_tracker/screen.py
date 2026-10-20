"""Finding the game window and taking screenshots of parts of the screen.

Read-only on purpose: the game window is found by its window class (no handle to the game's
process is ever opened), and screenshots are ordinary desktop captures, the same kind Snipping
Tool or OBS's Display Capture take. Nothing is sent to the game."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import mss
import numpy as np

GAME_WINDOW_CLASS = "MapleStoryClass"

_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _api(fn, restype, *argtypes):
    fn.restype, fn.argtypes = restype, list(argtypes)
    return fn


_FindWindow = _api(_user32.FindWindowW, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_IsWindowVisible = _api(_user32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_IsIconic = _api(_user32.IsIconic, wintypes.BOOL, wintypes.HWND)
_GetClientRect = _api(_user32.GetClientRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_ClientToScreen = _api(_user32.ClientToScreen, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT))
_GetAncestor = _api(_user32.GetAncestor, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_GetWindowRect = _api(_user32.GetWindowRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_SetWindowDisplayAffinity = _api(_user32.SetWindowDisplayAffinity, wintypes.BOOL, wintypes.HWND, wintypes.DWORD)

WDA_EXCLUDEFROMCAPTURE = 0x11
GA_ROOT = 2


def make_dpi_aware():
    """Physical pixels everywhere, so tkinter, window positions and screenshots agree on
    scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass


def game_rect():
    """The game's drawing area on screen as (x, y, w, h), or None if the game isn't showing."""
    hwnd = _FindWindow(GAME_WINDOW_CLASS, None)
    if not hwnd or not _IsWindowVisible(hwnd) or _IsIconic(hwnd):
        return None
    r, pt = wintypes.RECT(), wintypes.POINT(0, 0)
    if not _GetClientRect(hwnd, ctypes.byref(r)) or not _ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    if r.right < 100 or r.bottom < 100:
        return None
    return pt.x, pt.y, r.right, r.bottom


def game_origin():
    """Top-left of the game's drawing area on screen, or None if the game isn't showing."""
    rect = game_rect()
    return rect[:2] if rect else None


def set_capture_hidden(widget, hidden):
    """Leave one of our windows out of screenshots, screen sharing and streams (Windows 10
    2004+), or put it back in. Shown is the default: our own reading doesn't need hiding, since
    it blacks our windows out of what it reads (blank_own)."""
    try:
        hwnd = _GetAncestor(widget.winfo_id(), GA_ROOT)
        return bool(_SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if hidden else 0))
    except Exception:
        return False


def window_rect(widget):
    """Where one of our windows is on screen, frame included: (x, y, w, h)."""
    hwnd = _GetAncestor(widget.winfo_id(), GA_ROOT)
    r = wintypes.RECT()
    if not _GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def blank_own(img, frame, rects):
    """A screenshot of `frame` (x, y, w, h on screen) with our own windows blacked out, so the
    overlay is never read as part of the game, even when it's on top of it."""
    if img is None or not rects:
        return img
    fx, fy = frame[:2]
    out = None
    for x, y, w, h in rects:
        x0, y0 = max(0, x - fx), max(0, y - fy)
        x1, y1 = min(img.shape[1], x + w - fx), min(img.shape[0], y + h - fy)
        if x1 > x0 and y1 > y0:
            out = img.copy() if out is None else out
            out[y0:y1, x0:x1] = 0
    return img if out is None else out


# --------------------------------------------------------------------------- boxes

def make_region(rect, origin):
    """A box the player drew (screen coordinates), stored relative to the game window when it
    was found, so moving the window doesn't break it."""
    x, y, w, h = rect
    if origin:
        return {"x": x - origin[0], "y": y - origin[1], "w": w, "h": h, "relative": True}
    return {"x": x, "y": y, "w": w, "h": h, "relative": False}


def region_rect(region, origin):
    """Screen rectangle for a stored box, or None when it can't be placed right now."""
    if not region:
        return None
    if region.get("relative"):
        if origin is None:
            return None
        return origin[0] + region["x"], origin[1] + region["y"], region["w"], region["h"]
    return region["x"], region["y"], region["w"], region["h"]


class Screen:
    """Screenshots of screen rectangles. One per thread (mss isn't shared across threads)."""

    def __init__(self):
        self.sct = mss.mss()

    def virtual(self):
        """The whole desktop across all monitors: (left, top, width, height)."""
        m = self.sct.monitors[0]
        return m["left"], m["top"], m["width"], m["height"]

    def frame_rect(self):
        """Where to look for the game: its window when it's found, else the main screen."""
        rect = game_rect()
        if rect:
            return rect, True
        m = self.sct.monitors[1]
        return (m["left"], m["top"], m["width"], m["height"]), False

    def grab(self, rect):
        """RGB pixels of a rectangle, clipped to the screens, or None if it's off screen."""
        x, y, w, h = rect
        vx, vy, vw, vh = self.virtual()
        x0, y0 = max(x, vx), max(y, vy)
        x1, y1 = min(x + w, vx + vw), min(y + h, vy + vh)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        shot = self.sct.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0})
        return np.ascontiguousarray(np.asarray(shot)[:, :, 2::-1])   # BGRA -> RGB

    def close(self):
        self.sct.close()
