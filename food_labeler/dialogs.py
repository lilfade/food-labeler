"""The extra windows: pickers, save/open, settings, printers, USB devices, report.

Every dialog is a widgets.Modal: build it, call .run(), get the result back.
Dialogs talk to the main window through the ``app`` they are given (its
cfg, found printers, known models and printing helpers); none of them print
anything unless the user presses a button that says so.
"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageDraw, ImageTk

from . import APP_NAME, BRAND, __version__
from . import dates, known, model, printers, render, report, settings as settings_mod, stocks
from . import templates, usbscan
from .widgets import (BG, BORDER, GREEN, GREEN_DARK, GREEN_LIGHT, INK, MUTED, PANEL, WARN,
                      WARN_BG, Modal, ScrollFrame, ask, button, tell)

log = logging.getLogger("food_labeler.dialogs")

SAMPLE_FIELDS = {
    "simple": {"food": "Chicken Soup", "contains": "Wheat", "note": "Keep refrigerated"},
    "package": {"product": "Lemon Shortbread", "net": "8 oz", "ingredients": "Butter, flour, "
                "sugar, lemon", "contains": "Milk, Wheat", "business": "My Kitchen",
                "address": "123 Garden Lane"},
    "sticker": {"count": "12"},
    "free": {"text": "Happy\nBirthday!"},
    "cottage": {"product": "Lemon Shortbread", "net": "8 oz", "ingredients": "Butter (cream, "
                "salt), flour, sugar, lemon", "contains": "Milk, Wheat"},
    "picture": {"text": "Thank you!"},
}


def sample_picture(doc) -> dict | None:
    """The picture for the Picture label preview: the label's own, else the seal."""
    from . import pictures
    if doc.picture:
        return dict(doc.picture, place="fit", size=100)
    try:
        im = Image.open(Path(__file__).resolve().parent / "assets" / "seal-header-2x.png")
        return pictures.new_picture(pictures.normalise(im), "seal", place="fit", size=100)
    except (OSError, pictures.PictureError):
        return None
KIND_CHOICES = [
    ("Label printer like the LP610BT", "tspl"),
    ("Zebra label printer", "zpl"),
    ("I don't know", "tspl"),
]


def choose(parent, title, message, options, cancel_text="Cancel"):
    """Big vertical list of choices. options: [(text, value)]. Returns value or None."""
    m = Modal(parent, title)
    tk.Label(m.body, text=message, font="ui", bg=BG, fg=INK, wraplength=640,
             justify="left").pack(anchor="w", pady=(0, 14))
    for text, value in options:
        button(m.body, text, lambda v=value: m.finish(v)).pack(fill="x", pady=4)
    if cancel_text:
        button(m.body, cancel_text, m.cancel, "quiet").pack(anchor="e", pady=(12, 0))
    return m.run()


# ---------------------------------------------------------------------------
# template & size pickers
# ---------------------------------------------------------------------------

class TemplatePicker(Modal):
    """Pick the kind of label from live previews of each template. Result: template id."""

    def __init__(self, parent, doc, ctx):
        super().__init__(parent, "Choose the kind of label")
        tk.Label(self.body, text="What kind of label do you want?", font="big", bg=BG,
                 fg=INK).pack(anchor="w", pady=(0, 12))
        grid = tk.Frame(self.body, bg=BG)
        grid.pack()
        self._imgs = []
        cols = 3 if len(model.TEMPLATES) > 4 else 2
        for i, t in enumerate(model.TEMPLATES):
            stock = doc.stock if doc.stock in templates.ALLOWED_STOCKS[t] else "large"
            d = model.LabelDoc(t, stock, model.default_fields(t))
            d.fields.update(SAMPLE_FIELDS[t])
            if t == "picture":
                d.picture = sample_picture(doc)
            res = render.render(d, ctx)
            img = render.preview(res, 300, 170, highlight=False)
            ph = ImageTk.PhotoImage(img)
            self._imgs.append(ph)
            name, hint = templates.TEMPLATE_INFO[t]
            selected = t == doc.template
            b = tk.Button(grid, image=ph, text=f"{name}\n{hint}", compound="top", font="ui",
                          bg=GREEN_LIGHT if selected else PANEL, fg=INK, relief="flat",
                          highlightthickness=3,
                          highlightbackground=GREEN if selected else BORDER, cursor="hand2",
                          padx=10, pady=10, command=lambda t=t: self.finish(t), wraplength=320)
            b.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")
        button(self.body, "Cancel", self.cancel, "quiet").pack(anchor="e", pady=(10, 0))


def stock_picture(st: stocks.Stock, box=130) -> Image.Image:
    """Outline of a label size, drawn to scale with the others (4 x 6 in fills the box)."""
    img = Image.new("RGB", (box + 20, box + 20), BG)
    d = ImageDraw.Draw(img)
    big = 1218.0
    sc = box / big
    w, h = max(14, st.w * sc * 1.0), max(14, st.h * sc * 1.0)
    # make small labels still visible but proportional to each other
    x0, y0 = (img.width - w) / 2, (img.height - h) / 2
    if st.round:
        d.ellipse((x0, y0, x0 + w, y0 + h), fill="white", outline="#7A746A", width=2)
    else:
        d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=4, fill="white",
                            outline="#7A746A", width=2)
    return img


