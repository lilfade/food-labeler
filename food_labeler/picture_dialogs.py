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

The work (conversion, layout, printer commands) is in pictures.py,
qrcodes.py, extras.py and printsettings.py; these classes only collect
choices and show previews.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog

from PIL import ImageTk

from . import pictures, printers, printsettings, qrcodes, render, settings as settings_mod
from . import stocks
from .widgets import (BG, BORDER, GREEN, INK, MUTED, PANEL, WARN, Modal, ScrollFrame, Toggle,
                      ask, button, tell)

log = logging.getLogger("food_labeler.picture_dialogs")

PREVIEW_W, PREVIEW_H = 520, 300


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
        self.places = (pictures.PLACES_FOR_PICTURE_LABEL if on_picture_label
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
        for p in self.places:
            tk.Radiobutton(left, text=pictures.PLACES[p], variable=self.place, value=p,
                           font="ui", bg=BG, activebackground=BG,
                           command=self._changed).pack(anchor="w")
        if app.doc.stock and stocks.get(self.doc.stock).round and not on_picture_label:
            tk.Label(left, text="On round labels the picture goes above the writing.",
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
        self.brightness = tk.IntVar(value=pic["brightness"])
        self.contrast = tk.IntVar(value=pic["contrast"])
        self.invert = Toggle(left, "Swap black and white", self._changed, pic["invert"])
        self.invert.pack(anchor="w", pady=(8, 2))
        self.remove_bg = Toggle(left, "Remove the background (light parts become paper)",
                                self._changed, pic["remove_bg"])
        self.remove_bg.pack(anchor="w", pady=2)

        tk.Label(right, text="This is exactly what prints", font="ui_bold", bg=BG,
                 fg=INK).pack(anchor="w")
        self.preview = tk.Label(right, bg=BG)
        self.preview.pack(pady=(6, 4))
        self.zoom = tk.Label(right, bg=BG)
        self.zoom.pack(pady=(4, 4))
        self.msg = tk.Label(right, text="", font="ui_bold", bg=BG, fg=WARN, wraplength=PREVIEW_W,
                            justify="left")
        self.msg.pack(anchor="w")

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
                self.threshold.set(pictures.auto_threshold(self._current()))
            _scale(self.mode_box, self.threshold, 1, 254, "Lighter", "Darker",
                   command=self._threshold_moved).pack(anchor="w")
            button(self.mode_box, "Automatic", self._automatic, "chip").pack(anchor="w")

    def _threshold_moved(self):
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
        img = render.preview(res, PREVIEW_W, PREVIEW_H, highlight=False)
        ph = ImageTk.PhotoImage(img)
        self._imgs = [ph]
        self.preview.configure(image=ph)
        zoom = None
        for (_x, _y, pic) in res.layout.images[:1]:
            k = min(1.0, PREVIEW_W / max(1, pic.width), 200 / max(1, pic.height))
            k = max(k, min(3.0, 200 / max(1, pic.height)))
            zoom = render.scaled(pic, k)
        if zoom is not None:
            zph = ImageTk.PhotoImage(zoom)
            self._imgs.append(zph)
            self.zoom.configure(image=zph)
        else:
            self.zoom.configure(image="")
        self.msg.configure(text=res.message if res.overflow else "")

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
        for k, text in qrcodes.WHAT.items():
            tk.Radiobutton(left, text=text, variable=self.what, value=k, font="ui", bg=BG,
                           activebackground=BG, command=self._what_changed).pack(anchor="w")
        self.value = tk.StringVar(value=qr["value"] or self._suggest(qr["what"]))
        self.value_entry = tk.Entry(left, textvariable=self.value, font="field", width=34,
                                    relief="flat", highlightthickness=2,
                                    highlightbackground=BORDER, highlightcolor=GREEN)
        self.value_entry.pack(anchor="w", fill="x", ipady=4, pady=(6, 0))
        self.value.trace_add("write", lambda *a: self._changed())
        _heading(left, "Words under the code (if you want them)")
        self.caption = tk.StringVar(value=qr["caption"])
        tk.Entry(left, textvariable=self.caption, font="field", width=34, relief="flat",
                 highlightthickness=2, highlightbackground=BORDER,
                 highlightcolor=GREEN).pack(anchor="w", fill="x", ipady=4)
        self.caption.trace_add("write", lambda *a: self._changed())
        chips = tk.Frame(left, bg=BG)
        chips.pack(anchor="w", pady=(4, 0))
        for text in ("Scan for our menu", "Scan for ingredients", "Scan to reorder"):
            button(chips, text, lambda t=text: self.caption.set(t), "chip").pack(
                side="left", padx=(0, 4))
        _heading(left, "Where does it go?")
        self.place = tk.StringVar(value=qr["place"])
        for p in qrcodes.PLACES:
            tk.Radiobutton(left, text=pictures.PLACES[p], variable=self.place, value=p,
                           font="ui", bg=BG, activebackground=BG,
                           command=self._changed).pack(anchor="w")
        _heading(left, "How big?")
        self.size = tk.IntVar(value=qr["size"])
        _scale(left, self.size, *qrcodes.SIZE_RANGE, "Smaller", "Bigger",
               command=self._changed).pack(anchor="w")

        tk.Label(right, text="This is exactly what prints", font="ui_bold", bg=BG,
                 fg=INK).pack(anchor="w")
        self.preview = tk.Label(right, bg=BG)
        self.preview.pack(pady=(6, 4))
        self.holds = tk.Label(right, text="", font="small", bg=BG, fg=MUTED,
                              wraplength=PREVIEW_W, justify="left")
        self.holds.pack(anchor="w")
        self.msg = tk.Label(right, text="", font="ui_bold", bg=BG, fg=WARN, wraplength=PREVIEW_W,
                            justify="left")
        self.msg.pack(anchor="w", pady=(6, 0))

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

    def _draw(self):
        self._job = None
        cur = self._current()
        self.doc.qr = cur
        res = render.render(self.doc, self.app.render_ctx(), dpi=self.dpi)
        img = render.preview(res, PREVIEW_W, PREVIEW_H, highlight=False)
        ph = ImageTk.PhotoImage(img)
        self._imgs = [ph]
        self.preview.configure(image=ph)
        text = qrcodes.payload(cur)
        self.holds.configure(text=f"The code holds: {text}" if text else
                             "Type what the code should hold.")
        self.msg.configure(text=res.message if res.overflow else "")

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
        super().__init__(parent, "Print settings")
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

        _heading(b, "Labels in the printer")
        self.media = tk.StringVar(value=ps.get("media", "gap"))
        for k, text in printsettings.MEDIA.items():
            tk.Radiobutton(b, text=text, variable=self.media, value=k, font="ui", bg=BG,
                           activebackground=BG).pack(anchor="w")
        self.gap = tk.StringVar(value=str(ps.get("gap", {}).get(st.id, self.base_gap)))
        if kind == "tspl":
            row = tk.Frame(b, bg=BG)
            row.pack(anchor="w", pady=(4, 0))
            tk.Label(row, text=f"Space between {st.name} labels (mm):", font="ui",
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

        row = tk.Frame(b, bg=BG)
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

