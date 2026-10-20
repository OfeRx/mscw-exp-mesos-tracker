"""The windows besides the overlay: potions, pointing things out by hand, the summary and the
history."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageTk

from . import card, config, history, share
from .glyphs import parse_exp, parse_number, parse_typed_number
from .screen import Screen, game_origin, make_region, region_rect

BG = "#241b13"
PANEL = "#1a130d"
FG = "#fcf8f0"
MUTED = "#c4ac8a"
GOOD = "#7bd88f"
WARN = "#ffc45c"
BAD = "#ff7a7a"
FONT = ("Segoe UI", 10)
BOLD = ("Segoe UI", 10, "bold")


def button(parent, text, command, **kw):
    return tk.Button(parent, text=text, command=command, bg="#5c462f", fg=FG, activebackground="#6e5639",
                     activeforeground=FG, relief="flat", padx=10, pady=3, font=FONT, cursor="hand2", **kw)


def label(parent, text="", fg=FG, font=FONT, **kw):
    return tk.Label(parent, text=text, bg=kw.pop("bg", BG), fg=fg, font=font, justify="left", **kw)


def para(parent, text):
    w = label(parent, text, fg=MUTED, wraplength=440)
    w.pack(anchor="w", pady=(0, 8))
    return w


def heading(parent, text):
    label(parent, text, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))


class Dialog(tk.Toplevel):
    """A dark, always-on-top window that's left out of screenshots."""

    def __init__(self, app, title):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.body = tk.Frame(self, bg=BG, padx=16, pady=12)
        self.body.pack(fill="both", expand=True)
        self.after(150, lambda: app.apply_capture(self))


# --------------------------------------------------------------------------- drawing a box