class StockPicker(Modal):
    """Pick the label size; sizes the template can't use are shown disabled. Result: stock id."""

    def __init__(self, parent, template, current):
        super().__init__(parent, "Choose the label size")
        tk.Label(self.body, text="Which labels are in the printer?", font="big", bg=BG,
                 fg=INK).pack(anchor="w", pady=(0, 12))
        allowed = templates.ALLOWED_STOCKS[template]
        self._imgs = []
        grid = tk.Frame(self.body, bg=BG)
        grid.pack()
        for i, sid in enumerate(stocks.ORDER):
            st = stocks.get(sid)
            ph = ImageTk.PhotoImage(stock_picture(st))
            self._imgs.append(ph)
            ok = sid in allowed
            text = f"{st.name}\n{st.hint}" if ok else f"{st.name}\nToo small for this kind of label"
            sel = sid == current
            b = tk.Button(grid, image=ph, text=text, compound="left", font="ui", anchor="w",
                          justify="left", bg=GREEN_LIGHT if sel else PANEL, fg=INK,
                          relief="flat", highlightthickness=3,
                          highlightbackground=GREEN if sel else BORDER, cursor="hand2",
                          padx=10, pady=6, command=lambda s=sid: self.finish(s),
                          state="normal" if ok else "disabled", width=520)
            b.grid(row=i, column=0, sticky="ew", pady=4)
        button(self.body, "Cancel", self.cancel, "quiet").pack(anchor="e", pady=(10, 0))


# ---------------------------------------------------------------------------
# save / open
# ---------------------------------------------------------------------------

class NameDialog(Modal):
    """Save: just a name (kept in the labels folder) or "somewhere else". Result: path."""

    def __init__(self, parent, name, folder: Path):
        super().__init__(parent, "Save your label")
        self.folder = folder
        tk.Label(self.body, text="What should this label be called?", font="big", bg=BG,
                 fg=INK).pack(anchor="w")
        tk.Label(self.body, text=f"It will be kept in “{folder.name}”.", font="ui",
                 bg=BG, fg=MUTED).pack(anchor="w", pady=(4, 10))
        self.var = tk.StringVar(value=name)
        e = tk.Entry(self.body, textvariable=self.var, font="big", width=30, relief="flat",
                     highlightthickness=2, highlightbackground=BORDER, highlightcolor=GREEN)
        e.pack(fill="x", ipady=6)
        e.select_range(0, "end")
        e.focus_set()
        e.bind("<Return>", lambda ev: self._ok())
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        button(row, "Save", self._ok, "primary").pack(side="left")
        button(row, "Save somewhere else…", self._elsewhere).pack(side="left", padx=10)
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")

    def _ok(self):
        name = model.safe_filename(self.var.get())
        path = self.folder / (name + model.EXT)
        if path.exists():
            ans = ask(self, "Replace?",
                      f"There is already a label called “{name}”. Replace it?",
                      [("Replace it", True, "primary"), ("Pick another name", False, "normal")])
            if not ans:
                return
        self.finish(str(path))

    def _elsewhere(self):
        p = filedialog.asksaveasfilename(
            parent=self, title="Save label", initialdir=str(self.folder),
            initialfile=model.safe_filename(self.var.get()) + model.EXT,
            defaultextension=model.EXT, filetypes=[("Labels", "*" + model.EXT)])
        if p:
            self.finish(p)


class OpenDialog(Modal):
    """List of saved labels, newest first, or "look somewhere else". Result: path."""

    def __init__(self, parent, folder: Path):
        super().__init__(parent, "Open a label")
        tk.Label(self.body, text="Which label?", font="big", bg=BG, fg=INK).pack(anchor="w")
        files = []
        try:
            files = sorted(folder.glob("*" + model.EXT), key=lambda p: p.stat().st_mtime,
                           reverse=True)[:60]
        except OSError:
            pass
        sf = ScrollFrame(self.body, bg=BG)
        sf.configure(width=620, height=420)
        sf.pack(fill="both", expand=True, pady=10)
        sf.pack_propagate(False)
        if not files:
            tk.Label(sf.inner, text="You haven't saved any labels yet.", font="ui", bg=BG,
                     fg=MUTED).pack(anchor="w", pady=10)
        for p in files:
            try:
                when = dates.fmt(dates.dt.date.fromtimestamp(p.stat().st_mtime))
            except OSError:
                when = ""
            b = button(sf.inner, f"{p.stem}\n   saved {when}", lambda p=p: self.finish(str(p)))
            b.configure(anchor="w", justify="left")
            b.pack(fill="x", pady=3, padx=2)
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x")
        button(row, "Look somewhere else…", self._elsewhere).pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")
        self.folder = folder

    def _elsewhere(self):
        p = filedialog.askopenfilename(parent=self, title="Open label",
                                       initialdir=str(self.folder),
                                       filetypes=[("Labels", "*" + model.EXT), ("All", "*")])
        if p:
            self.finish(p)


# ---------------------------------------------------------------------------
# print dialog (Ctrl+P)
# ---------------------------------------------------------------------------

