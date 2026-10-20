"""The overlay: a small always-on-top window with the live rates, plus the reading thread."""
from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from PIL import Image, ImageTk

from . import card, config, fmt, itemdata, screen, share
from .dialogs import FONT, ManualSetup, PricesDialog, RegionSelector, SummaryWindow
from .glyphs import GlyphStore, parse_exp, parse_number
from .items import (INVENTORY, QUICKSLOT, ItemLibrary, Spot, combine, read_count,
                    teach_counts)
from .locate import EXP_TEXT, MESOS_TEXT, Locator, game_px, gray
from .screen import Screen, region_rect
from .tracker import PotionState, Session, Stable, level_of

LOST_AFTER = 15        # seconds without finding the EXP bar before offering to set it up by hand


def crop(img, rect):
    x, y, w, h = rect
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    return img[y0:y1, x0:x1] if x1 - x0 >= 4 and y1 - y0 >= 4 else None


class Reader(threading.Thread):
    """Screenshots the game about once a second, finds the numbers and queues what it read."""

    def __init__(self, store, locator, jobs, out, interval=1.0):
        super().__init__(daemon=True)
        self.store, self.locator, self.jobs, self.out = store, locator, jobs, out
        self.interval = interval
        self.stopped = threading.Event()

    def run(self):
        sc = Screen()
        tick = 0
        while not self.stopped.is_set():
            t0 = time.monotonic()
            try:
                self.out.put(self.read_once(sc, with_mesos=tick % 2 == 0))
            except Exception as e:                      # keep reading; show it on the overlay
                self.out.put({"t": time.time(), "error": f"{type(e).__name__}: {e}"})
            tick += 1
            self.stopped.wait(max(0.05, self.interval - (time.monotonic() - t0)))
        sc.close()

    def read_once(self, sc, with_mesos):
        jobs = self.jobs()
        rect, game = sc.frame_rect()
        res = {"t": time.time(), "game": game, "frame": rect}
        img = sc.grab(rect)
        if img is None:
            return res
        g = gray(img)
        label_ = self.locator.find_exp(g)
        res["found"] = label_ is not None
        if label_:
            self.store.set_scale(game_px(label_.scale))     # draw the fonts at this screen's size
        manual = jobs["manual"]
        origin = rect[:2] if game else None
        if label_:
            res["exp"] = self._read("exp", crop(img, label_.rect(EXP_TEXT)))
        elif manual.get("exp"):
            res["exp"] = self._read_screen(sc, "exp", manual["exp"], origin)
        if with_mesos:
            m = self.locator.find_mesos(g) if label_ else None
            if m:
                res["mesos"] = self._read("mesos", crop(img, m.rect(MESOS_TEXT)))
            elif manual.get("mesos"):
                res["mesos"] = self._read_screen(sc, "mesos", manual["mesos"], origin)
            else:
                res["mesos"] = None                     # inventory closed
        return res

    def _read_screen(self, sc, kind, region, origin):
        r = region_rect(region, origin)
        return self._read(kind, sc.grab(r)) if r else None

    def _read(self, kind, img):
        if img is None:
            return None
        text, glyphs = self.store.read(kind, img)
        value = parse_exp(text) if kind == "exp" else parse_number(text)
        before = text[:text.index("%")] if kind == "exp" and "%" in text else text
        return {"value": value, "text": text, "glyphs": glyphs,
                "unknown": value is None and "?" in before, "img": img}


