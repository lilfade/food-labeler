"""The lettering windows: choose the fonts of a label, get more fonts.

* ``LetteringDialog`` — the two choices for one label ("Name of the food",
  "Everything else") with a live preview of the label.
* ``FontPicker`` — a list of fonts, each name drawn in its own font. Tk only
  knows fonts installed on the computer, so every name is a small picture
  drawn with Pillow (lettering.preview_image).
* ``GetFontsDialog`` — type a Google Fonts name, see it, add it. The
  download runs on a worker thread (fontget.fetch_family) and the result
  comes back through a queue polled with ``after()``, so the window never
  freezes and Tk is only touched from the main thread.
* ``add_font_file`` — "Add a font file from my computer…".
* ``offer_missing_fonts`` — the gentle note when a label uses a font this
  computer doesn't have.
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import filedialog

from PIL import ImageTk

from . import fontget, lettering, render
from .widgets import (BG, BORDER, GREEN, GREEN_DARK, GREEN_LIGHT, INK, MUTED, PANEL, WARN,
                      Modal, ScrollFrame, ask, button, tell)

log = logging.getLogger("food_labeler.font_dialogs")

GOOGLE_FONTS = "https://fonts.google.com"
LEGAL_NOTE = ("The wording the law asks for (ingredients, allergens, your address and "
              "your state's statements) always stays in easy-to-read lettering.")


def _px() -> int:
    """Height of a font picture, following the A−/A+ text size."""
    try:
        size = abs(int(tkfont.nametofont("ui").cget("size")))
    except (tk.TclError, ValueError):
        size = 16
    return max(28, int(size * 2.4))


def _photo(text, name=None, data=None, variable=False, height=None, bg=PANEL):
    img = lettering.preview_image(text, height or _px(), name=name, data=data,
                                  variable=variable, bg=_rgb(bg), max_width=520)
    return ImageTk.PhotoImage(img)


def _rgb(color: str):
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def summary(doc) -> str:
    """Short text for the main window: "Standard" or "Pacifico · Lato"."""
    lt = lettering.clean(doc.lettering)
    if lettering.is_default(lt):
        return "Standard"
    name = lt.get("name", lettering.DEFAULT)
    other = lt.get("other", lettering.DEFAULT)
    parts = [name] if doc.template in ("free", "picture") or other == name else [name, other]
    missing = set(lettering.missing(lt))
    return " · ".join(p + (" (not on this computer)" if p in missing else "")
                           for p in parts)


# ---------------------------------------------------------------------------
# the lettering of one label
# ---------------------------------------------------------------------------

class LetteringDialog(Modal):
    """Both lettering choices of the label, with a preview. Result: lettering dict."""

    def __init__(self, parent, doc, ctx):
        super().__init__(parent, "Lettering")
        self.doc = doc.copy()
        self.ctx = ctx
        self.choice = dict(lettering.clean(doc.lettering))
        self._imgs = []
        tk.Label(self.body, text="Choose the lettering for this label", font="big", bg=BG,
                 fg=INK).pack(anchor="w", pady=(0, 10))
        self.rows = tk.Frame(self.body, bg=BG)
        self.rows.pack(fill="x")
        self.preview = tk.Label(self.body, bg=BG)
        self.preview.pack(pady=(12, 6))
        tk.Label(self.body, text=LEGAL_NOTE, font="small", bg=BG, fg=MUTED, wraplength=560,
                 justify="left").pack(anchor="w")
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        button(row, "Use this lettering", lambda: self.finish(lettering.clean(self.choice)),
               "primary").pack(side="left", padx=(0, 10))
        button(row, "Standard lettering", lambda: self.finish({})).pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")
        self._draw()

    def _draw(self):
        for w in self.rows.winfo_children():
            w.destroy()
        self._imgs = []
        titles = lettering.ROLE_TITLES.get(self.doc.template, ("Name of the food",
                                                                "Everything else"))
        for role, title in zip(("name", "other"), titles):
            if not title:
                continue
            cur = self.choice.get(role) or lettering.DEFAULT
            shown = cur if lettering.get(cur) else lettering.DEFAULT
            r = tk.Frame(self.rows, bg=PANEL, highlightthickness=1, highlightbackground=BORDER,
                         padx=12, pady=8)
            r.pack(fill="x", pady=4)
            tk.Label(r, text=title + ":", font="ui_bold", bg=PANEL, fg=INK, width=16,
                     anchor="w").pack(side="left")
            ph = _photo(cur if shown == cur else f"{cur} (not on this computer)", shown)
            self._imgs.append(ph)
            tk.Label(r, image=ph, bg=PANEL).pack(side="left", padx=8)
            button(r, "Change…", lambda role=role: self._pick(role), "chip").pack(
                side="right")
        self.doc.lettering = lettering.clean(self.choice)
        res = render.render(self.doc, self.ctx)
        img = render.preview(res, 520, 260, highlight=False)
        ph = ImageTk.PhotoImage(img)
        self._imgs.append(ph)
        self.preview.configure(image=ph)

    def _pick(self, role):
        got = FontPicker(self, role, self.choice.get(role) or lettering.DEFAULT).run()
        if got:
            self.choice[role] = got
            if self.doc.template in ("free", "picture"):
                self.choice["other"] = lettering.DEFAULT
        self._draw()


# ---------------------------------------------------------------------------
# the font list
# ---------------------------------------------------------------------------

class FontPicker(Modal):
    """A list of fonts, each name drawn in its own font. Result: family name.

    role "name" lists every font (and can get more); role "other" lists only
    the easy-to-read sans fonts."""

    def __init__(self, parent, role, current):
        title = ("Lettering for the name of the food" if role == "name"
                 else "Lettering for everything else")
        super().__init__(parent, title)
        self.role = role
        self.current = current
        self._imgs = []
        tk.Label(self.body, text=title, font="big", bg=BG, fg=INK).pack(anchor="w")
        if role == "other":
            tk.Label(self.body, text="Only easy-to-read lettering is offered here, so "
                     "the small print stays clear.", font="small", bg=BG, fg=MUTED,
                     wraplength=560, justify="left").pack(anchor="w", pady=(2, 0))
        self.scroll = ScrollFrame(self.body, bg=BG)
        self.scroll.pack(fill="both", expand=True, pady=(10, 0))
        self.scroll.canvas.configure(height=min(520, int(_px() * 1.6 * 7)))
        if role == "name":
            more = tk.Frame(self.body, bg=BG)
            more.pack(fill="x", pady=(10, 0))
            button(more, "Get more fonts…", self._get_more).pack(side="left",
                                                                      padx=(0, 8))
            button(more, "Add a font file from my computer…", self._add_file,
                   "quiet").pack(side="left")
        button(self.body, "Cancel", self.cancel, "quiet").pack(anchor="e", pady=(10, 0))
        self._draw()

    def _faces(self):
        return lettering.name_choices() if self.role == "name" else lettering.other_choices()

    def _draw(self):
        inner = self.scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        self._imgs = []
        mine_started = False
        for face in self._faces():
            if not face.bundled and not mine_started:
                mine_started = True
                tk.Label(inner, text="Fonts you added", font="ui_bold", bg=BG,
                         fg=GREEN_DARK).pack(anchor="w", pady=(10, 2))
            sel = face.key == str(self.current).casefold()
            bg = GREEN_LIGHT if sel else PANEL
            row = tk.Frame(inner, bg=bg, highlightthickness=3,
                           highlightbackground=GREEN if sel else BORDER)
            row.pack(fill="x", pady=3, padx=(0, 6))
            ph = _photo(face.name, face.name, bg=bg)
            self._imgs.append(ph)
            b = tk.Button(row, image=ph, bg=bg, activebackground=GREEN_LIGHT, relief="flat",
                          bd=0, cursor="hand2", anchor="w", padx=10, pady=4,
                          command=lambda n=face.name: self.finish(n))
            b.pack(side="left", fill="x", expand=True)
            if not face.bundled:
                button(row, "Remove", lambda f=face: self._remove(f), "warn").pack(
                    side="right", padx=6)
            elif face.name == lettering.DEFAULT:
                tk.Label(row, text="standard", font="small", bg=bg, fg=MUTED).pack(
                    side="right", padx=10)

    def _get_more(self):
        added = GetFontsDialog(self).run()
        if added:
            self.finish(added)

    def _add_file(self):
        added = add_font_file(self)
        if added:
            self.finish(added)

    def _remove(self, face):
        if not ask(self, "Remove this font?",
                   f"Remove {face.name} from this computer? Labels that use it will be "
                   "shown in the standard lettering until you get it again.",
                   [("Remove", True, "warn"), ("Keep it", False, "normal")]):
            return
        try:
            fontget.remove(face.name)
        except fontget.FontGetError as e:
            tell(self, "Couldn't remove", str(e))
        self._draw()


# ---------------------------------------------------------------------------
# getting more fonts
# ---------------------------------------------------------------------------

class GetFontsDialog(Modal):
    """Type a Google Fonts name, see a preview, add it. Result: family name added."""

    def __init__(self, parent, name: str = ""):
        super().__init__(parent, "Get more fonts")
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        self._candidate = None
        self._imgs = []
        tk.Label(self.body, text="Get more fonts", font="big", bg=BG, fg=INK).pack(anchor="w")
        tk.Label(self.body, text="Type the name of a font from Google Fonts, for example "
                 "“Dancing Script”. You can look at all of them on fonts.google.com.",
                 font="ui", bg=BG, fg=INK, wraplength=600, justify="left").pack(
            anchor="w", pady=(4, 8))
        button(self.body, "Look at fonts.google.com", lambda: webbrowser.open(GOOGLE_FONTS),
               "quiet").pack(anchor="w")
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        self.var = tk.StringVar(master=self, value=name)
        self.entry = tk.Entry(row, textvariable=self.var, font="field", relief="flat",
                              highlightthickness=2, highlightbackground=BORDER,
                              highlightcolor=GREEN, bg="#FFFFFF", fg=INK, width=26)
        self.entry.pack(side="left", ipady=6)
        self.entry.bind("<Return>", lambda e: self._find())
        self.find_btn = button(row, "Find it", self._find, "primary")
        self.find_btn.pack(side="left", padx=10)
        self.status = tk.Label(self.body, text="", font="ui", bg=BG, fg=MUTED,
                               wraplength=600, justify="left")
        self.status.pack(anchor="w", pady=(10, 0))
        self.preview = tk.Label(self.body, bg=BG)
        self.preview.pack(anchor="w", pady=(6, 0))
        bottom = tk.Frame(self.body, bg=BG)
        bottom.pack(fill="x", pady=(14, 0))
        self.add_btn = button(bottom, "Add this font", self._add, "primary", state="disabled")
        self.add_btn.pack(side="left")
        button(bottom, "Close", self.cancel, "quiet").pack(side="right")
        self.entry.focus_set()
        if name:
            self.after(100, self._find)

    def _find(self):
        if self._busy:
            return
        name = self.var.get()
        self._candidate = None
        self.add_btn.configure(state="disabled")
        self.preview.configure(image="")
        self.status.configure(text="Looking for it… (this needs the internet)", fg=MUTED)
        self.find_btn.configure(state="disabled")
        self._busy = True

        def work():
            try:
                self._q.put(("ok", fontget.fetch_family(name)))
            except fontget.FontGetError as e:
                self._q.put(("err", str(e)))
            except Exception:  # noqa: BLE001 - never let a worker die silently
                log.exception("getting font %r", name)
                self._q.put(("err", "Something went wrong getting that font. Please try "
                                    "again later."))
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _poll(self):
        try:
            kind, value = self._q.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(100, self._poll)
            return
        if not self.winfo_exists():
            return
        self._busy = False
        self.find_btn.configure(state="normal")
        if kind == "err":
            self.status.configure(text=value, fg=WARN)
            return
        self._candidate = value
        self.status.configure(text=f"Found {value.name} ({value.license_name}). This is how "
                                   "it looks:", fg=INK)
        try:
            ph = _photo(f"{value.name}: Chicken Soup", data=value.regular,
                        variable=value.variable, height=int(_px() * 1.4), bg=BG)
            self._imgs = [ph]
            self.preview.configure(image=ph)
        except Exception:  # noqa: BLE001
            log.exception("preview")
        self.add_btn.configure(state="normal")

    def _add(self):
        c = self._candidate
        if not c:
            return
        try:
            face = fontget.install(c)
        except fontget.FontGetError as e:
            self.status.configure(text=str(e), fg=WARN)
            return
        self.finish(face.name)


def add_font_file(parent) -> str | None:
    """Pick a .ttf/.otf on this computer, show it, add it. Returns the family name."""
    path = filedialog.askopenfilename(parent=parent, title="Choose a font file",
                                      filetypes=[("Font files", "*.ttf *.otf")])
    if not path:
        return None
    try:
        c = fontget.from_file(path)
    except fontget.FontGetError as e:
        tell(parent, "Can't use that file", str(e))
        return None
    m = Modal(parent, "Add this font?")
    tk.Label(m.body, text=f"This is {c.name}:", font="ui", bg=BG, fg=INK).pack(anchor="w")
    ph = _photo(f"{c.name}: Chicken Soup", data=c.regular, variable=c.variable,
                height=int(_px() * 1.4), bg=BG)
    tk.Label(m.body, image=ph, bg=BG).pack(anchor="w", pady=8)
    tk.Label(m.body, text="Only add fonts you are allowed to use.", font="small", bg=BG,
             fg=MUTED).pack(anchor="w")
    row = tk.Frame(m.body, bg=BG)
    row.pack(fill="x", pady=(12, 0))
    button(row, "Add this font", lambda: m.finish(True), "primary").pack(side="left")
    button(row, "Cancel", m.cancel, "quiet").pack(side="right")
    m._ph = ph
    if not m.run():
        return None
    try:
        return fontget.install(c).name
    except fontget.FontGetError as e:
        tell(parent, "Couldn't add the font", str(e))
        return None


def missing_message(name: str) -> str:
    return (f"This label used the font {name}, which isn't on this computer — showing it "
            "in the standard lettering. Get the font?")


def offer_missing_fonts(parent, doc) -> bool:
    """If the label uses fonts this computer lacks, say so gently and offer to get
    them. Returns True if a font was added (the caller redraws)."""
    added = False
    for name in lettering.missing(doc.lettering):
        if ask(parent, "A font is missing", missing_message(name),
               [("Get the font", True, "primary"), ("Not now", False, "normal")]):
            if GetFontsDialog(parent, name).run():
                added = True
    return added