class PrintDialog(Modal):
    """Ctrl+P: confirm copies and printer. Result: "print" or None."""

    def __init__(self, parent, app):
        super().__init__(parent, "Print")
        self.app = app
        p = app.current_printer()
        pname = app.printer_name(p) if p else "No printer chosen"
        tk.Label(self.body, text="Print your label", font="big", bg=BG, fg=INK).pack(anchor="w")
        tk.Label(self.body, text=f"Printer: {pname}", font="ui", bg=BG, fg=MUTED).pack(
            anchor="w", pady=(4, 12))
        row = tk.Frame(self.body, bg=BG)
        row.pack(anchor="w")
        tk.Label(row, text="How many?", font="big", bg=BG, fg=INK).pack(side="left")
        button(row, "−", lambda: app.change_copies(-1), font="huge", width=2).pack(
            side="left", padx=(12, 4))
        tk.Label(row, textvariable=app.copies_var, font="huge", bg=BG, fg=INK, width=3).pack(
            side="left")
        button(row, "+", lambda: app.change_copies(1), font="huge", width=2).pack(side="left",
                                                                                  padx=4)
        row2 = tk.Frame(self.body, bg=BG)
        row2.pack(fill="x", pady=(18, 0))
        b = button(row2, "PRINT", lambda: self.finish("print"), "print", font="huge")
        b.configure(padx=40)
        b.pack(side="left")
        button(row2, "Save as picture instead", lambda: (self.cancel(), app.export_picture()),
               "normal").pack(side="left", padx=12)
        button(row2, "Cancel", self.cancel, "quiet").pack(side="right")


# ---------------------------------------------------------------------------
# settings & advanced
# ---------------------------------------------------------------------------

class SettingsDialog(Modal):
    """Text size, date style, kitchen details, printer tools, folders, About."""

    def __init__(self, parent, app):
        super().__init__(parent, "Settings")
        self.app = app
        cfg = app.cfg
        sf = ScrollFrame(self.body, bg=BG)
        sf.configure(width=760, height=min(640, parent.winfo_screenheight() - 200))
        sf.pack_propagate(False)
        sf.pack(fill="both", expand=True)
        b = sf.inner

        def heading(text):
            tk.Label(b, text=text, font="big", bg=BG, fg=GREEN_DARK).pack(anchor="w",
                                                                         pady=(16, 6))
        heading("Text size")
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w")
        button(row, "Smaller text", lambda: app.bigger_text(-1)).pack(side="left")
        button(row, "Bigger text", lambda: app.bigger_text(1)).pack(side="left", padx=8)

        heading("How dates look on simple labels")
        self.style = tk.StringVar(value=cfg["date_style"])
        for key, example in dates.STYLES.items():
            tk.Radiobutton(b, text=example, value=key, variable=self.style, font="ui", bg=BG,
                           activebackground=BG, selectcolor="white",
                           command=self._style).pack(anchor="w")

        heading("My kitchen details (for package labels)")
        k = cfg["kitchen"]
        self.kvars = {}
        for key, title, lines in [("business", "Business name", 1), ("address", "Address", 2),
                                  ("cross_contact", "Cross-contact notice", 3),
                                  ("disclaimer", "Disclaimer", 3)]:
            tk.Label(b, text=title, font="ui_bold", bg=BG, fg=INK).pack(anchor="w", pady=(6, 0))
            t = tk.Text(b, font="field", height=lines, wrap="word", relief="flat",
                        highlightthickness=2, highlightbackground=BORDER, width=50)
            t.insert("1.0", k.get(key, ""))
            t.pack(fill="x")
            self.kvars[key] = t

        heading("My bakery (cottage food labels)")
        tk.Label(b, text="Your state, your bakery's details, the wording on your labels, "
                 "and your saved ingredients and products.", font="ui", bg=BG, fg=MUTED,
                 wraplength=700, justify="left").pack(anchor="w")
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w", pady=(6, 0))
        button(row, "My bakery…", lambda: app.my_bakery(), "primary").pack(side="left")
        button(row, "Set up my bakery", lambda: app.bakery_wizard()).pack(side="left", padx=8)
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w", pady=(8, 0))
        button(row, "My products…", lambda: app.my_products()).pack(side="left")
        button(row, "Back up or restore my ingredients…",
               lambda: _ingredients_backup(self, app)).pack(side="left", padx=8)
        tk.Label(b, text="These are suggestions from public state guidance. You are "
                 "responsible for following your state's rules.", font="small", bg=BG,
                 fg=MUTED, wraplength=700, justify="left").pack(anchor="w", pady=(6, 0))

        heading("Printer")
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w")
        button(row, "Set up my printer", lambda: app.setup_wizard(), "primary").pack(side="left")
        button(row, "My printers…", lambda: app.my_printers()).pack(side="left", padx=8)
        button(row, "Advanced…", lambda: AdvancedDialog(self, app).run()).pack(side="left")
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w", pady=(8, 0))
        button(row, "Add printer update file…", lambda: import_update(self, app)).pack(
            side="left")
        button(row, "Send printer info to High Thyme Kitchen",
               lambda: ReportDialog(self, app).run()).pack(side="left", padx=8)

        heading("Where my labels are kept")
        tk.Label(b, text=str(settings_mod.labels_dir()), font="ui", bg=BG, fg=INK,
                 wraplength=700, justify="left").pack(anchor="w")

        heading("About")
        support = str(known.app_config().get("support_email") or "")
        tk.Label(b, text=f"{APP_NAME} version {__version__}, by {BRAND}"
                 + (f"\nHelp: {support}" if support else ""), font="ui", bg=BG, fg=INK,
                 wraplength=700, justify="left").pack(anchor="w")
        button(self.body, "Done", self._done, "primary").pack(anchor="e", pady=(12, 0))

    def _style(self):
        self.app.cfg["date_style"] = self.style.get()
        self.app.schedule_render()

    def _done(self):
        for key, t in self.kvars.items():
            self.app.cfg["kitchen"][key] = t.get("1.0", "end-1c").strip()
        self.app.cfg.save()
        self.finish(True)


def _ingredients_backup(parent, app):
    from .bakery_dialogs import backup_ingredients
    backup_ingredients(parent, app)


