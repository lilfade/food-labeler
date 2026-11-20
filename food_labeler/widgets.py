"""Big, friendly Tk building blocks: dialogs, calendar, toggles, scroll frame.

Everything uses the named fonts the main window creates ("ui", "big", …), so
the A−/A+ text size buttons resize every window at once. Colours are plain
constants here; there is no theme engine.
"""
from __future__ import annotations

import calendar
import datetime as dt
import tkinter as tk
from tkinter import ttk

from . import dates

# High Thyme Kitchen-ish colours, high contrast.
BG = "#F6F1E7"
PANEL = "#FFFFFF"
INK = "#1E1E1E"
MUTED = "#55524C"
GREEN = "#1F6B45"
GREEN_DARK = "#174F33"
GREEN_LIGHT = "#DCEFE2"
WARN = "#B34700"
WARN_BG = "#FFF1DC"
BORDER = "#C9C2B4"


def center_on(win: tk.Toplevel, parent: tk.Misc):
    """Place a window over its parent (a little above centre), kept on screen."""
    win.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    except tk.TclError:
        px = py = 0
        pw, ph = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = max(0, min(sw - w, px + (pw - w) // 2))
    y = max(0, min(sh - h - 40, py + (ph - h) // 3))
    win.geometry(f"+{x}+{y}")


class Modal(tk.Toplevel):
    """A modal window with big text. result is set by the buttons."""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=BG)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())
        self.body = tk.Frame(self, bg=BG, padx=28, pady=22)
        self.body.pack(fill="both", expand=True)

    def cancel(self):
        """Close with result None (also Escape and the window's close button)."""
        self.result = None
        self.destroy()

    def finish(self, value):
        """Close with ``value`` as the result."""
        self.result = value
        self.destroy()

    def run(self):
        """Show, grab input and wait until closed. Returns the result."""
        center_on(self, self.master)
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()
        self.wait_window()
        return self.result


def button(parent, text, command, kind="normal", font="ui", width=None, **kw):
    """A big flat button with words. kind: normal | primary | print | chip | quiet."""
    colors = {
        "normal": ("#FFFFFF", INK, "#EFE9DD"),
        "primary": (GREEN, "#FFFFFF", GREEN_DARK),
        "print": (GREEN, "#FFFFFF", GREEN_DARK),
        "chip": ("#EFE9DD", INK, "#E3DCCD"),
        "quiet": (BG, GREEN_DARK, "#EFE9DD"),
        "warn": ("#FFFFFF", WARN, WARN_BG),
    }[kind]
    b = tk.Button(parent, text=text, command=command, font=font, bg=colors[0], fg=colors[1],
                  activebackground=colors[2], activeforeground=colors[1], relief="flat",
                  bd=0, highlightthickness=2, highlightbackground=BORDER,
                  highlightcolor=GREEN, cursor="hand2", padx=12, pady=6, **kw)
    if width:
        b.configure(width=width)
    if kind in ("primary", "print"):
        b.configure(highlightbackground=GREEN_DARK)
    return b


def ask(parent, title: str, message: str, buttons, icon: str = "") -> str | None:
    """Show a message with big buttons. buttons: [(text, value, kind), ...]."""
    m = Modal(parent, title)
    if icon:
        tk.Label(m.body, text=icon, font="huge", bg=BG, fg=GREEN).pack(pady=(0, 6))
    tk.Label(m.body, text=message, font="ui", bg=BG, fg=INK, wraplength=640,
             justify="left").pack(anchor="w", pady=(0, 18))
    row = tk.Frame(m.body, bg=BG)
    row.pack(fill="x")
    first = None
    for text, value, kind in buttons:
        b = button(row, text, lambda v=value: m.finish(v), kind)
        b.pack(side="left", padx=(0, 12))
        first = first or b
    if first is not None:
        first.focus_set()
    return m.run()


def tell(parent, title: str, message: str, icon: str = "") -> None:
    """A message with a single OK button."""
    ask(parent, title, message, [("OK", True, "primary")], icon)


class ScrollFrame(tk.Frame):
    """A vertically scrolling frame; the mouse wheel works anywhere over it."""

    def __init__(self, parent, bg=PANEL):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=200, height=160)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", self._wheel, add="+")
        self.bind_all("<Button-5>", self._wheel, add="+")

    def _on_inner(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        # ask for as much width as the content needs, so nothing gets squeezed
        need = self.inner.winfo_reqwidth()
        if int(self.canvas.cget("width")) != need:
            self.canvas.configure(width=need)

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _over_me(self, e) -> bool:
        w = e.widget
        while w is not None:
            if w is self:
                return True
            w = getattr(w, "master", None)
        return False

    def _wheel(self, e):
        try:
            if not self._over_me(e) or isinstance(e.widget, tk.Text):
                return
        except (AttributeError, tk.TclError):
            return
        if getattr(e, "num", None) == 4:
            step = -2
        elif getattr(e, "num", None) == 5:
            step = 2
        else:
            step = -2 if e.delta > 0 else 2
        self.canvas.yview_scroll(step, "units")

    def scroll_to(self, widget):
        """Scroll so ``widget`` (inside .inner) is near the top, e.g. the field that is too long."""
        self.update_idletasks()
        try:
            y = widget.winfo_rooty() - self.inner.winfo_rooty()
            h = max(1, self.inner.winfo_height())
            self.canvas.yview_moveto(max(0.0, (y - 40) / h))
        except tk.TclError:
            pass


class Toggle(tk.Button):
    """A big on/off button with a tick, e.g. for allergens."""

    def __init__(self, parent, text, command=None, value=False):
        self.word = text
        self._cmd = command
        self.value = bool(value)
        super().__init__(parent, command=self._click, font="ui", relief="flat", bd=0,
                         highlightthickness=2, cursor="hand2", padx=10, pady=6, anchor="w")
        self._paint()

    def _click(self):
        self.value = not self.value
        self._paint()
        if self._cmd:
            self._cmd()

    def set(self, value: bool):
        """Change the state without calling the command (used when syncing from text)."""
        self.value = bool(value)
        self._paint()

    def _paint(self):
        if self.value:
            self.configure(text=f"✔ {self.word}", bg=GREEN_LIGHT, fg=GREEN_DARK,
                           activebackground=GREEN_LIGHT, highlightbackground=GREEN)
        else:
            self.configure(text=f"  {self.word}", bg="#FFFFFF", fg=INK,
                           activebackground="#EFE9DD", highlightbackground=BORDER)


class CalendarDialog(Modal):
    """A plain month grid with big day buttons."""

    def __init__(self, parent, title: str, initial: dt.date | None):
        super().__init__(parent, title)
        self.sel = initial or dates.today()
        self.month = self.sel.replace(day=1)
        top = tk.Frame(self.body, bg=BG)
        top.pack(fill="x", pady=(0, 10))
        button(top, "◀ Earlier", lambda: self._shift(-1)).pack(side="left")
        self.title_lbl = tk.Label(top, font="big", bg=BG, fg=INK, width=16)
        self.title_lbl.pack(side="left", expand=True, fill="x", padx=10)
        button(top, "Later ▶", lambda: self._shift(1)).pack(side="right")
        self.grid_f = tk.Frame(self.body, bg=BG)
        self.grid_f.pack()
        bottom = tk.Frame(self.body, bg=BG)
        bottom.pack(fill="x", pady=(14, 0))
        button(bottom, "Today", lambda: self.finish(dates.today()), "chip").pack(side="left")
        button(bottom, "Cancel", self.cancel).pack(side="right")
        self._draw()

    def _shift(self, n):
        self.month = dates.add_months(self.month, n)
        self._draw()

    def _draw(self):
        for w in self.grid_f.winfo_children():
            w.destroy()
        self.title_lbl.configure(text=f"{calendar.month_name[self.month.month]} {self.month.year}")
        for c, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            tk.Label(self.grid_f, text=name, font="ui", bg=BG, fg=MUTED).grid(row=0, column=c,
                                                                              padx=3, pady=3)
        cal = calendar.Calendar(firstweekday=6)
        today = dates.today()
        for r, week in enumerate(cal.monthdatescalendar(self.month.year, self.month.month), 1):
            for c, d in enumerate(week):
                if d.month != self.month.month:
                    tk.Label(self.grid_f, text="", bg=BG, width=3).grid(row=r, column=c)
                    continue
                kind = "primary" if d == self.sel else ("chip" if d == today else "normal")
                b = button(self.grid_f, str(d.day), lambda d=d: self.finish(d), kind, width=3)
                b.grid(row=r, column=c, padx=3, pady=3)