class RegionSelector:
    """Dims the desktop; drag a box, or with point=True click a spot (Esc cancels). Calls
    on_done(rect or (x, y)) in screen coordinates, or on_done(None)."""

    def __init__(self, root, prompt, on_done, point=False):
        self.on_done, self.point = on_done, point
        sc = Screen()
        vx, vy, vw, vh = sc.virtual()
        sc.close()
        self.origin = (vx, vy)
        self.win = w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.geometry(f"{vw}x{vh}+{vx}+{vy}")
        w.attributes("-alpha", 0.35)
        w.attributes("-topmost", True)
        self.canvas = c = tk.Canvas(w, bg="black", cursor="cross", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_text(vw // 2, 60, text=f"{prompt}   (Esc to cancel)", fill="white",
                      font=("Segoe UI", 18, "bold"))
        self.start, self.rect_id = None, None
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        w.bind("<Escape>", lambda e: self._finish(None))
        w.focus_force()

    def _press(self, e):
        if self.point:
            self._finish((e.x + self.origin[0], e.y + self.origin[1]))
            return
        self.start = (e.x, e.y)
        self.rect_id = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff5050", width=2)

    def _drag(self, e):
        if self.start:
            self.canvas.coords(self.rect_id, *self.start, e.x, e.y)

    def _release(self, e):
        if not self.start:
            return
        (x0, y0), (x1, y1) = self.start, (e.x, e.y)
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 4 or y1 - y0 < 4:
            self._finish(None)
            return
        self._finish((x0 + self.origin[0], y0 + self.origin[1], x1 - x0, y1 - y0))

    def _finish(self, rect):
        self.win.destroy()
        self.on_done(rect)


# --------------------------------------------------------------------------- one box, live

class RegionPanel(tk.Frame):
    """One box on screen: draw it, see what's read from it live, and correct or teach it.

    Whatever the player types is also what the reader learns from, so the first time each
    box is used the player types what it shows, and from then on it reads by itself."""

    def __init__(self, parent, app, kind, get_region, set_region, prompt, numeric=True, compact=False):
        super().__init__(parent, bg=BG)
        self.app, self.kind = app, kind
        self.get_region, self.set_region, self.prompt = get_region, set_region, prompt
        self.numeric = numeric
        self.img = None
        self.value_read = None
        self.edited = False
        self.size = (150, 34) if compact else (440, 70)

        self.canvas = tk.Canvas(self, width=self.size[0], height=self.size[1], bg="#000",
                                highlightthickness=1, highlightbackground="#8b6837")
        self.draw_btn = button(self, "Draw box", self.select)
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, width=14 if compact else 24, font=FONT,
                              bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                              highlightthickness=1, highlightbackground="#8b6837")
        self.entry.bind("<Key>", lambda e: setattr(self, "edited", True))
        self.status = label(self, "", fg=MUTED, wraplength=150 if compact else 440)
        if compact:
            self.draw_btn.grid(row=0, column=0, padx=(0, 6))
            self.canvas.grid(row=0, column=1, padx=(0, 6))
            self.entry.grid(row=0, column=2, padx=(0, 6))
            self.status.grid(row=1, column=1, columnspan=2, sticky="w")
        else:
            self.canvas.pack(anchor="w")
            row = tk.Frame(self, bg=BG)
            row.pack(anchor="w", fill="x", pady=(6, 0))
            self.draw_btn.pack(in_=row, side="left")
            label(row, "  It shows:").pack(side="left")
            self.entry.pack(in_=row, side="left", padx=6)
            self.draw_btn.lift(row)          # made before the row, so they'd sit behind it
            self.entry.lift(row)
            if not numeric:
                button(row, "Teach", self.teach).pack(side="left")
            self.status.pack(anchor="w", pady=(4, 0))
        self._tick()

    def _tick(self):
        if not self.winfo_exists():
            return
        try:
            self.refresh()
        except tk.TclError:
            return
        self.after(700, self._tick)

    def refresh(self):
        region = self.get_region()
        self.draw_btn.config(text="Redraw box" if region else "Draw box")
        origin = game_origin()
        rect = region_rect(region, origin)
        if rect is None:
            self.img = self.value_read = None
            self._show(None, [], "")
            self._status("Draw a box around it." if not region else
                         "Game window not found (is it minimised?).", MUTED if not region else WARN)
            return
        img = self.app.ui_screen.grab(rect)
        if img is None:
            self.img = self.value_read = None
            self._status("The box is off screen: redraw it.", WARN)
            return
        text, glyphs = self.app.store.read(self.kind, img)
        value = parse_exp(text) if self.kind == "exp" else parse_number(text)
        self.img, self.value_read = img, value
        self._show(img, glyphs, text)
        if value is not None:
            shown = f"{value[0]:,} [{value[1]:.2f}%]" if self.kind == "exp" else f"{value:,}"
            self._status(f"✓ Reads {shown}", GOOD)
            if not self.edited:
                self.var.set(shown)
        elif not glyphs:
            self._status("No number in the box.", WARN)
        elif "?" in text:
            self._status("Red characters aren't learned yet: type what the box shows"
                         + ("." if self.numeric else ", then Teach."), WARN)
        else:
            self._status(f"Can't make sense of '{text}': make the box tight around the number.", WARN)

    def _status(self, text, color):
        self.status.config(text=text, fg=color)

    def _show(self, img, glyphs, text):
        w, h = self.size
        self.canvas.delete("all")
        if img is None:
            return
        ih, iw = img.shape[:2]
        scale = max(1, min(w // iw, h // ih)) if iw <= w and ih <= h else min(w / iw, h / ih)
        pic = Image.fromarray(img).resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.NEAREST)
        d = ImageDraw.Draw(pic)
        for g, ch in zip(glyphs, text):
            x0, y0, x1, y1 = g.box
            color = (255, 80, 80) if ch == "?" else (90, 220, 120)
            d.rectangle([x0 * scale, y0 * scale, x1 * scale - 1, y1 * scale - 1], outline=color)
        self._photo = ImageTk.PhotoImage(pic)
        self.canvas.create_image(w // 2, h // 2, image=self._photo)

    def select(self):
        def done(rect):
            if rect:
                self.set_region(make_region(rect, game_origin()))
                self.edited = False
            if self.winfo_exists():
                self.refresh()
        self.app.select_region(self.prompt, done)

    def value(self):
        if self.kind == "exp":
            return self.value_read
        return parse_typed_number(self.var.get())

    def teach(self):
        if self.img is None:
            self._status("Draw a box first.", WARN)
            return
        ok, msg = self.app.store.learn(self.kind, self.img, self.var.get())
        if ok:
            self.edited = False
            self.refresh()
            if self.value_read is None:
                self._status(msg + " Some characters may still be missing: teach another reading.", WARN)
        else:
            self._status(msg, BAD)

    def learn_quietly(self):
        """Learn from what's in the entry now (the player confirmed it), if it lines up."""
        if self.img is not None and self.var.get().strip():
            self.app.store.learn(self.kind, self.img, self.var.get())


# --------------------------------------------------------------------------- prices

class PricesDialog(Dialog):
    """What each potion and food item costs, for the potion bill: NPC shop prices to start with
    (from NiaMeowDB), changeable for anything you buy elsewhere."""

    def __init__(self, app):
        super().__init__(app, "Prices")
        heading(self.body, "Potion and food prices")
        para(self.body, "Potions and food are found on your quickslot and in your inventory by "
                        "themselves. These are NPC shop prices (from NiaMeowDB): change any you "
                        "pay differently. ~ marks an estimate, for items no open shop sells.")
        names = sorted(set(app.item_counts) | set(app.cfg["prices"])
                       | set(app.session.potions if app.session else ()))
        grid = tk.Frame(self.body, bg=BG)
        grid.pack(anchor="w")
        for col, text in enumerate(("Item", "You have", "Price")):
            label(grid, text, fg=MUTED).grid(row=0, column=col, sticky="w", padx=(0, 14))
        self.vars = {}
        for i, name in enumerate(names, start=1):
            item = app.library.by_name.get(name)
            label(grid, name).grid(row=i, column=0, sticky="w", padx=(0, 14), pady=2)
            have = app.item_counts.get(name)
            label(grid, "—" if have is None else str(have), fg=MUTED).grid(row=i, column=1, sticky="w")
            var = tk.StringVar(value=str(app.price(name)))
            entry(grid, var, 8).grid(row=i, column=2, sticky="w")
            if item and item.estimated and name not in app.cfg["prices"]:
                label(grid, "~", fg=MUTED).grid(row=i, column=3, sticky="w")
            self.vars[name] = var
        if not names:
            para(self.body, "None seen yet: put potions on your quickslot, or open your inventory "
                            "on the Use tab.")
        nav = tk.Frame(self, bg=BG, padx=16, pady=10)
        nav.pack(fill="x", side="bottom")
        button(nav, "Cancel", self.destroy).pack(side="left")
        button(nav, "Save", self._save).pack(side="right")

    def _save(self):
        prices = dict(self.app.cfg["prices"])
        for name, var in self.vars.items():
            price = parse_typed_number(var.get())
            if price is None:
                messagebox.showwarning("Prices", f"Type a price for {name}.", parent=self)
                return
            item = self.app.library.by_name.get(name)
            if item and price == item.price:
                prices.pop(name, None)                  # back to the shop price
            else:
                prices[name] = price
        self.app.cfg["prices"] = prices
        self.app.save_config()
        self.app.prices_changed()
        self.destroy()


def entry(parent, var, width):
    return tk.Entry(parent, textvariable=var, width=width, font=FONT, bg=PANEL, fg=FG, insertbackground=FG,
                    relief="flat", highlightthickness=1, highlightbackground="#8b6837")


# --------------------------------------------------------------------------- by hand

class ManualSetup(Dialog):
    """If the EXP bar can't be found on its own (a different UI layout): draw the boxes."""

    def __init__(self, app):
        super().__init__(app, "Set up by hand")
        heading(self.body, "Point out the numbers")
        para(self.body, "I couldn't find the EXP bar by myself. Drag a box around the EXP numbers "
                        "(like 38,849 [61.02%]), type what it shows and press Teach.")
        RegionPanel(self.body, app, "exp", lambda: app.cfg["regions"].get("exp"),
                    lambda r: app.set_region("exp", r), "Drag a box around the EXP numbers",
                    numeric=False).pack(anchor="w", fill="x")
        para(self.body, "\nThen open your inventory and do the same for your meso count.")
        RegionPanel(self.body, app, "mesos", lambda: app.cfg["regions"].get("mesos"),
                    lambda r: app.set_region("mesos", r), "Drag a box around your meso count",
                    numeric=False).pack(anchor="w", fill="x")
        nav = tk.Frame(self, bg=BG, padx=16, pady=10)
        nav.pack(fill="x", side="bottom")
        button(nav, "Done", self.destroy).pack(side="right")


# --------------------------------------------------------------------------- summary and history

def _shown(big):
    """A picture drawn at card.S times the size, at screen size."""
    return ImageTk.PhotoImage(big.resize((big.width // card.S, big.height // card.S), Image.LANCZOS))


class SummaryWindow(Dialog):
    """One session: the picture that Copy image puts on the clipboard, and the buttons."""

    def __init__(self, app, s):
        super().__init__(app, "Session summary")
        self.body.config(padx=10, pady=10)
        self.record = s
        self.big = share.summary_card(s, icon=app.library.icon)
        self._photo = _shown(self.big)
        tk.Label(self.body, image=self._photo, bg=BG, bd=0).pack()
        nav = tk.Frame(self, bg=BG, padx=10)
        nav.pack(fill="x")
        button(nav, "Copy image", self._copy_image).pack(side="left")
        button(nav, "Copy text", self._copy_text).pack(side="left", padx=6)
        button(nav, "All sessions", lambda: HistoryWindow(app)).pack(side="left")
        button(nav, "Close", self.destroy).pack(side="right")
        self.copied = label(self, "For Discord or WhatsApp: copy, then paste with Ctrl+V.", fg=MUTED, padx=10)
        self.copied.pack(anchor="w", pady=(6, 10))

    def _copy_text(self):
        share.copy_text(self, share.summary_text(self.record))
        self.copied.config(text="Copied. Paste it into Discord or WhatsApp with Ctrl+V.", fg=GOOD)

    def _copy_image(self):
        if share.copy_image(self.big):
            self.copied.config(text="Picture copied. Paste it into Discord or WhatsApp with Ctrl+V.", fg=GOOD)
        else:
            self.copied.config(text="Couldn't reach the clipboard: try again.", fg=WARN)


class HistoryWindow(Dialog):
    """Every saved session, newest first: click one to see it in full."""

    def __init__(self, app):
        super().__init__(app, "Session history")
        self.body.config(padx=10, pady=10)
        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(side="left")
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta // 40, "units"))
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", lambda e: self.canvas.delete("hover"))
        self.canvas.bind("<ButtonRelease-1>", self._open)
        self.canvas.bind("<Button-3>", self._menu)
        self.bar = tk.Scrollbar(self.body, command=self.canvas.yview)
        self.canvas.config(yscrollcommand=self.bar.set, yscrollincrement=8)
        self.refresh()

    def refresh(self):
        big, self.rows = history.render(config.load_history())
        self._photo = _shown(big)
        w, h = self._photo.width(), self._photo.height()
        tall = h > self.HEIGHT
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self.canvas.config(width=w, height=min(h, self.HEIGHT), scrollregion=(0, 0, w, h))
        if tall:
            self.bar.pack(side="right", fill="y")
        else:
            self.bar.pack_forget()

    HEIGHT = 640

    def _row(self, e):
        y = self.canvas.canvasy(e.y)
        return next((row for row in self.rows if row[0] <= y < row[1]), None)

    def _hover(self, e):
        self.canvas.delete("hover")
        row = self._row(e)
        if row:
            self.canvas.create_rectangle(16, row[0], history.W - 16, row[1], outline="#d6ac62", width=1,
                                         tags="hover")

    def _open(self, e):
        row = self._row(e)
        if row:
            SummaryWindow(self.app, row[2])

    def _menu(self, e):
        row = self._row(e)
        if not row:
            return
        menu = tk.Menu(self, tearoff=0, bg=BG, fg=FG, activebackground="#6e5639", activeforeground=FG, font=FONT)
        menu.add_command(label="See it in full", command=lambda: SummaryWindow(self.app, row[2]))
        menu.add_command(label="Delete from history…", command=lambda: self._delete(row[2]))
        menu.tk_popup(e.x_root, e.y_root)

    def _delete(self, record):
        when = history._date(record)
        if messagebox.askyesno("Delete session", f"Delete the session from {when} from your history?",
                               parent=self):
            config.delete_history(record)
            self.refresh()