class AdvancedDialog(Modal):
    """Technical settings. This is the only place printer jargon appears."""

    def __init__(self, parent, app):
        super().__init__(parent, "Advanced printer settings")
        self.app = app
        adv = app.cfg["advanced"]
        p = app.current_printer()
        st = stocks.get(app.doc.stock, app.current_dpi())
        b = self.body
        tk.Label(b, text="Advanced (for helpers)", font="big", bg=BG, fg=INK).pack(anchor="w")
        tk.Label(b, text=(f"Label size: {st.name} = {st.w} × {st.h} dots at "
                          f"{st.dpi} DPI ({st.w_mm} × {st.h_mm} mm), gap "
                          f"{adv['gap'].get(st.id, st.gap_mm)} mm"),
                 font="ui", bg=BG, fg=MUTED, wraplength=700, justify="left").pack(anchor="w")
        if p is not None:
            info = app.cfg["printers"].get(p.id, {})
            tk.Label(b, text=(f"Printer: {p.id} via {p.method} → {p.target}; language "
                              f"{(info.get('kind') or p.kind or 'tspl').upper()}; "
                              f"model {p.model or '?'}; USB {p.vidpid or '?'}; detected "
                              f"{p.dpi} dpi"),
                     font="ui", bg=BG, fg=MUTED, wraplength=700, justify="left").pack(anchor="w")
            tk.Label(b, text="Print sharpness (resolution of this printer)", font="ui_bold",
                     bg=BG, fg=INK).pack(anchor="w", pady=(14, 0))
            self.dpi = tk.IntVar(value=app.printer_dpi(p))
            for v in printers.DPI_CHOICES:
                tk.Radiobutton(b, text=printers.DPI_LABELS[v], variable=self.dpi, value=v,
                               font="ui", bg=BG, activebackground=BG).pack(anchor="w")

        tk.Label(b, text=("The darkness, speed and gap below are for each label size on every "
                          "printer. “Print settings…” next to the printer keeps them per "
                          "printer, and those come first."),
                 font="small", bg=BG, fg=MUTED, wraplength=700, justify="left").pack(
            anchor="w", pady=(8, 0))
        fam = p.family if p is not None else None
        d0 = adv["density"].get(st.id)
        if d0 is None:
            d0 = fam.density_for(st.id) if fam is not None else None
        if d0 is None:
            d0 = st.density
        tk.Label(b, text=f"Darkness for {st.name} (TSPL DENSITY 0–15)", font="ui_bold",
                 bg=BG, fg=INK).pack(anchor="w", pady=(14, 0))
        row = tk.Frame(b, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text="Lighter", font="ui", bg=BG).pack(side="left")
        self.density = tk.IntVar(value=int(d0))
        tk.Scale(row, from_=0, to=15, orient="horizontal", variable=self.density, font="ui",
                 length=360, bg=BG, highlightthickness=0).pack(side="left", padx=8)
        tk.Label(row, text="Darker", font="ui", bg=BG).pack(side="left")

        grid = tk.Frame(b, bg=BG)
        grid.pack(anchor="w", pady=(10, 0))
        s0 = adv["speed"].get(st.id) or (fam.speed_for(st.id) if fam is not None else None) \
            or st.speed
        self.speed = tk.StringVar(value=str(s0))
        self.gap = tk.StringVar(value=str(adv["gap"].get(st.id, st.gap_mm)))
        self.zpl_dark = tk.StringVar(value="" if adv.get("zpl_darkness") is None
                                     else str(adv["zpl_darkness"]))
        for r, (label, var) in enumerate([("Speed (TSPL SPEED 1–6)", self.speed),
                                          (f"Gap between labels for {st.name} (mm)", self.gap),
                                          ("Zebra darkness ^MD (blank = normal)", self.zpl_dark)]):
            tk.Label(grid, text=label, font="ui", bg=BG).grid(row=r, column=0, sticky="w")
            tk.Entry(grid, textvariable=var, font="ui", width=8).grid(row=r, column=1, padx=8,
                                                                      pady=3)
        self.via_driver = tk.BooleanVar(
            value=bool(p is not None and app.cfg["printers"].get(p.id, {}).get("via_driver")))
        if p is not None and p.method == "windows_raw":
            tk.Checkbutton(b, text="Print through Windows driver (if raw doesn't work)",
                           variable=self.via_driver, font="ui", bg=BG,
                           activebackground=BG).pack(anchor="w", pady=(8, 0))
        self.printer = p
        self.invert = tk.BooleanVar(value=bool(adv.get("invert")))
        tk.Checkbutton(b, text="Invert colours (if labels print as a black block)",
                       variable=self.invert, font="ui", bg=BG, activebackground=BG).pack(
            anchor="w", pady=(8, 0))

        tk.Label(b, text="Network printer (address:port, e.g. 192.168.1.50:9100)",
                 font="ui_bold", bg=BG, fg=INK).pack(anchor="w", pady=(14, 0))
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w")
        self.net = tk.StringVar()
        tk.Entry(row, textvariable=self.net, font="ui", width=26).pack(side="left")
        self.net_kind = tk.StringVar(value="tspl")
        ttk.Combobox(row, textvariable=self.net_kind, values=["tspl", "zpl"], width=6,
                     state="readonly", font="ui").pack(side="left", padx=6)
        button(row, "Add", self._add_net, "chip").pack(side="left")

        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        button(row, "Feed / calibrate…", self._calibrate, "warn").pack(side="left")
        button(row, "Open log folder", self._logs, "quiet").pack(side="left", padx=8)
        button(row, "Save", self._save, "primary").pack(side="right")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right", padx=8)
        self.stock = st

    def _add_net(self):
        try:
            p = printers.network_printer(self.net.get(), self.net_kind.get())
        except printers.PrinterError as e:
            tell(self, "Address", str(e))
            return
        info = self.app.cfg.printer_info(p.id)
        info.update({"manual": True, "target": p.target, "kind": self.net_kind.get(),
                     "method": "network"})
        self.app.cfg.save()
        self.app.set_found([x for x in self.app.found if not x.manual])
        tell(self, "Added", f"Added {p.target}. Pick it in the printer list.")

    def _save(self):
        adv = self.app.cfg["advanced"]
        sid = self.stock.id
        adv["density"][sid] = int(self.density.get())
        try:
            sp = int(self.speed.get())
            adv["speed"][sid] = max(1, min(6, sp))
        except ValueError:
            pass
        try:
            g = float(self.gap.get())
            if 0 <= g <= 10:
                adv["gap"][sid] = g
        except ValueError:
            pass
        z = self.zpl_dark.get().strip()
        try:
            adv["zpl_darkness"] = int(z) if z else None
        except ValueError:
            pass
        adv["invert"] = bool(self.invert.get())
        if self.printer is not None:
            info = self.app.cfg.printer_info(self.printer.id)
            info["via_driver"] = bool(self.via_driver.get())
            set_printer_dpi(info, self.printer, int(self.dpi.get()))
        self.app.cfg.save()
        self.app.refresh_printer_combo()          # draws again if the resolution changed
        self.finish(True)

    def _calibrate(self):
        p = self.app.current_printer()
        if p is None:
            tell(self, "No printer", "Pick a printer first.")
            return
        cfgp = self.app.printer_config(p)
        if cfgp["kind"] != "tspl":
            tell(self, "Not needed", "Zebra printers calibrate from their own button "
                 "(hold the feed button until it flashes twice).")
            return
        if not ask(self, "Feed / calibrate",
                   "The printer will feed a few blank labels to measure them. "
                   "This uses up 2–4 labels. Go ahead?",
                   [("Yes, calibrate", True, "primary"), ("Cancel", False, "normal")]):
            return
        from . import tspl
        gap = self.app.cfg["advanced"]["gap"].get(self.stock.id)
        data = tspl.calibrate_job(self.stock, gap)
        try:
            printers.send(cfgp, data)
            tell(self, "Done", "Sent. The printer should feed a few labels and stop.")
        except printers.PrinterError as e:
            tell(self, "Didn't work", str(e))

    def _logs(self):
        open_folder(settings_mod.data_dir())