class ItemScanner(threading.Thread):
    """Every couple of seconds: finds the potions and food on the quickslot (and every stack in
    the inventory while it's open) by their icons, and reads how many there are. Slower than
    reading EXP, so it has its own thread."""

    QUICKSLOT_EVERY = 20        # seconds between looking again for what's on the quickslot
    INVENTORY_EVERY = 4

    def __init__(self, store, library, out, interval=2.0):
        super().__init__(daemon=True)
        self.store, self.library, self.out, self.interval = store, library, out, interval
        self.stopped = threading.Event()
        self.wake = threading.Event()    # set to scan now rather than at the next interval
        self.locator = Locator()
        self.quick = []                 # (item, place relative to the EXP label)
        self.quick_at = self.inventory_at = -1e9
        self.quick_failed = False

    def recheck(self):
        """Look at everything again on the next scan, and right away."""
        self.quick_at = self.inventory_at = -1e9
        self.wake.set()

    def run(self):
        sc = Screen()
        while not self.stopped.is_set():
            t0 = time.monotonic()
            self.wake.clear()
            try:
                self.out.put(self.scan_once(sc))
            except Exception as e:
                self.out.put({"t": time.time(), "error": f"{type(e).__name__}: {e}"})
            self.wake.wait(max(0.1, self.interval - (time.monotonic() - t0)))
        sc.close()

    def scan_once(self, sc):
        out = {"t": time.time(), "quick": {}, "inventory": None, "unread": [], "read": [],
               "inventory_open": False}
        rect, _ = sc.frame_rect()
        img = sc.grab(rect)
        if img is None:
            return out
        g = gray(img)
        loc = self.locator
        label_ = loc.find_exp(g)
        if not label_:
            return out
        now, scale_px = time.monotonic(), game_px(label_.scale)
        self.store.set_scale(scale_px)
        if self.quick_failed or now - self.quick_at > self.QUICKSLOT_EVERY:
            spots = self.library.scan(img, label_.rect(QUICKSLOT), scale_px)
            self.quick = [(s.item, loc.to_exp(s.box)) for s in spots]
            self.quick_at = now
        self.quick_failed = False
        quick = {}
        for item, anchor in self.quick:
            count = read_count(img, Spot(item, loc.from_exp(anchor), 1.0), label_.scale, self.store)
            if count is None:
                self.quick_failed = True            # no count where it was: look again next time
            else:
                quick[item.name] = count
        mesos = loc.find_mesos(g)
        out["inventory_open"] = mesos is not None
        unread_quick = any(c.value is None for c in quick.values())
        if mesos and (unread_quick or now - self.inventory_at > self.INVENTORY_EVERY):
            self.inventory_at = now
            stacks = defaultdict(list)
            for spot in self.library.scan(img, mesos.rect(INVENTORY), scale_px):
                count = read_count(img, spot, label_.scale, self.store)
                if count is not None:
                    stacks[spot.item.name].append(count)
            # The quickslot shows each item's inventory total: digits it couldn't read on one
            # side are learned from the other, then read again.
            for name in teach_counts(self.store, quick, stacks):
                for count in [quick.get(name), *stacks[name]]:
                    if count is not None and count.value is None:
                        count.text, _ = self.store.read("potion", count.img)
                        count.value = parse_number(count.text)
            if not stacks:
                # Open on another tab (Etc, Equip...): that says nothing about potions, it
                # doesn't mean there are none.
                out["other_tab"] = True
            else:
                # A stack whose count still can't be read makes that item's total unknown.
                out["inventory"] = {n: sum(c.value for c in cs) for n, cs in stacks.items()
                                    if all(c.value is not None for c in cs)}
                out["inventory_unsure"] = sorted(n for n, cs in stacks.items()
                                                 if any(c.value is None for c in cs))
        for name, count in quick.items():
            if count.value is None:
                out["unread"].append((name, count.img))
            else:
                out["quick"][name] = count.value
                out["read"].append(name)
        return out


