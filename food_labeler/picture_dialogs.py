"""Windows for pictures, QR codes and print settings (plain words only).

* ``PictureDialog`` — add or change the label's picture: open a file or pick
  one from My pictures, where it goes, how big, and how it turns into black
  and white, with a live preview of exactly what prints (at the printer's
  resolution). Result: a picture dict, "remove", or None (cancel).
* ``MyPicturesDialog`` — the pictures kept in the data folder. Result: id.
* ``QrDialog`` — what the QR code holds, its caption, where and how big.
  Result: a QR dict, "remove", or None.
* ``PrintSettingsDialog`` — darkness, speed, nudging, upside down, gap,
  media, what happens after printing, per printer; "Feed one blank label"
  and "Darkness test" (only on click, after saying what it will use).
* ``RollSetupDialog`` — "New roll? Set it up…": put the roll in, say what is
  on it, set it up (only after "This feeds 2–4 blank labels. OK?"), then an
  optional line-up label and help if it's off. Result: the size set up.

The work (conversion, layout, printer commands) is in pictures.py,
qrcodes.py, extras.py, printsettings.py and calibrate.py; these classes only collect
choices and show previews.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog

from PIL import ImageTk

from . import pictures, printers, printsettings, qrcodes, render, settings as settings_mod
from . import calibrate, extras, stocks
from .widgets import (BG, BORDER, GREEN, INK, MUTED, PANEL, WARN, FlowFrame, Modal, ScrollFrame,
                      Toggle, ask, button, tell)

log = logging.getLogger("food_labeler.picture_dialogs")

PREVIEW_W, PREVIEW_H = 520, 300


def preview_size(win) -> tuple[int, int]:
    """The preview in the Picture and QR code windows: smaller on a small screen,
    so the window fits without scrolling."""
    return (PREVIEW_W, PREVIEW_H) if win.winfo_screenheight() >= 900 else (440, 230)


def show_line(label, text, after):
    """A warning line that takes no room when there is nothing to say."""
    label.configure(text=text)
    if text:
        if not label.winfo_manager():
            label.pack(anchor="w", after=after)
    else:
        label.pack_forget()


def _scale(parent, var, lo, hi, left, right, resolution=1, command=None, length=300):
    """A slider with plain words at both ends ("Lighter ←→ Darker")."""
    row = tk.Frame(parent, bg=BG)
    tk.Label(row, text=left, font="ui", bg=BG, fg=MUTED).pack(side="left")
    tk.Scale(row, from_=lo, to=hi, resolution=resolution, orient="horizontal", variable=var,
             font="small", length=length, bg=BG, highlightthickness=0, showvalue=True,
             command=(lambda _v: command()) if command else None).pack(side="left", padx=8)
    tk.Label(row, text=right, font="ui", bg=BG, fg=MUTED).pack(side="left")
    return row


def _heading(parent, text, pady=(12, 2)):
    tk.Label(parent, text=text, font="ui_bold", bg=BG, fg=INK).pack(anchor="w", pady=pady)


# ---------------------------------------------------------------------------
# picture
# ---------------------------------------------------------------------------

class PictureDialog(Modal):
    """Add/change the label's picture with a live preview of what prints."""

    def __init__(self, parent, app):
        super().__init__(parent, "Picture on the label")
        self.app = app
        self.doc = app.doc.copy()
        self.dpi = app.current_dpi()
        self.library = pictures.Library(settings_mod.data_dir())
        on_picture_label = self.doc.template == "picture"
        round_label = stocks.get(self.doc.stock).round
        self.places = (pictures.PLACES_FOR_PICTURE_LABEL if on_picture_label
                       else pictures.PLACES_ON_ROUND if round_label
                       else pictures.PLACES_FOR_OTHERS)
        pic = pictures.clean(self.doc.picture)
        if pic is None:
            pic = dict(pictures.DEFAULTS, png="")
            if on_picture_label:
                pic.update(place="fit", size=100)
        if pic["place"] not in self.places:
            pic["place"] = self.places[0]
        self.pic = pic
        self._job = None
        self._imgs = []

        b = self.body
        top = tk.Frame(b, bg=BG)
        top.pack(fill="x")
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="y", anchor="n")
        right = tk.Frame(top, bg=BG)
        right.pack(side="left", fill="both", padx=(20, 0), anchor="n")

        tk.Label(left, text="Picture on the label", font="big", bg=BG, fg=INK).pack(anchor="w")
        row = tk.Frame(left, bg=BG)
        row.pack(anchor="w", pady=(6, 0))
        button(row, "Open a picture file…", self._open).pack(side="left", padx=(0, 8))
        button(row, "My pictures…", self._library).pack(side="left")
        self.name_lbl = tk.Label(left, text="", font="small", bg=BG, fg=MUTED)
        self.name_lbl.pack(anchor="w", pady=(4, 0))

        _heading(left, "Where does it go?")
        self.place = tk.StringVar(value=pic["place"])
        grid = tk.Frame(left, bg=BG)             # two columns, to keep the window short
        grid.pack(anchor="w")
        for n, p in enumerate(self.places):
            tk.Radiobutton(grid, text=pictures.PLACES[p], variable=self.place, value=p,
                           font="ui", bg=BG, activebackground=BG,
                           command=self._changed).grid(row=n // 2, column=n % 2, sticky="w",
                                                       padx=(0, 16))
        if round_label and not on_picture_label:
            tk.Label(left, text="On round labels the picture goes above or below the writing.",
                     font="small", bg=BG, fg=MUTED).pack(anchor="w")

        _heading(left, "How big?")
        self.size = tk.IntVar(value=pic["size"])
        _scale(left, self.size, *pictures.SIZE_RANGE, "Smaller", "Bigger",
               command=self._changed).pack(anchor="w")

        _heading(left, "Black and white")
        self.mode = tk.StringVar(value=pic["mode"])
        for m, text in pictures.MODES.items():
            tk.Radiobutton(left, text=text, variable=self.mode, value=m, font="ui", bg=BG,
                           activebackground=BG, command=self._mode_changed).pack(anchor="w")
        self.mode_box = tk.Frame(left, bg=BG)
        self.mode_box.pack(anchor="w", fill="x")
        self.threshold = tk.IntVar(value=pic["threshold"] or 128)
        self.auto = pic["threshold"] is None
        self._auto_value = None
        self.brightness = tk.IntVar(value=pic["brightness"])
        self.contrast = tk.IntVar(value=pic["contrast"])

        tk.Label(right, text="This is exactly what prints", font="ui_bold", bg=BG,
                 fg=INK).pack(anchor="w")
        self.preview = tk.Label(right, bg=BG)
        self.preview.pack(pady=(6, 4))
        # a safety net: say so when the picture would print as a mostly black block
        self.black_lbl = tk.Label(right, text="", font="ui", bg=BG, fg=WARN,
                                  wraplength=preview_size(self)[0], justify="left")
        self.black_lbl.pack(anchor="w")       # shown by _draw only when needed
        under = self.under = tk.Frame(right, bg=BG)
        under.pack(anchor="w", fill="x", pady=(4, 4))
        self.zoom = tk.Label(under, bg=BG)
        self.zoom.pack(side="left", anchor="n")
        toggles = tk.Frame(under, bg=BG)
        toggles.pack(side="left", anchor="n", padx=(14, 0))
        self.msg = tk.Label(right, text="", font="ui_bold", bg=BG, fg=WARN,
                            wraplength=preview_size(self)[0], justify="left")
        self.msg.pack(anchor="w")
        # beside the close-up (not in the left column) so the window fits a laptop screen
        self.invert = Toggle(toggles, "Swap black and white", self._changed, pic["invert"])
        self.invert.pack(anchor="w", pady=(0, 4))
        self.remove_bg = Toggle(toggles, "Remove the background", self._changed,
                                pic["remove_bg"])
        self.remove_bg.pack(anchor="w")
        tk.Label(toggles, text="(light parts become paper)", font="small", bg=BG,
                 fg=MUTED).pack(anchor="w")
        self.swapped = tk.Label(toggles, text="", font="small", bg=BG, fg=WARN,
                                wraplength=220, justify="left")
        self.swapped.pack(anchor="w", pady=(4, 0))

        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        button(row, "Use this picture", self._done, "primary").pack(side="left", padx=(0, 8))
        button(row, "Keep in My pictures", self._keep).pack(side="left", padx=(0, 8))
        if app.doc.picture:
            button(row, "Take the picture off", lambda: self.finish("remove"),
                   "warn").pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")
        self._mode_controls()
        self._show_name()
        self._draw()

    # ---- choosing the picture --------------------------------------------
    def _use_image(self, im, name):
        try:
            png = pictures.encode(im)
        except Exception:  # noqa: BLE001
            log.exception("could not keep picture")
            tell(self, "Picture", "Food Labeler couldn't use this picture.")
            return
        self.pic["png"], self.pic["name"] = png, name
        self.pic["threshold"] = None
        self.auto = True
        self._mode_controls()
        self._show_name()
        self._changed()

    def _open(self):
        path = filedialog.askopenfilename(parent=self, title="Choose a picture",
                                          filetypes=pictures.OPEN_TYPES)
        if not path:
            return
        try:
            im, name = pictures.read_file(path)
        except pictures.PictureError as e:
            tell(self, "Picture", str(e))
            return
        self._use_image(im, name)

    def _library(self):
        pid = MyPicturesDialog(self, self.library).run()
        if not pid:
            return
        try:
            im, name = self.library.load(pid)
        except (pictures.PictureError, OSError) as e:
            tell(self, "Picture", str(e) if isinstance(e, pictures.PictureError)
                 else "That picture couldn't be opened.")
            return
        self._use_image(im, name)

    def _keep(self):
        if not self.pic.get("png"):
            tell(self, "My pictures", "Choose a picture first.")
            return
        try:
            self.library.add(self.pic, self.pic.get("name") or "My picture")
            tell(self, "My pictures", "Kept. Next time it is one click under "
                 "“My pictures…”.")
        except OSError:
            log.exception("could not keep picture")
            tell(self, "My pictures", "Food Labeler couldn't keep the picture.")

    def _show_name(self):
        self.name_lbl.configure(text=self.pic.get("name") or (
            "No picture chosen yet" if not self.pic.get("png") else "Picture"))

    # ---- settings ------------------------------------------------------------
    def _mode_changed(self):
        self._mode_controls()
        self._changed()

    def _mode_controls(self):
        for w in self.mode_box.winfo_children():
            w.destroy()
        if self.mode.get() == "photo":
            _scale(self.mode_box, self.brightness, -100, 100, "Darker", "Brighter",
                   command=self._changed).pack(anchor="w")
            _scale(self.mode_box, self.contrast, -100, 100, "Softer", "More contrast",
                   command=self._changed).pack(anchor="w")
        else:
            if self.auto and self.pic.get("png"):
                self._auto_value = pictures.auto_threshold(self._current())
                self.threshold.set(self._auto_value)
            _scale(self.mode_box, self.threshold, 1, 254, "Lighter", "Darker",
                   command=self._threshold_moved).pack(anchor="w")
            button(self.mode_box, "Automatic", self._automatic, "chip").pack(anchor="w")

    def _threshold_moved(self):
        # Tk also calls this when the slider is first shown; only a real move
        # (to another value than the automatic one) switches Automatic off.
        if self.auto and int(self.threshold.get()) == self._auto_value:
            return
        self.auto = False
        self._changed()

    def _automatic(self):
        self.auto = True
        self._mode_controls()
        self._changed()

    def _current(self) -> dict:
        p = dict(self.pic)
        p.update(place=self.place.get(), size=int(self.size.get()), mode=self.mode.get(),
                 brightness=int(self.brightness.get()), contrast=int(self.contrast.get()),
                 invert=self.invert.value, remove_bg=self.remove_bg.value)
        # "Darker" (right) = a higher threshold: more of the picture turns black
        p["threshold"] = None if self.auto else int(self.threshold.get())
        return p

    def _changed(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(120, self._draw)

    def _draw(self):
        self._job = None
        cur = pictures.clean(self._current())
        self.doc.picture = cur
        res = render.render(self.doc, self.app.render_ctx(), dpi=self.dpi)
        img = render.preview(res, *preview_size(self), highlight=False)
        ph = ImageTk.PhotoImage(img)
        self._imgs = [ph]
        self.preview.configure(image=ph)
        zoom = None
        black = ""
        for (_x, _y, pic) in res.layout.images[:1]:
            black = pictures.mostly_black_warning(pictures.black_share(pic), cur["mode"]
                                                  if cur else "logo",
                                                  bool(cur and cur.get("invert")))
            k = min(1.0, 160 / max(1, pic.width), 160 / max(1, pic.height))
            k = max(k, min(3.0, 160 / max(1, pic.height)))
            zoom = render.scaled(pic, k)
        if zoom is not None:
            zph = ImageTk.PhotoImage(zoom)
            self._imgs.append(zph)
            self.zoom.configure(image=zph)
        else:
            self.zoom.configure(image="")
        show_line(self.msg, res.message if res.overflow else "", self.under)
        show_line(self.black_lbl, black, self.preview)
        self.swapped.configure(text="Black and white are swapped: the light parts of "
                               "your picture will print black." if self.invert.value else "")

    def _done(self):
        cur = pictures.clean(self._current())
        if cur is None:
            tell(self, "Picture", "Choose a picture first: “Open a picture file…”.")
            return
        self.finish(cur)


class MyPicturesDialog(Modal):
    """Pictures kept in My pictures: use one, or take it out of the list."""

    def __init__(self, parent, library: pictures.Library):
        super().__init__(parent, "My pictures")
        self.library = library
        self._imgs = []
        tk.Label(self.body, text="My pictures", font="big", bg=BG, fg=INK).pack(anchor="w")
        self.scroll = ScrollFrame(self.body, bg=BG)
        self.scroll.pack(fill="both", expand=True, pady=(10, 0))
        self.scroll.canvas.configure(height=420, width=560)
        button(self.body, "Cancel", self.cancel, "quiet").pack(anchor="e", pady=(10, 0))
        self._draw()

    def _draw(self):
        inner = self.scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        self._imgs = []
        items = self.library.items()
        if not items:
            tk.Label(inner, text="Nothing here yet. After choosing a picture, press "
                     "“Keep in My pictures”.", font="ui", bg=BG, fg=MUTED, wraplength=520,
                     justify="left").pack(anchor="w")
        for it in items:
            row = tk.Frame(inner, bg=PANEL, highlightthickness=1, highlightbackground=BORDER,
                           padx=10, pady=6)
            row.pack(fill="x", pady=3)
            try:
                im, _ = self.library.load(it["id"])
                im = im.copy()
                im.thumbnail((90, 60))
                ph = ImageTk.PhotoImage(im)
                self._imgs.append(ph)
                tk.Label(row, image=ph, bg=PANEL).pack(side="left")
            except (pictures.PictureError, OSError):
                pass
            tk.Label(row, text=it.get("name") or "Picture", font="ui", bg=PANEL, fg=INK).pack(
                side="left", padx=10)
            button(row, "Take out", lambda i=it["id"]: self._remove(i), "warn").pack(
                side="right", padx=4)
            button(row, "Use this", lambda i=it["id"]: self.finish(i), "primary").pack(
                side="right", padx=4)

    def _remove(self, pid):
        if ask(self, "My pictures", "Take this picture out of My pictures? Labels that use "
               "it keep their own copy.", [("Take it out", True, "warn"),
                                           ("Keep it", False, "normal")]):
            self.library.remove(pid)
            self._draw()


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------

class QrDialog(Modal):
    """Add/change the label's QR code."""

    def __init__(self, parent, app):
        super().__init__(parent, "QR code on the label")
        self.app = app
        self.doc = app.doc.copy()
        self.dpi = app.current_dpi()
        qr = qrcodes.clean(self.doc.qr) or dict(qrcodes.DEFAULTS)
        self.profile = dict(getattr(app, "profile", None).data) if getattr(
            app, "profile", None) is not None else {}
        self._job = None
        self._imgs = []
        b = self.body
        top = tk.Frame(b, bg=BG)
        top.pack(fill="x")
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="y", anchor="n")
        right = tk.Frame(top, bg=BG)
        right.pack(side="left", padx=(20, 0), anchor="n")

        tk.Label(left, text="QR code on the label", font="big", bg=BG, fg=INK).pack(anchor="w")
        _heading(left, "What should it hold?")
        self.what = tk.StringVar(value=qr["what"])
        whats = tk.Frame(left, bg=BG)
        whats.pack(anchor="w")
        for i, (k, text) in enumerate(qrcodes.WHAT.items()):
            tk.Radiobutton(whats, text=text, variable=self.what, value=k, font="ui", bg=BG,
                           activebackground=BG, command=self._what_changed).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 16))
        self.value = tk.StringVar(value=qr["value"] or self._suggest(qr["what"]))
        self.value_entry = tk.Entry(left, textvariable=self.value, font="field", width=28,
                                    relief="flat", highlightthickness=2,
                                    highlightbackground=BORDER, highlightcolor=GREEN)
        self.value_entry.pack(anchor="w", fill="x", ipady=4, pady=(6, 0))
        self.value.trace_add("write", lambda *a: self._changed())
        _heading(left, "Words under the code (if you want them)")
        self.caption = tk.StringVar(value=qr["caption"])
        tk.Entry(left, textvariable=self.caption, font="field", width=28, relief="flat",
                 highlightthickness=2, highlightbackground=BORDER,
                 highlightcolor=GREEN).pack(anchor="w", fill="x", ipady=4)
        self.caption.trace_add("write", lambda *a: self._changed())
        chips = FlowFrame(left, bg=BG, gap_x=4, gap_y=4)    # as many to a row as fit
        chips.pack(fill="x", pady=(4, 0))
        for text in ("Scan for our menu", "Scan for ingredients", "Scan to reorder"):
            chips.add(button(chips, text, lambda t=text: self.caption.set(t), "chip"))
        _heading(left, "How big?")
        self.size = tk.IntVar(value=qr["size"])
        row = _scale(left, self.size, *qrcodes.SIZE_RANGE, "Smaller", "Bigger",
                     command=self._changed)
        row.pack(anchor="w")
        # the slider only goes from the smallest size that still scans to the biggest
        # that leaves room for the writing (extras.qr_size_range), so neither end
        # can be a size that doesn't print
        self.size_scale = next(w for w in row.winfo_children() if isinstance(w, tk.Scale))
        self.size_words = tk.Label(left, text="", font="small", bg=BG, fg=MUTED,
                                   wraplength=420, justify="left")
        self.size_words.pack(anchor="w")
        self._range_key = None
        self._range = None
        tk.Label(right, text="This is exactly what prints", font="ui_bold", bg=BG,
                 fg=INK).pack(anchor="w")
        self.preview = tk.Label(right, bg=BG)
        self.preview.pack(pady=(6, 4))
        self.holds = tk.Label(right, text="", font="small", bg=BG, fg=MUTED,
                              wraplength=preview_size(self)[0], justify="left")
        self.holds.pack(anchor="w")
        self.msg = tk.Label(right, text="", font="ui_bold", bg=BG, fg=WARN,
                            wraplength=preview_size(self)[0], justify="left")
        self.msg.pack(anchor="w", pady=(6, 0))
        _heading(right, "Where does it go?")
        round_label = stocks.get(self.doc.stock).round
        places = (pictures.PLACES_ON_ROUND if round_label and self.doc.template != "picture"
                  else qrcodes.PLACES)
        if qr["place"] not in places:
            qr["place"] = "bottom" if qr["place"] in extras.BOTTOM_PLACES else "above"
        self.place = tk.StringVar(value=qr["place"])
        grid = tk.Frame(right, bg=BG)
        grid.pack(anchor="w")
        for n, p in enumerate(places):           # two columns, to keep the window short
            tk.Radiobutton(grid, text=pictures.PLACES[p], variable=self.place, value=p,
                           font="ui", bg=BG, activebackground=BG,
                           command=self._changed).grid(row=n // 2, column=n % 2, sticky="w",
                                                       padx=(0, 16))


        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        button(row, "Use this QR code", self._done, "primary").pack(side="left", padx=(0, 8))
        if app.doc.qr:
            button(row, "Take the QR code off", lambda: self.finish("remove"),
                   "warn").pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")
        self._draw()

    def _suggest(self, what):
        p = self.profile
        return {"link": p.get("website", ""), "phone": p.get("phone", ""),
                "email": p.get("email", "")}.get(what, "") or ""

    def _what_changed(self):
        cur = self.value.get().strip()
        others = {self._suggest(k) for k in ("link", "phone", "email")}
        if not cur or cur in others:
            self.value.set(self._suggest(self.what.get()))
        self._changed()

    def _current(self) -> dict:
        return qrcodes.clean({"what": self.what.get(), "value": self.value.get(),
                              "caption": self.caption.get(), "place": self.place.get(),
                              "size": int(self.size.get())})

    def _changed(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(150, self._draw)

    def _update_range(self, cur):
        """Limit the slider to the sizes that print for what the code holds now."""
        key = (qrcodes.payload(cur), cur["place"], cur["caption"])
        if key == self._range_key:
            return
        self._range_key = key
        stock = stocks.get(self.doc.stock, self.dpi)
        rng = extras.qr_size_range(self.doc, stock, self.app.render_ctx())
        self._range = rng
        lo, hi = rng if rng else qrcodes.SIZE_RANGE
        self.size_scale.configure(from_=lo, to=max(lo, hi),
                                  state="normal" if rng and hi > lo else "disabled")
        v = int(self.size.get())
        if rng and not lo <= v <= hi:
            self.size.set(max(lo, min(hi, v)))
            cur["size"] = int(self.size.get())
            self.doc.qr = cur

    def _draw(self):
        self._job = None
        cur = self._current()
        self.doc.qr = cur
        if qrcodes.payload(cur):
            self._update_range(cur)
            stock = stocks.get(self.doc.stock, self.dpi)
            if self._range is None:
                words = ("This is too much for a QR code on this label. Shorten what it "
                         "holds, or pick a bigger label.")
            else:
                words = extras.qr_size_words(self.doc, stock, int(self.size.get()))
                if self._range[0] == self._range[1]:
                    words += ". This is the only size that fits on this label."
            self.size_words.configure(text=words)
        else:
            self.size_words.configure(text="")
        res = render.render(self.doc, self.app.render_ctx(), dpi=self.dpi)
        img = render.preview(res, *preview_size(self), highlight=False)
        ph = ImageTk.PhotoImage(img)
        self._imgs = [ph]
        self.preview.configure(image=ph)
        text = qrcodes.payload(cur)
        self.holds.configure(text=f"The code holds: {text}" if text else
                             "Type what the code should hold.")
        show_line(self.msg, res.message if res.overflow else "", self.holds)

    def _done(self):
        cur = self._current()
        if not qrcodes.payload(cur):
            tell(self, "QR code", "Type what the QR code should hold first (for example "
                 "your website).")
            return
        self.finish(cur)


# ---------------------------------------------------------------------------
# print settings
# ---------------------------------------------------------------------------

class PrintSettingsDialog(Modal):
    """Per-printer print settings in plain words, with "Reset to normal"."""

    def __init__(self, parent, app, printer):
        super().__init__(parent, "Print settings" + (f" {printers.ALPHA_TAG}"
                                                      if printer.alpha else ""))
        self.app = app
        self.p = printer
        info = app.cfg["printers"].get(printer.id, {})
        self.kind = app.printer_config(printer)["kind"]
        self.stock = stocks.get(app.doc.stock, app.printer_dpi(printer))
        self.adv = app.cfg["advanced"]
        self.old = printsettings.clean(info.get("print"))
        fam = printer.family
        st, ps, adv, kind = self.stock, self.old, self.adv, self.kind
        self.base_dark = printsettings.effective_darkness(kind, st, {}, adv, fam)
        self.base_speed = printsettings.effective_speed(kind, st, {}, adv, fam)
        self.base_gap = printsettings.tspl_values(st, {}, adv, fam)["gap_mm"]
        if self.base_gap is None:
            self.base_gap = st.gap_mm

        b = self.body
        tk.Label(b, text=f"Print settings for {app.printer_name(printer)}", font="big",
                 bg=BG, fg=INK, wraplength=640, justify="left").pack(anchor="w")
        tk.Label(b, text="Remembered for this printer. If you are not sure, leave them as "
                 "they are.", font="small", bg=BG, fg=MUTED).pack(anchor="w")
        roll = tk.Frame(b, bg=BG)
        roll.pack(anchor="w", pady=(10, 0))
        button(roll, "New roll? Set it up\u2026", self._new_roll, "primary").pack(side="left")
        tk.Label(roll, text="  Do this after putting in a new roll, so labels line up.",
                 font="small", bg=BG, fg=MUTED).pack(side="left")

        # two columns, so the window fits a laptop screen
        cols = tk.Frame(b, bg=BG)
        cols.pack(fill="x")
        b = tk.Frame(cols, bg=BG)
        b.pack(side="left", anchor="n", padx=(0, 30))
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", anchor="n")

        _heading(b, "Darkness")
        lo, hi = printsettings.ZPL_DARKNESS if kind == "zpl" else printsettings.TSPL_DARKNESS
        self.dark = tk.IntVar(value=printsettings.effective_darkness(kind, st, ps, adv, fam))
        _scale(b, self.dark, lo, hi, "Lighter", "Darker").pack(anchor="w")

        _heading(b, "Speed")
        lo, hi = printsettings.ZPL_SPEED if kind == "zpl" else printsettings.TSPL_SPEED
        self.speed = tk.IntVar(value=printsettings.effective_speed(kind, st, ps, adv, fam))
        _scale(b, self.speed, lo, hi, "Slower (sharper)", "Faster").pack(anchor="w")

        _heading(b, "Nudge the print (if it isn't in the middle of the label)")
        self.nx = tk.DoubleVar(value=ps.get("nudge_x", 0.0))
        self.ny = tk.DoubleVar(value=ps.get("nudge_y", 0.0))
        n = printsettings.NUDGE_MM
        _scale(b, self.nx, -n, n, "Move left", "Move right (mm)", resolution=0.5).pack(
            anchor="w")
        _scale(b, self.ny, -n, n, "Move up", "Move down (mm)", resolution=0.5).pack(anchor="w")
        self.upside = Toggle(b, "Print upside down (for printers that feed the other way)",
                             None, ps.get("upside_down", False))
        self.upside.pack(anchor="w", pady=(6, 0))

        b = right
        _heading(b, "Labels in the printer")
        self.media = tk.StringVar(value=ps.get("media", "gap"))
        for k, text in printsettings.MEDIA.items():
            tk.Radiobutton(b, text=text, variable=self.media, value=k, font="ui", bg=BG,
                           activebackground=BG).pack(anchor="w")
        self.gap = tk.StringVar(value=str(ps.get("gap", {}).get(st.id, self.base_gap)))
        if kind == "tspl":
            row = tk.Frame(b, bg=BG)
            row.pack(anchor="w", pady=(4, 0))
            tk.Label(row, text="Gap between labels (mm):", font="ui",
                     bg=BG).pack(side="left")
            tk.Entry(row, textvariable=self.gap, font="ui", width=6).pack(side="left", padx=6)

        _heading(b, "After printing")
        self.after_ = tk.StringVar(value=ps.get("after", "tear"))
        for k, text in printsettings.AFTER.items():
            tk.Radiobutton(b, text=text, variable=self.after_, value=k, font="ui", bg=BG,
                           activebackground=BG).pack(anchor="w")

        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        button(row, "Feed one blank label", self._feed, "chip").pack(side="left", padx=(0, 6))
        button(row, "Darkness test", self._test, "chip").pack(side="left")

        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        button(row, "Save", self._save, "primary").pack(side="left", padx=(0, 8))
        button(row, "Reset to normal", self._reset).pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")

    def collect(self) -> dict:
        """The settings as chosen; only what differs from normal is kept."""
        ps: dict = {}
        k = "zpl_" if self.kind == "zpl" else ""
        if int(self.dark.get()) != self.base_dark or f"{k}darkness" in self.old:
            ps[f"{k}darkness"] = int(self.dark.get())
        if int(self.speed.get()) != self.base_speed or f"{k}speed" in self.old:
            ps[f"{k}speed"] = int(self.speed.get())
        # the other language's values stay (the printer's Type might be changed back)
        other = "" if self.kind == "zpl" else "zpl_"
        for key in (f"{other}darkness", f"{other}speed"):
            if key in self.old:
                ps[key] = self.old[key]
        ps["nudge_x"], ps["nudge_y"] = float(self.nx.get()), float(self.ny.get())
        if self.upside.value:
            ps["upside_down"] = True
        gaps = dict(self.old.get("gap", {}))
        try:
            g = float(self.gap.get())
            if abs(g - float(self.base_gap)) > 1e-9 or self.stock.id in gaps:
                gaps[self.stock.id] = g
        except ValueError:
            pass
        if gaps:
            ps["gap"] = gaps
        # media and "after printing" are sent once changed, so going back to normal
        # also tells the printer
        if self.media.get() != "gap" or "media" in self.old:
            ps["media"] = self.media.get()
        if self.after_.get() != "tear" or "after" in self.old:
            ps["after"] = self.after_.get()
            if ps["after"] == "feed":
                ps["feed_mm"] = self.old.get("feed_mm", printsettings.DEFAULT_FEED_MM)
        return printsettings.clean(ps)

    def _store(self, ps):
        info = self.app.cfg.printer_info(self.p.id)
        if ps:
            info["print"] = ps
        else:
            info.pop("print", None)
        self.app.cfg.save()

    def _save(self):
        self._store(self.collect())
        self.finish(True)

    def _reset(self):
        if ask(self, "Reset to normal", "Put every print setting for this printer back to "
               "normal?", [("Yes, reset", True, "primary"), ("No", False, "normal")]):
            self._store({})
            self.finish(True)

    def _send(self, data, done):
        try:
            printers.send(self.app.printer_config(self.p), data)
            tell(self, "Sent", done)
        except printers.PrinterError as e:
            tell(self, "Didn't work", str(e))

    def _new_roll(self):
        """The same set-up window as "Feed / calibrate…" in Advanced. It keeps the
        kind of roll it set up; show that here too (other changes stay unsaved)."""
        if self.app.setup_roll(self, self.p):
            stored = printsettings.clean(self.app.cfg["printers"].get(self.p.id, {})
                                         .get("print"))
            if "media" in stored:
                self.old["media"] = stored["media"]
                self.media.set(stored["media"])

    def _feed(self):
        data = printers.feed_job(self.stock, self.app.printer_config(self.p), self.adv,
                                 self.collect())
        self._send(data, "Sent. The printer should feed one blank label.")

    def _test(self):
        if not ask(self, "Darkness test", "This prints 3 labels, each a little darker than "
                   "the one before and each saying its darkness. It uses 3 labels. Go ahead?",
                   [("Yes, print 3 labels", True, "primary"), ("Cancel", False, "normal")]):
            return
        try:
            data, levels = printers.darkness_test_job(
                self.stock, self.app.printer_config(self.p), self.adv, self.p.family,
                self.collect())
        except printers.PrinterError as e:
            tell(self, "Didn't work", str(e))
            return
        nums = ", ".join(str(v) for _w, v in levels)
        self._send(data, f"Sent. Pick the label you like best ({nums}) and move the "
                         "Darkness slider to its number.")



# ---------------------------------------------------------------------------
# new roll (calibration)
# ---------------------------------------------------------------------------

class RollSetupDialog(Modal):
    """"New roll? Set it up…": three plain steps, then an optional line-up label.

    Nothing is sent until "Set it up" is pressed *and* the person says OK to
    "This feeds 2–4 blank labels" (calibrate.send_setup). Result: the label
    size id that was set up, or None.
    """

    def __init__(self, parent, app, printer):
        super().__init__(parent, "Set up a new roll")
        self.app = app
        self.p = printer
        self.dpi = app.printer_dpi(printer)
        self.kind = app.printer_config(printer)["kind"]
        self.ps = app.print_settings_for(printer)
        self.done_stock = None
        fam = printer.family
        b = self.body
        tk.Label(b, text=f"Set up a new roll in the {app.printer_name(printer)}", font="big",
                 bg=BG, fg=INK, wraplength=680, justify="left").pack(anchor="w")
        tk.Label(b, text="Do this each time you put in a new roll, so the printing lines up "
                 "with the labels.", font="small", bg=BG, fg=MUTED, wraplength=680,
                 justify="left").pack(anchor="w")

        cols = tk.Frame(b, bg=BG)
        cols.pack(fill="x")
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", anchor="n", padx=(0, 30))
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", anchor="n")

        for text, pady in (("1.  " + calibrate.STEP1, (14, 2)),
                           ("2.  " + calibrate.STEP2, (12, 2))):
            tk.Label(left, text=text, font="ui_bold", bg=BG, fg=INK, wraplength=600,
                     justify="left").pack(anchor="w", pady=pady)
        tk.Label(left, text="Label size", font="ui", bg=BG, fg=MUTED).pack(anchor="w")
        self.stock = tk.StringVar(value=app.doc.stock if app.doc.stock in stocks.STOCKS
                                  else stocks.DEFAULT_STOCK)
        sizes = tk.Frame(left, bg=BG)       # two columns, so the window fits a laptop
        sizes.pack(anchor="w")
        for n, sid in enumerate(stocks.ORDER):
            tk.Radiobutton(sizes, text=stocks.STOCKS[sid].name, variable=self.stock, value=sid,
                           font="ui", bg=BG, activebackground=BG).grid(
                row=n // 2, column=n % 2, sticky="w", padx=(0, 12))
        tk.Label(left, text="Kind of roll", font="ui", bg=BG, fg=MUTED).pack(anchor="w",
                                                                             pady=(8, 0))
        self.media = tk.StringVar(value=calibrate.clean_media(self.ps.get("media")))
        kinds = tk.Frame(left, bg=BG)
        kinds.pack(anchor="w")
        for n, (k, text) in enumerate(calibrate.MEDIA.items()):
            tk.Radiobutton(kinds, text=text, variable=self.media, value=k, font="ui", bg=BG,
                           activebackground=BG, command=self._media_changed).grid(
                row=n // 2, column=n % 2, sticky="w", padx=(0, 12))

        _heading(right, "3.  " + calibrate.STEP3, pady=(14, 2))
        self.note = tk.Label(right, text="", font="ui", bg=BG, fg=INK, wraplength=360,
                             justify="left")
        self.note.pack(anchor="w")
        self.go = button(right, "Set it up", self._set_it_up, "primary", font="big")
        self.go.pack(anchor="w", pady=(8, 0))
        # shown once the roll has been set up
        self.after_frame = tk.Frame(right, bg=BG)
        tk.Label(self.after_frame, text="Want to check it? A test label shows a box just "
                 "inside the edges; the arrow points to the end that comes out first.",
                 font="small", bg=BG, fg=MUTED, wraplength=360, justify="left").pack(
            anchor="w", pady=(12, 4))
        button(self.after_frame, "Print one test label", self._lineup, "chip").pack(anchor="w")
        row = tk.Frame(self.after_frame, bg=BG)
        row.pack(anchor="w", pady=(8, 0))
        button(row, "Looks right", lambda: self.finish(self.done_stock), "primary").pack(
            side="left", padx=(0, 8))
        button(row, "It's off — help me", self._help, "warn").pack(side="left")

        self.fallback = tk.Label(b, text=calibrate.still_not_right(fam), font="small", bg=BG,
                                 fg=MUTED, wraplength=980, justify="left")
        self.fallback.pack(anchor="w", pady=(16, 0))
        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        button(row, "Close", self._close, "quiet").pack(side="right")
        self._media_changed()

    def _stock(self):
        return stocks.get(self.stock.get(), self.dpi)

    def _media_changed(self):
        m = self.media.get()
        if m == "continuous":
            self.note.configure(text=calibrate.CONTINUOUS_NOTE)
            self.go.configure(text="Set the size")
        else:
            text = "The printer feeds 2–4 blank labels to find where each one starts."
            if m == "mark" and self.kind != "zpl":
                text += "\n\n" + calibrate.MARK_UNVERIFIED
            self.note.configure(text=text)
            self.go.configure(text="Set it up")

    def _keep_media(self, media):
        """The kind of roll also goes into Print settings, so labels print to match."""
        info = self.app.cfg.printer_info(self.p.id)
        ps = printsettings.clean(info.get("print"))
        if media != "gap" or "media" in ps:
            ps["media"] = media
        if ps:
            info["print"] = ps
        self.ps = ps

    def _set_it_up(self):  # not "_setup": tkinter uses that name itself
        stock, media = self._stock(), self.media.get()
        cfgp = self.app.printer_config(self.p)
        try:
            data = calibrate.setup_job_for(stock, cfgp, self.app.cfg["advanced"], media,
                                           self.ps, self.p.family)
            sent = calibrate.send_setup(
                cfgp, data, lambda: ask(self, "Set up the roll", calibrate.confirm_text(media),
                                        [("Yes, set it up", True, "primary"),
                                         ("Cancel", False, "normal")]))
        except printers.PrinterError as e:
            tell(self, "Didn't work", str(e))
            return
        if not sent:
            return
        info = self.app.cfg.printer_info(self.p.id)
        calibrate.remember_roll(info, stock.id, media)
        self._keep_media(media)
        self.app.cfg.save()
        self.done_stock = stock.id
        self.after_frame.pack(anchor="w", fill="x")
        tell(self, "Sent", "Sent. The printer feeds a few labels and stops." if
             calibrate.uses_labels(media) else "Sent. The printer now knows the size.")

    def _lineup(self):
        stock = self._stock()
        cfgp = self.app.printer_config(self.p)
        try:
            data = calibrate.lineup_label_job(stock, cfgp, self.app.cfg["advanced"],
                                              self.p.family, self.ps)
            printers.send(cfgp, data)
        except printers.PrinterError as e:
            tell(self, "Didn't work", str(e))
            return
        tell(self, "Sent", "Sent one test label. Is the box just inside the edges of the "
             "label?")

    def _help(self):
        tell(self, "Let's fix it", calibrate.help_text(self.p.family, self.kind,
                                                       self.media.get()))

    def _close(self):
        self.finish(self.done_stock)