def open_folder(path: Path):
    """Show a folder in Explorer / Finder / the file manager."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        log.exception("open folder")


def import_update(parent, app):
    """Ask for a printer update file, validate and merge it (see known.KnownPrinters)."""
    path = filedialog.askopenfilename(parent=parent, title="Printer update file",
                                      filetypes=[("Printer update", "*.json"), ("All", "*")])
    if not path:
        return
    try:
        names = app.known.import_file(path)
    except known.DefinitionError as e:
        tell(parent, "Not added", str(e))
        return
    tell(parent, "Thank you", "Added support for: " + ", ".join(names))
    app.rescan_printers(user=True)


# ---------------------------------------------------------------------------
# printers
# ---------------------------------------------------------------------------

def set_printer_dpi(info: dict, p, dpi) -> None:
    """Remember the user's resolution for a printer; the detected one needs no entry."""
    if dpi in printers.DPI_CHOICES and dpi != p.dpi:
        info["dpi"] = int(dpi)
    else:
        info.pop("dpi", None)


def pick_dpi(parent, name: str, detected: int) -> int | None:
    """Ask how sharp a printer prints, in plain words. Returns 203/300 or None."""
    return choose(parent, "How sharp does it print?",
                  f"How sharp does “{name}” print? Leave it on Normal unless the printer "
                  "(or its box) says 300 dpi. Food Labeler thinks it is "
                  f"{'Sharp (300 dpi)' if detected == 300 else 'Normal (203 dpi)'}.",
                  [(printers.DPI_LABELS[v], v) for v in printers.DPI_CHOICES])


def pick_kind(parent, name: str) -> str | None:
    """Ask which language a printer speaks, in plain words. Returns "tspl"/"zpl"/None."""
    return choose(parent, "What kind of printer?",
                  f"What kind of printer is “{name}”?", KIND_CHOICES)