class App:
    def __init__(self):
        screen.make_dpi_aware()
        self.cfg = config.load()
        self.store = GlyphStore(config.GLYPHS)
        self.locator = Locator()
        self.root = tk.Tk()
        self.root.title("Maple Tracker")
        self.ui_screen = Screen()
        self.session: Session | None = None
        self.stopping = False
        self.latest = {}
        self.lost_since = None
        self.mesos_seen = Stable()
        self.library = ItemLibrary()
        self.items_latest = {}
        self.item_counts = {}               # item -> how many there are, as best known
        self.quick_unlinked = set()         # quickslot items whose count the inventory contradicts
        self.items_seen: dict[str, Stable] = {}
        self.unread_streak = defaultdict(int)  # quickslot item -> scans in a row it couldn't be read
        self.count_hint = None                 # a quickslot count to learn once the inventory opens
        self.last_record = None                # the last finished session, for Share
        self.recheck_until = 0                 # while Recheck waits for the inventory
        self.flash = None                      # (a short message, until when)
        self.teach_queue = {}               # what needs teaching: key -> (kind, image, title)
        self.skip_teach = {}                # key -> time until which it isn't asked again
        self.q = queue.Queue()
        self._update_jobs()
        self.reader = Reader(self.store, self.locator, lambda: self._jobs, self.q)
        self.reader.start()
        self.item_q = queue.Queue()
        self.scanner = ItemScanner(self.store, self.library, self.item_q)
        self.scanner.start()
        self.item_download = None           # None, "running", "done" or the error
        self.exp_table = itemdata.exp_table()  # level -> EXP to next level, for the level badge
        self.last_mesos = None
        if not itemdata.available() or not self.exp_table:
            self.download_items()
        self._build()
        self.root.after(250, self._tick)

    # ---- settings
    def save_config(self):
        config.save(self.cfg)
        self._update_jobs()

    def set_region(self, key, region):
        self.cfg["regions"][key] = region
        self.save_config()

    def _update_jobs(self):
        """What the reading thread reads, swapped in whole so it never sees half a change."""
        self._jobs = {"manual": dict(self.cfg["regions"])}

    def price(self, name):
        """What an item costs: the player's own price if they set one, else the NPC shop's."""
        if name in self.cfg["prices"]:
            return self.cfg["prices"][name]
        item = self.library.by_name.get(name)
        return item.price if item else 0

    # ---- overlay
    def _build(self):
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=card.KEY_HEX)
        r.attributes("-transparentcolor", card.KEY_HEX)     # the card's rounded corners
        r.attributes("-alpha", self.cfg["alpha"])
        pos = self.cfg.get("overlay_pos") or [40, 40]
        r.geometry(f"+{pos[0]}+{pos[1]}")
        self.card = tk.Label(r, bd=0, bg=card.KEY_HEX, highlightthickness=0)
        self.card.pack()
        self._shown, self._hits = None, {}
        self._hover = self._pressed = self._drag_from = None
        self._msg_action = None
        self.expanded = bool(self.cfg.get("details_open"))
        self.card.bind("<ButtonPress-1>", self._press)
        self.card.bind("<B1-Motion>", self._drag)
        self.card.bind("<ButtonRelease-1>", self._release)
        self.card.bind("<Motion>", self._move)
        self.card.bind("<Leave>", lambda e: self._set_hover(None))
        self.actions = {"main": self.start_or_stop, "pause": self.toggle_pause, "recheck": self.recheck,
                        "prices": lambda: PricesDialog(self), "share": self.share, "close": self.quit,
                        "details": self._toggle_details, "message": self._msg_click}

        # Teaching, inline: the unread number and a box to type it in. It needs a real text
        # box, so it's widgets under the card rather than part of the picture.
        bg, fg, gold = "#2a2017", "#fcf8f0", "#ffc45c"
        self.teach = tk.Frame(r, bg=bg, padx=12, pady=8, highlightthickness=2,
                              highlightbackground="#8b6837")
        self.teach_title = tk.Label(self.teach, text="", bg=bg, fg=gold, font=FONT, wraplength=440,
                                    justify="left")
        self.teach_title.pack(anchor="w")
        row = tk.Frame(self.teach, bg=bg)
        row.pack(anchor="w", pady=(4, 0))
        self.teach_img = tk.Label(row, bg="#000")
        self.teach_img.pack(side="left")
        self.teach_var = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.teach_var, width=14, font=FONT, bg="#1a130d", fg=fg,
                         insertbackground=fg, relief="flat", highlightthickness=1,
                         highlightbackground="#8b6837")
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self._teach_ok())
        for text, command in (("OK", self._teach_ok), ("✕", self._teach_skip)):
            tk.Button(row, text=text, command=command, bg="#5c462f", fg=fg, activebackground="#6e5639",
                      activeforeground=fg, relief="flat", padx=10, pady=2, font=FONT,
                      cursor="hand2").pack(side="left", padx=(0, 4))
        self.teach_entry = entry
        self._teaching = None
        r.after(200, lambda: screen.exclude_from_capture(r))

    # Clicks on the card: a button acts when released over it; anywhere else drags the window.
    def _press(self, e):
        name = card.hit(self._hits, e.x, e.y)
        if name:
            self._pressed = name
            self._redraw()
        else:
            self._drag_from = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag(self, e):
        if self._drag_from:
            self.root.geometry(f"+{e.x_root - self._drag_from[0]}+{e.y_root - self._drag_from[1]}")

    def _release(self, e):
        if self._pressed:
            name, self._pressed = self._pressed, None
            self._redraw()
            if card.hit(self._hits, e.x, e.y) == name and name in self.actions:
                self.actions[name]()
            return
        if self._drag_from:
            self._drag_from = None
            self.cfg["overlay_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            config.save(self.cfg)

    def _move(self, e):
        self._set_hover(card.hit(self._hits, e.x, e.y))

    def _set_hover(self, name):
        if name != self._hover:
            self._hover = name
            self.card.config(cursor="hand2" if name else "fleur")
            self._redraw()

    def _toggle_details(self):
        self.expanded = not self.expanded
        self.cfg["details_open"] = self.expanded
        config.save(self.cfg)
        self._redraw()

    def _redraw(self):
        self._render(time.time())

    def _windows(self):
        return [self.root] + [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]

    def select_region(self, prompt, done, point=False):
        """Hide our windows while the player picks a spot on screen, then bring them back."""
        shown = [w for w in self._windows() if w.winfo_viewable()]
        for w in shown:
            w.withdraw()

        def finish(result):
            for w in shown:
                w.deiconify()
                w.attributes("-topmost", True)
            done(result)
        self.root.after(150, lambda: RegionSelector(self.root, prompt, finish, point=point))

    def grab_frame(self):
        """A screenshot of the game (UI thread) and where it is on screen."""
        rect, _ = self.ui_screen.frame_rect()
        return self.ui_screen.grab(rect), rect

    # ---- session
    def start_or_stop(self):
        if not self.session:
            self._begin()
        elif self.stopping:
            self._finish()
        else:
            s = self.session
            if s.mesos_seen and time.time() - s.mesos_seen < 4:
                self._finish()              # the inventory is open right now
            else:
                self.stopping = True

    def _begin(self):
        # Potions and food already seen start from their current counts; others join the
        # session the first time they're seen.
        potions = [PotionState(name, self.price(name), start=n) for name, n in self.item_counts.items()]
        self.session = Session(None, potions, idle_seconds=self.cfg["idle_seconds"],
                               exp_table=self.exp_table)
        self.stopping = False
        self.mesos_seen = Stable()
        self.items_seen = {name: Stable(n) for name, n in self.item_counts.items()}

    def prices_changed(self):
        if self.session:
            for p in self.session.potions.values():
                p.price = self.price(p.name)

    def _finish(self):
        s = self.session
        s.finish(s.mesos, {})
        record = s.summary()
        record["started"] = datetime.fromtimestamp(s.started).isoformat(timespec="seconds")
        record["ended"] = datetime.fromtimestamp(s.ended).isoformat(timespec="seconds")
        config.append_history(record)
        self.last_record = record
        self.session, self.stopping = None, False
        SummaryWindow(self, record)

    def share(self):
        """Copy the stats so far (or the last session's) to paste to friends."""
        if self.session:
            record = self.session.summary()
            text = share.summary_text(record, live=True)
        elif self.last_record:
            text = share.summary_text(self.last_record)
        else:
            self.flash = ("Nothing to share yet: start a session first.", time.time() + 4)
            return
        share.copy_text(self.root, text)
        self.flash = ("Copied. Paste it into Discord or WhatsApp with Ctrl+V.", time.time() + 4)

    def download_items(self):
        """Fetch the potion and food data on first run, in the background."""
        self.item_download = "running"

        def work():
            try:
                if not itemdata.available():
                    itemdata.download()
                    self.library.reload()
                if not self.exp_table:
                    itemdata.download_exp_table()
                    self.exp_table = itemdata.exp_table()
                    if self.session:
                        self.session.exp.table = self.exp_table
                self.item_download = "done"
            except Exception as e:
                self.item_download = f"{type(e).__name__}: {e}"
        threading.Thread(target=work, daemon=True).start()

    def recheck(self):
        """Read every potion and food count again from the inventory, right now, and believe
        what it shows: for when the counts went wrong."""
        self.recheck_until = time.time() + 15
        self.quick_unlinked.clear()
        self.scanner.recheck()
        self.flash = ("Rechecking: keep your inventory open on the Use tab.", time.time() + 15)

    def _apply_recheck(self, out):
        if not out.get("inventory"):
            if not out.get("inventory_open"):
                self.flash = ("Open your inventory on the Use tab to recheck.", self.recheck_until)
            elif out.get("other_tab"):
                self.flash = ("Switch your inventory to the Use tab to recheck.", self.recheck_until)
            return
        counts = combine(out["quick"], out["inventory"], out.get("inventory_unsure", []),
                         self.quick_unlinked)
        for name, n in counts.items():
            self.items_seen[name] = Stable(n)
            self.item_counts[name] = n
            if self.session:
                if name not in self.session.potions:
                    self.session.potions[name] = PotionState(name, self.price(name))
                self.session.set_potion(name, n)
        self.recheck_until = 0
        self.flash = (f"Rechecked {len(counts)} potions and food.", time.time() + 5)

    def toggle_pause(self):
        if self.session:
            self.session.resume() if self.session.paused else self.session.pause()

    def quit(self):
        if self.session and not messagebox.askyesno(
                "Quit", "Quit without saving this session?", parent=self.root):
            return
        self.reader.stopped.set()
        self.scanner.stopped.set()
        self.scanner.wake.set()
        self.root.destroy()

    # ---- live updates
    def _tick(self):
        while True:
            try:
                self._apply(self.q.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                self._apply_items(self.item_q.get_nowait())
            except queue.Empty:
                break
        self._render(time.time())
        self.root.after(250, self._tick)

    def _apply(self, out):
        if "mesos" not in out and "mesos" in self.latest:
            out["mesos"] = self.latest["mesos"]           # read every other time: keep the last
        self.latest = out
        if "error" in out:
            return
        t = out["t"]
        if out.get("found") or self.cfg["regions"].get("exp"):
            self.lost_since = None
        elif self.lost_since is None:
            self.lost_since = t
        self._queue_teaching(out)
        s = self.session
        if not s:
            return
        exp = out.get("exp")
        if exp and exp["value"]:
            s.on_exp(*exp["value"], now=t)
        mesos = out.get("mesos")
        if mesos and mesos["value"] is not None:
            v = mesos["value"]
            if self.mesos_seen.feed(v) is not None or v == s.mesos:
                s.set_mesos(self.mesos_seen.value, now=t)
                if self.stopping:
                    self._finish()
                    return

    def _apply_items(self, out):
        """Potion and food counts from the item scanner."""
        self.items_latest = out
        if "error" in out:
            return
        if time.time() < self.recheck_until:
            self._apply_recheck(out)
            return
        for name in out.get("read", []):
            self.unread_streak.pop(name, None)
        self.count_hint = None
        for name, img in out["unread"]:
            # A count it can't read is learned by itself from the inventory, so the player is
            # only asked when the inventory is open and that didn't work, a few scans in a row
            # (not for a moment's overlap, like the mouse passing over it). With the inventory
            # closed, the overlay just asks for it to be opened.
            self.unread_streak[name] += 1
            key = f"potion:{name}"
            if not out.get("inventory_open"):
                self.count_hint = name
            elif self.session and self.unread_streak[name] >= 3 and self.skip_teach.get(key, 0) < out["t"]:
                self.teach_queue[key] = ("potion", img, f"Your {name} count shows a digit I haven't learned yet.")
        counts = combine(out["quick"], out["inventory"], out.get("inventory_unsure", []),
                         self.quick_unlinked)
        for name, n in counts.items():
            self.teach_queue.pop(f"potion:{name}", None)
            stable = self.items_seen.setdefault(name, Stable())
            new = stable.feed(n)
            if new is None and stable.value != n:
                continue                                # wait for a second reading to agree
            self.item_counts[name] = stable.value
            s = self.session
            if s and new is not None:
                if name not in s.potions:
                    s.potions[name] = PotionState(name, self.price(name))
                s.set_potion(name, new)

    def _queue_teaching(self, out):
        now = out["t"]
        items = [("exp", "exp", out.get("exp"), "The EXP bar shows a character I haven't learned yet."),
                 ("mesos", "mesos", out.get("mesos"), "Your mesos show a digit I haven't learned yet.")]
        for key, kind, r, title in items:
            if r and r["unknown"] and self.skip_teach.get(key, 0) < now:
                self.teach_queue[key] = (kind, r["img"], title)
            elif r and r["value"] is not None:
                self.teach_queue.pop(key, None)

    def _show_teaching(self):
        if self._teaching and self._teaching in self.teach_queue:
            return
        self._teaching = next(iter(self.teach_queue), None)
        if not self._teaching:
            self.teach.pack_forget()
            return
        kind, img, title = self.teach_queue[self._teaching]
        h, w = img.shape[:2]
        k = max(1, min(4, 240 // max(1, w), 40 // max(1, h)))
        self._teach_photo = ImageTk.PhotoImage(Image.fromarray(img).resize((w * k, h * k), Image.NEAREST))
        self.teach_img.config(image=self._teach_photo)
        self.teach_title.config(text=title + " What does it say? I only ask once per digit.")
        self.teach_var.set("")
        self.teach.pack(anchor="w", pady=(4, 0))
        self.teach_entry.focus_set()

    def _teach_ok(self):
        key = self._teaching
        if not key or key not in self.teach_queue:
            return
        kind, img, _ = self.teach_queue[key]
        ok, msg = self.store.learn(kind, img, self.teach_var.get())
        if ok:
            self.teach_queue.pop(key, None)
            self._teaching = None
        else:
            self.teach_title.config(text=msg)

    def _teach_skip(self):
        if self._teaching:
            self.skip_teach[self._teaching] = time.time() + 120
            self.teach_queue.pop(self._teaching, None)
            self._teaching = None

    def _render(self, now):
        v = self._view(now)
        if v != self._shown:                    # only draw when something changed
            img, self._hits = card.render(v)
            self._card_photo = ImageTk.PhotoImage(img)
            self.card.config(image=self._card_photo)
            self._shown = v
        self._show_teaching()

    def _view(self, now):
        s, out = self.session, self.latest
        exp = out.get("exp")
        reading = exp["value"] if exp and exp["value"] else None
        mesos = out.get("mesos")
        if mesos and mesos["value"] is not None:
            self.last_mesos = mesos["value"]
        v = card.View(hover=self._hover, pressed=self._pressed, expanded=self.expanded)
        if reading:
            v.exp, v.pct = reading
        v.level = (s.exp.level() if s else None) or (level_of(*reading, self.exp_table) if reading else None)
        v.mesos = s.mesos if s and s.mesos is not None else self.last_mesos
        to_level = f"To Lv. {v.level + 1}" if v.level else "To level"
        dash = "—"
        if not s:
            v.state, v.state_text = "off", "Not tracking"
            v.tiles = [("Last 5 min", dash, None), ("EXP / hour", dash, None), (to_level, dash, None),
                       ("This session", dash, None), ("Session time", dash, None), ("% / hour", dash, None)]
            v.meso_tiles = [("Mesos / hour", dash, None), ("Net mesos", dash, None), ("Potions", dash, None)]
            v.buttons = [("main", "Start", True, True), ("pause", "Pause", False, False)]
        else:
            if self.stopping:
                v.state, v.state_text = "finishing", "Finishing"
            elif s.paused:
                v.state, v.state_text = "paused", "Paused"
            elif s.idle(now):
                v.state, v.state_text = "idle", "Idle"
            else:
                v.state, v.state_text = "tracking", "Tracking"
            v.clock = fmt.clock(s.active(now))
            pct = s.pct_rate(now)
            eta = fmt.eta(s.tnl_seconds(now))
            v.tiles = [("Last 5 min", fmt.short(s.recent_exp(now), sign=True), None),
                       ("EXP / hour", fmt.short(s.exp_rate(now)), None),
                       (to_level, eta, None),
                       ("This session", fmt.short(s.exp_gained, sign=True), None),
                       ("Session time", fmt.clock(s.active(now)), None),
                       ("% / hour", f"{pct:.1f}%" if pct else dash, None)]
            if s.mesos_start is None:
                v.meso_tiles = [("Mesos / hour", dash, None), ("Net mesos", dash, None)]
            else:
                net_color = card.GOLD if s.net_mesos >= 0 else card.RED
                v.meso_tiles = [("Mesos / hour", fmt.short(s.net_rate(now), sign=True), net_color),
                                ("Net mesos", fmt.short(s.net_mesos, sign=True), net_color)]
            v.meso_tiles.append(("Potions", f"-{fmt.short(s.potion_cost)}" if s.potion_cost else "0",
                                 card.RED if s.potion_cost else None))
            main = "Finish now" if self.stopping else "Stop"
            v.buttons = [("main", main, True, True),
                         ("pause", "Resume" if s.paused else "Pause", False, True)]
        v.buttons += [("recheck", "Recheck", False, True), ("prices", "Prices", False, True),
                      ("share", "Share", False, True)]
        v.details = self._detail_lines(s)
        v.message, self._msg_action = self._message(out, now)
        v.message_clickable = self._msg_action is not None
        return v

    def _detail_lines(self, s):
        """One line per potion, so it's easy to check the counts are read right."""
        lines = []
        if s:
            if s.mesos_start is not None:
                lines.append(f"Mesos at start  {s.mesos_start:,}")
            for p in s.potions.values():
                if p.start is None:
                    lines.append(f"{p.name}  not seen yet")
                else:
                    parts = [f"−{p.used} drunk"] if p.used else []
                    parts += [f"+{p.added} bought"] if p.added else []
                    parts += [f"{p.removed} put away"] if p.removed else []
                    change = f"  ({', '.join(parts)})" if parts else ""
                    lines.append(f"{p.name}  {p.start} → {p.count}{change}")
        else:
            for name, n in sorted(self.item_counts.items()):
                lines.append(f"{name}  {n}")
            if not lines and self.items_latest.get("t"):
                lines.append("No potions or food seen yet")
        return lines

    def _msg_click(self):
        if self._msg_action:
            self._msg_action()

    def _message(self, out, now):
        """The one thing worth telling the player, and what clicking it does."""
        s = self.session
        if self.flash and now < self.flash[1]:
            return self.flash[0], None
        if self.item_download == "running":
            return "Downloading potion, food and EXP table data from NiaMeowDB…", None
        if self.item_download not in (None, "running", "done"):
            return ("Couldn't download potion data (no internet?). Click to try again.",
                    self.download_items)
        if "error" in out:
            return f"Reading failed: {out['error']}", None
        if not out:
            return "Looking for the game…", None
        if self.lost_since and now - self.lost_since > LOST_AFTER:
            return "Can't find the EXP bar. Click to point it out by hand.", lambda: ManualSetup(self)
        if not out.get("found") and not self.cfg["regions"].get("exp"):
            return "Looking for the EXP bar…", None
        if self.stopping:
            return "Open your inventory to record your final mesos, or press Finish now.", None
        if s and s.mesos_start is None:
            return "Open your inventory once so I can note your mesos and potions.", None
        if self.count_hint:
            return f"Open your inventory for a moment so I can learn your {self.count_hint} count.", None
        if s and self.items_latest.get("other_tab"):
            return "Your inventory is on another tab: potions are read from the Use tab.", None
        return "", None


def main():
    App().root.mainloop()