class MyPrintersDialog(Modal):
    """Name, identify ("Which one is it?"), retype, choose or forget printers."""

    def __init__(self, parent, app):
        super().__init__(parent, "My printers")
        self.app = app
        tk.Label(self.body, text="My printers", font="big", bg=BG, fg=INK).pack(anchor="w")
        tk.Label(self.body, text="Give each printer a name you'll recognise, like “White "
                 "label printer”. “Which one is it?” prints a tiny label on it.",
                 font="ui", bg=BG, fg=MUTED, wraplength=760, justify="left").pack(anchor="w",
                                                                                 pady=(4, 8))
        self.list = tk.Frame(self.body, bg=BG)
        self.list.pack(fill="x")
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(12, 0))
        button(row, "Look for printers again", self._rescan, "chip").pack(side="left")
        button(row, "Done", self.cancel, "primary").pack(side="right")
        self._draw()

    def _rescan(self):
        self.app.set_found(printers.discover(self.app.known))
        self._draw()

    def _draw(self):
        for w in self.list.winfo_children():
            w.destroy()
        app = self.app
        rows = [(p, True) for p in app.found]
        for pid, info in app.cfg["printers"].items():
            if not any(p.id == pid for p in app.found) and (info.get("nickname") or
                                                            pid == app.cfg["selected"]):
                rows.append((printers.Printer(id=pid, port="not connected"), False))
        if not rows:
            tk.Label(self.list, text="No printers found.", font="ui", bg=BG).pack(anchor="w")
        for p, here in rows:
            info = app.cfg["printers"].get(p.id, {})
            fr = tk.Frame(self.list, bg=PANEL, highlightthickness=2,
                          highlightbackground=GREEN if p.id == app.cfg["selected"] else BORDER,
                          padx=12, pady=8)
            fr.pack(fill="x", pady=4)
            name = info.get("nickname") or (p.default_name() if here else "My printer")
            kind = info.get("kind") or p.kind or "tspl"
            tk.Label(fr, text=name, font="ui_bold", bg=PANEL, fg=INK, wraplength=380,
                     justify="left").grid(row=0, column=0,
                                                                          sticky="w")
            sub = f"{p.port}  •  {'Zebra' if kind == 'zpl' else 'Label printer (LP610BT type)'}"
            if here:
                sharp = printers.printer_dpi(p, info)
                sub += "  •  " + ("Sharp (300 dpi)" if sharp == 300 else "Normal (203 dpi)")
            tk.Label(fr, text=sub, font="ui", bg=PANEL, fg=MUTED, wraplength=380,
                     justify="left").grid(row=1, column=0,
                                                                       sticky="w")
            btns = tk.Frame(fr, bg=PANEL)
            btns.grid(row=0, column=1, rowspan=2, sticky="e")
            fr.grid_columnconfigure(0, weight=1)
            button(btns, "Rename", lambda p=p, n=name: self._rename(p, n), "chip").pack(
                side="left", padx=2)
            if here:
                button(btns, "Which one is it?", lambda p=p: self._identify(p), "chip").pack(
                    side="left", padx=2)
                button(btns, "Type", lambda p=p, n=name: self._kind(p, n), "chip").pack(
                    side="left", padx=2)
                button(btns, "Sharpness", lambda p=p, n=name: self._dpi(p, n), "chip").pack(
                    side="left", padx=2)
                if p.id != app.cfg["selected"]:
                    button(btns, "Use this one", lambda p=p: self._use(p), "primary").pack(
                        side="left", padx=2)
            if not here or p.manual:
                button(btns, "Forget", lambda p=p: self._forget(p), "warn").pack(side="left",
                                                                                padx=2)

    def _rename(self, p, current):
        m = Modal(self, "Rename printer")
        tk.Label(m.body, text="Name for this printer:", font="ui_bold", bg=BG).pack(anchor="w")
        var = tk.StringVar(value=current)
        e = tk.Entry(m.body, textvariable=var, font="big", width=28)
        e.pack(fill="x", ipady=4, pady=8)
        e.select_range(0, "end")
        e.focus_set()
        e.bind("<Return>", lambda ev: m.finish(var.get()))
        row = tk.Frame(m.body, bg=BG)
        row.pack(fill="x")
        button(row, "OK", lambda: m.finish(var.get()), "primary").pack(side="left")
        button(row, "Cancel", m.cancel, "quiet").pack(side="right")
        new = m.run()
        if new is not None:
            self.app.cfg.printer_info(p.id)["nickname"] = new.strip()[:60]
            self.app.cfg.save()
            self.app.refresh_printer_combo()
            self._draw()

    def _identify(self, p):
        name = self.app.printer_name(p)
        self.app.print_text_label(p, ["This is:", name])

    def _kind(self, p, name):
        k = pick_kind(self, name)
        if k:
            self.app.cfg.printer_info(p.id)["kind"] = k
            self.app.cfg.save()
            self._draw()

    def _dpi(self, p, name):
        v = pick_dpi(self, name, p.dpi)
        if v:
            set_printer_dpi(self.app.cfg.printer_info(p.id), p, v)
            self.app.cfg.save()
            self.app.refresh_printer_combo()      # draws again at the new resolution
            self._draw()

    def _use(self, p):
        self.app.select_printer(p.id)
        self._draw()

    def _forget(self, p):
        self.app.cfg["printers"].pop(p.id, None)
        if self.app.cfg["selected"] == p.id:
            self.app.cfg["selected"] = ""
        self.app.cfg.save()
        self.app.set_found([x for x in self.app.found if x.id != p.id])
        self._draw()


class SetupWizard(Modal):
    """Three big steps: plug in -> pick printer -> test label."""

    def __init__(self, parent, app):
        super().__init__(parent, "Set up my printer")
        self.app = app
        self.chosen = None
        self.frame = tk.Frame(self.body, bg=BG, width=760)
        self.frame.pack(fill="both", expand=True)
        self.step1()

    def _clear(self, n, title):
        for w in self.frame.winfo_children():
            w.destroy()
        tk.Label(self.frame, text=f"Step {n} of 3", font="ui", bg=BG, fg=MUTED).pack(anchor="w")
        tk.Label(self.frame, text=title, font="big", bg=BG, fg=INK, wraplength=740,
                 justify="left").pack(anchor="w", pady=(2, 12))

    def step1(self):
        self._clear(1, "Plug the printer in and switch it on")
        tk.Label(self.frame, text="Connect the printer to this computer with its USB cable. "
                 "Switch it on and put a roll of labels in it.", font="ui", bg=BG, fg=INK,
                 wraplength=740, justify="left").pack(anchor="w")
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=(20, 0))
        button(row, "Next ▶", self.step2, "primary").pack(side="right")
        button(row, "Cancel", self.cancel, "quiet").pack(side="left")

    def step2(self):
        self._clear(2, "Pick your printer")
        found = printers.discover(self.app.known)
        self.app.set_found(found)
        found = self.app.found
        self.lb = tk.Listbox(self.frame, font="ui", height=min(8, max(3, len(found))),
                             activestyle="none", selectbackground=GREEN, exportselection=False)
        for p in found:
            self.lb.insert("end", p.display(self.app.cfg.nickname(p.id)))
        self.lb.pack(fill="x")
        pick = printers.auto_pick(found)
        cur = self.app.current_printer()
        target = cur or pick
        if target is not None and target in found:
            i = found.index(target)
            self.lb.selection_set(i)
            self.lb.see(i)
        if not found:
            tk.Label(self.frame, text="I can't see any printers yet. Check the cable and that "
                     "the printer is switched on, then press “Look again”.",
                     font="ui", bg=BG, fg=WARN, wraplength=740, justify="left").pack(
                anchor="w", pady=(8, 0))
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        button(row, "Look again", self.step2, "chip").pack(side="left")
        button(row, "My printer isn't in the list",
               lambda: (UsbDevicesDialog(self, self.app).run(), self.step2()),
               "quiet").pack(side="left", padx=8)
        nav = tk.Frame(self.frame, bg=BG)
        nav.pack(fill="x", pady=(20, 0))
        button(nav, "◀ Back", self.step1, "quiet").pack(side="left")
        button(nav, "Next ▶", lambda: self._chose(found), "primary").pack(side="right")

    def _chose(self, found):
        sel = self.lb.curselection()
        if not sel:
            tell(self, "Pick one", "Please tap your printer in the list first.")
            return
        p = found[sel[0]]
        info = self.app.cfg.printer_info(p.id)
        if not (info.get("kind") or p.kind):
            k = pick_kind(self, p.default_name())
            if not k:
                return
            info["kind"] = k
        self.app.select_printer(p.id, use_its_size=False)
        self.chosen = p
        self.step3()

    def step3(self):
        p = self.chosen
        self._clear(3, "Print a test label")
        tk.Label(self.frame, text=f"Printer: {self.app.printer_name(p)}", font="ui", bg=BG,
                 fg=MUTED).pack(anchor="w")
        tk.Label(self.frame, text="Make sure labels are in the printer, then press the button. "
                 "A small label saying “Hello! Your printer works.” should come out.",
                 font="ui", bg=BG, fg=INK, wraplength=740, justify="left").pack(anchor="w",
                                                                                pady=(8, 12))
        button(self.frame, "Print a test label",
               lambda: self.app.print_text_label(p, ["Hello!", "Your printer works."]),
               "print", font="big").pack(anchor="w")
        tk.Label(self.frame, text="Give it a name (if you like):", font="ui", bg=BG,
                 fg=INK).pack(anchor="w", pady=(16, 0))
        self.nick = tk.StringVar(value=self.app.cfg.nickname(p.id))
        tk.Entry(self.frame, textvariable=self.nick, font="field", width=30).pack(anchor="w",
                                                                                  ipady=4)
        nav = tk.Frame(self.frame, bg=BG)
        nav.pack(fill="x", pady=(20, 0))
        button(nav, "◀ Back", self.step2, "quiet").pack(side="left")
        button(nav, "Finish", self._finish, "primary").pack(side="right")

    def _finish(self):
        if self.chosen is not None and self.nick.get().strip():
            self.app.cfg.printer_info(self.chosen.id)["nickname"] = self.nick.get().strip()[:60]
            self.app.cfg.save()
        self.app.refresh_printer_combo()
        self.finish(True)


# ---------------------------------------------------------------------------
# USB devices ("My printer isn't in the list")
# ---------------------------------------------------------------------------

class UsbDevicesDialog(Modal):
    """The "My printer isn't in the list" window: every USB device, re-scanned every 2 s.

    Devices that appear after the window opened are marked "This just
    appeared", so unplugging and re-plugging the printer identifies it.
    """

    POLL_MS = 2000

    def __init__(self, parent, app):
        super().__init__(parent, "Look for USB devices")
        self.app = app
        self.seen: set | None = None
        self.new: set = set()
        self.devices: list = []
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        self._job = None
        b = self.body
        tk.Label(b, text="Things plugged into this computer", font="big", bg=BG,
                 fg=INK).pack(anchor="w")
        tk.Label(b, text="Tip: unplug the printer, wait a moment, then plug it back in. "
                 "It will show up here marked “This just appeared”.", font="ui",
                 bg=BG, fg=MUTED, wraplength=760, justify="left").pack(anchor="w", pady=(4, 8))
        self.sf = ScrollFrame(b, bg=BG)
        self.sf.configure(width=800, height=min(460, parent.winfo_screenheight() - 300))
        self.sf.pack_propagate(False)
        self.sf.pack(fill="both", expand=True)
        row = tk.Frame(b, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        button(row, "Look again", self._scan, "chip").pack(side="left")
        button(row, "Send this to High Thyme Kitchen", lambda: ReportDialog(self, app).run()
               ).pack(side="left", padx=8)
        button(row, "Add printer update file…", lambda: import_update(self, app),
               "quiet").pack(side="left")
        button(row, "Close", self.cancel, "primary").pack(side="right")
        self._scan()

    def destroy(self):
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        super().destroy()

    def _scan(self):
        if self._busy:
            return
        self._busy = True

        def work():
            self._q.put(usbscan.scan(self.app.known))
        threading.Thread(target=work, daemon=True).start()
        self._job = self.after(100, self._poll)

    def _poll(self):
        try:
            devs = self._q.get_nowait()
        except queue.Empty:
            self._job = self.after(100, self._poll)
            return
        self._busy = False
        keys = {d.key for d in devs}
        if self.seen is not None:
            self.new |= keys - self.seen
        self.new &= keys
        self.seen = keys if self.seen is None else self.seen | keys
        if [d.key for d in devs] != [d.key for d in self.devices] or self.new:
            self.devices = devs
            self._draw()
        self._job = self.after(self.POLL_MS, self._scan)

    def _draw(self):
        inner = self.sf.inner
        for w in inner.winfo_children():
            w.destroy()
        devs = sorted(self.devices, key=lambda d: (d.key not in self.new, not d.is_printer,
                                                   d.family is None))
        if not devs:
            tk.Label(inner, text="Nothing found yet.", font="ui", bg=BG).pack(anchor="w")
        for d in devs:
            new = d.key in self.new
            fr = tk.Frame(inner, bg=WARN_BG if new else PANEL, highlightthickness=2,
                          highlightbackground=WARN if new else BORDER, padx=12, pady=8)
            fr.pack(fill="x", pady=4, padx=2)
            fr.grid_columnconfigure(0, weight=1)
            if new:
                tk.Label(fr, text="This just appeared — is it your printer?", font="ui_bold",
                         bg=WARN_BG, fg=WARN).grid(row=0, column=0, sticky="w")
            tk.Label(fr, text=d.title(), font="ui_bold", bg=fr["bg"], fg=INK, wraplength=460,
                     justify="left").grid(
                row=1, column=0, sticky="w")
            tk.Label(fr, text=d.describe(), font="ui", bg=fr["bg"], fg=MUTED).grid(
                row=2, column=0, sticky="w")
            button(fr, "Use this as my printer", lambda d=d: self._use(d),
                   "primary" if (new or d.is_printer) else "normal").grid(
                row=0, column=1, rowspan=3, sticky="e")

    def _use(self, d):
        app = self.app
        found = printers.discover(app.known)
        app.set_found(found)
        found = app.found
        p = None
        if sys.platform.startswith("win"):
            wins = [x for x in found if x.method.startswith("windows")]
            if not wins:
                tell(self, "Printer not installed",
                     "Windows hasn't installed this printer yet. Please install the printer's "
                     "program (driver) from the company that made it, then try again. If you "
                     "can't, press “Send this to High Thyme Kitchen”.")
                return
            pid = choose(self, "Which one is it?",
                         "Which of these installed printers is it?",
                         [(x.display(app.cfg.nickname(x.id)), x.id) for x in wins])
            p = next((x for x in wins if x.id == pid), None)
        else:
            p = next((x for x in found if x.id == f"usb:{d.port}"), None)
            if p is None:
                tell(self, "Not ready yet",
                     "This device isn't working as a printer on this computer yet. Press "
                     "“Send this to High Thyme Kitchen” so they can help.")
                return
        if p is None:
            return
        k = pick_kind(self, d.title())
        if not k:
            return
        app.cfg.printer_info(p.id)["kind"] = k
        app.select_printer(p.id, use_its_size=False)
        if ask(self, "Test it?", "Print a small test label now?",
               [("Print a test label", True, "primary"), ("Not now", False, "normal")]):
            app.print_text_label(p, ["Hello!", "Your printer works."])


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

class ReportDialog(Modal):
    """Show the printer report (report.build) and copy / save / e-mail it."""

    def __init__(self, parent, app):
        super().__init__(parent, "Send printer info")
        self.app = app
        devs = usbscan.scan(app.known)
        text = report.build(app.found, devs, app.cfg.nicknames(),
                            settings_mod.data_dir() / "food-labeler.log", app.known)
        self.text = text
        tk.Label(self.body, text="This is what will be sent. It only has facts about the "
                 "computer and printers — nothing you wrote on your labels.", font="ui",
                 bg=BG, fg=INK, wraplength=760, justify="left").pack(anchor="w", pady=(0, 8))
        t = tk.Text(self.body, font="small", width=90, height=18, wrap="none")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        button(row, "Copy", self._copy, "chip").pack(side="left")
        button(row, "Save to Desktop", self._save, "chip").pack(side="left", padx=6)
        button(row, "Email it", self._email, "primary").pack(side="left")
        button(row, "Close", self.cancel, "quiet").pack(side="right")

    def _copy(self, quiet=False):
        self.clipboard_clear()
        self.clipboard_append(self.text)
        if not quiet:
            tell(self, "Copied", "Copied. You can paste it into an email or message.")

    def _save(self):
        try:
            p = report.save_to_desktop(self.text)
            tell(self, "Saved", f"Saved on your Desktop as “{p.name}”.")
        except OSError:
            tell(self, "Couldn't save", "I couldn't save it to the Desktop. Try “Copy”.")

    def _email(self):
        self._copy(quiet=True)
        to = str(known.app_config().get("support_email") or "")
        try:
            webbrowser.open(report.mailto(self.text, to))
            tell(self, "Email", "Your email program should open with the report in it. "
                 "(It's also copied, in case you need to paste it.)" +
                 ("" if to else "\n\nPlease type High Thyme Kitchen's email address in "
                  "the “To” box."))
        except Exception:  # noqa: BLE001
            tell(self, "Email", "I couldn't open your email program. The report is copied "
                 "— paste it into an email.")
