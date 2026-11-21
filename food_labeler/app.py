"""Food Labeler main window.

The form on the left edits ``App.doc`` (a model.LabelDoc) field by field.
Every change schedules a re-render (debounced by RENDER_DELAY_MS), which
draws the real printer bitmap and shows it scaled on the right, and an undo
snapshot. PRINT renders once more, builds the job for the chosen printer and
sends it on a worker thread; results come back through a queue polled with
``after()``, because Tk must only be touched from the main thread. Printer
discovery runs the same way, every 15 s and on request.
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from . import APP_NAME, BRAND, dates, known, model, printers, render, settings as settings_mod, stocks
from . import bakery, calibrate, cottage, printsettings, templates
from .widgets import (BG, BORDER, GREEN, GREEN_DARK, INK, MUTED, PANEL, WARN, WARN_BG,
                      CalendarDialog, ScrollFrame, Toggle, ask, button, tell)

log = logging.getLogger("food_labeler.app")

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_SIZES = {"ui": (16, "normal"), "ui_bold": (16, "bold"), "field": (20, "normal"),
              "big": (22, "bold"), "huge": (30, "bold"), "title": (22, "bold"),
              "small": (13, "normal")}
SCALES = [0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.7]
RENDER_DELAY_MS = 150
AUTOSAVE_MS = 4000


class App:
    """The main window and the state behind it (document, file, undo, printers)."""

    def __init__(self, root: tk.Tk, cfg: settings_mod.Settings):
        self.root = root
        self.cfg = cfg
        self.doc = model.LabelDoc()
        self.path: str | None = None
        self.saved_json = ""
        self.history: list[str] = []
        self.hpos = -1
        self._render_job = None
        self._hist_job = None
        self._kitchen_job = None
        self._loading = False
        self._last_autosave = ""
        self._printing = False
        self._q: queue.Queue = queue.Queue()
        self.field_frames: dict[str, tk.Widget] = {}
        self.field_setters: dict = {}
        self.last_result: render.RenderResult | None = None
        self._rendered_dpi = stocks.BASE_DPI   # resolution of the last render
        self._photo = None
        self.known = known.KnownPrinters(settings_mod.data_dir())
        self.found: list[printers.Printer] = []
        self._scan_q: queue.Queue = queue.Queue()
        self._scanning = False
        self._choices: list[str] = []
        self._printer_choice = tk.StringVar(master=root)
        # cottage food labels: state rules (+ the user's own edits) and My bakery
        data = settings_mod.data_dir()
        self.rules = cottage.CottageRules(data)
        self.profile = bakery.Profile(data / bakery.PROFILE_NAME, cfg["kitchen"])
        self._ingredients = None
        self._products = None
        self.check_frame = None
        self.net_hint = None
        self._check_sig = None

        root.report_callback_exception = self.on_error
        self._setup_fonts()
        self._setup_window()
        self._build()
        self._restore_session()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(AUTOSAVE_MS, self._autosave_tick)
        root.after(200, self.rescan_printers)
        root.after(700, self._bakery_start)

    # ------------------------------------------------------------------ setup
    def _setup_fonts(self):
        fam = "DejaVu Sans"
        families = set(tkfont.families(self.root))
        if sys.platform.startswith("win") and "Segoe UI" in families:
            fam = "Segoe UI"
        elif fam not in families:
            fam = "TkDefaultFont"
        self.font_family = fam
        self.fonts = {}
        for name, (size, weight) in FONT_SIZES.items():
            try:
                self.fonts[name] = tkfont.Font(self.root, name=name, family=fam, size=size,
                                               weight=weight)
            except tk.TclError:
                self.fonts[name] = tkfont.nametofont(name)
        self.apply_scale(self.cfg["ui_scale"], save=False)

    def apply_scale(self, scale: float, save=True):
        """Resize every named font (all windows use them) to the nearest SCALES step."""
        scale = min(SCALES, key=lambda s: abs(s - float(scale)))
        self.cfg["ui_scale"] = scale
        for name, (size, _w) in FONT_SIZES.items():
            self.fonts[name].configure(size=int(round(size * scale)))
        if save:
            self.cfg.save()
            self.schedule_render()

    def bigger_text(self, step: int):
        """A− / A+: one step down or up the SCALES list."""
        i = SCALES.index(min(SCALES, key=lambda s: abs(s - self.cfg["ui_scale"])))
        i = max(0, min(len(SCALES) - 1, i + step))
        self.apply_scale(SCALES[i])

    def _setup_window(self):
        r = self.root
        r.title(APP_NAME)
        r.configure(bg=BG)
        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Vertical.TScrollbar", arrowsize=24, width=24)
        style.configure("TCombobox", padding=6)
        r.option_add("*TCombobox*Listbox.font", "ui")
        self._icons = []
        try:
            if sys.platform.startswith("win") and (ASSETS / "icon.ico").exists():
                r.iconbitmap(default=str(ASSETS / "icon.ico"))
            imgs = [ImageTk.PhotoImage(Image.open(ASSETS / n))
                    for n in ("icon.png", "icon-48.png", "icon-32.png", "icon-16.png")
                    if (ASSETS / n).exists()]
            if imgs:
                r.iconphoto(True, *imgs)
                self._icons = imgs
        except Exception:  # noqa: BLE001
            log.exception("icon")
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        w, h = min(1400, sw - 40), min(900, sh - 80)
        r.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        r.minsize(min(1000, sw - 40), min(640, sh - 80))

    # ------------------------------------------------------------------ layout
    def _build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(2, weight=1)

        # --- top bar: brand + big buttons
        top = tk.Frame(r, bg=BG, padx=14, pady=10)
        top.grid(row=0, column=0, sticky="ew")
        brand = tk.Frame(top, bg=BG)
        brand.pack(side="left", padx=(0, 18))
        try:
            self._seal = ImageTk.PhotoImage(Image.open(ASSETS / "seal-header.png"))
            tk.Label(brand, image=self._seal, bg=BG).pack(side="left", padx=(0, 8))
        except Exception:  # noqa: BLE001
            self._seal = None
        names = tk.Frame(brand, bg=BG)
        names.pack(side="left")
        tk.Label(names, text=APP_NAME, font="title", bg=BG, fg=GREEN_DARK).pack(anchor="w")
        tk.Label(names, text=f"by {BRAND}", font="small", bg=BG, fg=MUTED).pack(anchor="w")

        for text, cmd in [("New", self.new_label), ("Open", self.open_dialog),
                          ("Save", self.save), ("Print…", self.print_dialog),
                          ("Undo", self.undo)]:
            button(top, text, cmd).pack(side="left", padx=4)
        button(top, "Settings", self.settings_dialog).pack(side="right", padx=4)
        button(top, "A+", lambda: self.bigger_text(1), width=3).pack(side="right", padx=2)
        button(top, "A−", lambda: self.bigger_text(-1), width=3).pack(side="right", padx=2)
        tk.Label(top, text="Text size", font="small", bg=BG, fg=MUTED).pack(side="right", padx=6)

        # --- my saved labels
        self.recent_bar = tk.Frame(r, bg=BG, padx=14)
        self.recent_bar.grid(row=1, column=0, sticky="ew")

        # --- main: form (left) + preview (right)
        main = tk.Frame(r, bg=BG, padx=14, pady=8)
        main.grid(row=2, column=0, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        # "uniform" keeps the 6:5 split no matter how wide the form's contents ask
        # to be (the cottage label check would otherwise squeeze the preview).
        main.grid_columnconfigure(0, weight=6, uniform="main")
        main.grid_columnconfigure(1, weight=5, uniform="main")

        left = tk.Frame(main, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        self.kind_bar = tk.Frame(left, bg=PANEL, padx=14, pady=10)
        self.kind_bar.grid(row=0, column=0, sticky="ew")
        self.scroll = ScrollFrame(left)
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.form = self.scroll.inner

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        head = tk.Frame(right, bg=BG)
        head.grid(row=0, column=0, sticky="ew")
        tk.Label(head, text="This is how your label will look", font="ui_bold", bg=BG,
                 fg=INK).pack(side="left")
        button(head, "Save as picture", self.export_picture, "quiet").pack(side="right")
        self.canvas = tk.Canvas(right, bg="#E2DED6", highlightthickness=0, bd=0, width=300,
                                height=180)
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
        self.canvas.bind("<Configure>", lambda e: self.schedule_render())
        notes = tk.Frame(right, bg=BG)
        notes.grid(row=2, column=0, sticky="ew")
        self.qr_lbl = tk.Label(notes, text="", font="small", bg=BG, fg=MUTED,
                               wraplength=600, justify="left", anchor="w")
        self.qr_lbl.pack(fill="x")
        self.warn_lbl = tk.Label(notes, text="", font="ui_bold", bg=BG, fg=WARN,
                                 wraplength=600, justify="left")
        self.warn_lbl.pack(fill="x")
        right.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 20))
                                             for w in (self.warn_lbl, self.qr_lbl)])

        # printer choice (right above the PRINT button)
        pp = tk.Frame(right, bg=PANEL, highlightthickness=1, highlightbackground=BORDER,
                      padx=12, pady=8)
        pp.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        pp.grid_columnconfigure(1, weight=1)
        tk.Label(pp, text="Printer:", font="ui_bold", bg=PANEL, fg=INK).grid(row=0, column=0,
                                                                            sticky="w")
        self.printer_box = tk.Frame(pp, bg=PANEL, highlightthickness=3,
                                    highlightbackground=PANEL)
        self.printer_box.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.printer_btn = tk.Menubutton(self.printer_box, text="", font="ui", bg="#FFFFFF",
                                         fg=INK, relief="flat", highlightthickness=2,
                                         highlightbackground=BORDER, anchor="w", padx=10,
                                         pady=6, cursor="hand2", direction="above",
                                         wraplength=420, justify="left",
                                         activebackground="#EFE9DD")
        self.printer_menu = tk.Menu(self.printer_btn, tearoff=False, font="ui")
        self.printer_btn.configure(menu=self.printer_menu)
        self.printer_btn.pack(fill="x")
        self.status_lbl = tk.Label(pp, text="", font="ui", bg=PANEL, fg=MUTED, cursor="hand2",
                                   anchor="w", justify="left")
        self.status_lbl.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.status_lbl.bind("<Button-1>", lambda e: self._status_clicked())
        prow = tk.Frame(pp, bg=PANEL)
        prow.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        button(prow, "Look for printers again", lambda: self.rescan_printers(user=True),
               "chip").pack(side="left", padx=(0, 6))
        button(prow, "My printers\u2026", self.my_printers, "quiet").pack(side="left")
        # second row, so no button gets cut off on a laptop-size window
        prow2 = tk.Frame(pp, bg=PANEL)
        prow2.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        button(prow2, "Print settings\u2026", self.print_settings, "quiet").pack(
            side="left", padx=(0, 6))
        button(prow2, "My printer isn't in the list", self.usb_devices, "quiet").pack(
            side="left")
        # "New roll in the …? Set it up" — a gentle one-line notice, never a popup,
        # shown only when the label size differs from the roll last set up here
        self.roll_notice = tk.Frame(pp, bg=WARN_BG, padx=8, pady=4)
        self.roll_lbl = tk.Label(self.roll_notice, text="", font="ui", bg=WARN_BG, fg=INK,
                                 anchor="w", justify="left", wraplength=520)
        self.roll_lbl.pack(anchor="w", fill="x")
        # buttons on their own line under the words, so neither gets cut off
        nb = tk.Frame(self.roll_notice, bg=WARN_BG)
        nb.pack(anchor="w", pady=(4, 0))
        button(nb, "Set up", self._roll_notice_clicked, "chip").pack(side="left")
        button(nb, "No, same roll", self._same_roll, "quiet").pack(side="left", padx=(6, 0))

        # --- bottom: copies + PRINT
        bottom = tk.Frame(r, bg=BG, padx=14, pady=8)
        bottom.grid(row=3, column=0, sticky="ew")
        tk.Label(bottom, text="How many labels?", font="big", bg=BG, fg=INK).pack(side="left")
        button(bottom, "\u2212", lambda: self.change_copies(-1), font="huge", width=2).pack(
            side="left", padx=(12, 4))
        self.copies_var = tk.StringVar(value="1")
        self.copies_entry = tk.Entry(bottom, textvariable=self.copies_var, font="huge", width=3,
                                     justify="center", relief="flat", highlightthickness=2,
                                     highlightbackground=BORDER, highlightcolor=GREEN)
        self.copies_entry.pack(side="left", ipady=4)
        self.copies_var.trace_add("write", lambda *a: self._copies_typed())
        button(bottom, "+", lambda: self.change_copies(1), font="huge", width=2).pack(
            side="left", padx=(4, 18))
        self.print_btn = button(bottom, "PRINT", self.print_now, "print", font="huge")
        self.print_btn.configure(padx=60, pady=10)
        self.print_btn.pack(side="right")
        self.message_lbl = tk.Label(bottom, text="", font="ui", bg=BG, fg=GREEN_DARK,
                                    anchor="w", justify="left", wraplength=420)
        self.message_lbl.pack(side="left", fill="x", expand=True, padx=10)

    def _bind_keys(self):
        r = self.root
        for seq, fn in [("<Control-s>", self.save), ("<Control-S>", self.save_as),
                        ("<Control-o>", self.open_dialog), ("<Control-n>", self.new_label),
                        ("<Control-p>", self.print_dialog), ("<Control-z>", self.undo),
                        ("<Control-y>", self.redo)]:
            r.bind_all(seq, lambda e, fn=fn: (fn(), "break")[1])

    # ------------------------------------------------------------------ session
    def _restore_session(self):
        """Reopen exactly what was on screen last time (see settings autosave).

        "dirty" is derived by comparing the document with ``saved_json`` (the
        last saved contents). If the autosaved document had unsaved changes we
        reload the file it came from as the saved state, so the title still
        says "not saved yet" and closing still offers to save.
        """
        got = settings_mod.read_autosave()
        if got:
            doc, path, dirty = got
            self.set_doc(doc, path)
            if dirty:
                self.saved_json = ""          # still unsaved from last time
                if path and Path(path).is_file():
                    try:
                        self.saved_json = model.load(path).dumps()
                    except model.LabelFileError:
                        self.saved_json = ""
                self._update_title()
        else:
            self.set_doc(self._fresh_doc("simple", stocks.DEFAULT_STOCK), None)

    def _fresh_doc(self, template: str, stock: str) -> model.LabelDoc:
        doc = model.LabelDoc(template, stock, model.default_fields(template))
        doc.lettering = self.cfg.lettering_for(template)   # last choice for this kind
        self._fill_kitchen(doc)
        return doc

    def _fill_kitchen(self, doc: model.LabelDoc):
        if doc.template != "package":
            return
        k = self.cfg["kitchen"]
        for key in ("business", "address", "disclaimer", "cross_contact"):
            cur = str(doc.fields.get(key) or "")
            if (not cur.strip() or cur in (model.DEFAULT_DISCLAIMER, model.DEFAULT_CROSS_CONTACT)) \
                    and k.get(key):
                doc.fields[key] = k[key]

    def set_doc(self, doc: model.LabelDoc, path: str | None, mark_saved=True):
        """Replace the document (new/open/restore): resets undo and rebuilds the form."""
        self.doc = doc
        self.path = path
        if mark_saved:
            self.saved_json = doc.dumps()
        self.history = [doc.snapshot()]
        self.hpos = 0
        self._sync_ui_from_doc()

    def _sync_ui_from_doc(self):
        self._loading = True
        try:
            self.copies_var.set(str(self.doc.copies))
            self.build_form()
            self.refresh_recent()
        finally:
            self._loading = False
        self._update_title()
        self.schedule_render()
        self.refresh_roll_notice()

    def _autosave_tick(self):
        # Runs every AUTOSAVE_MS; writes only when document, path or dirty flag
        # changed since the last write, so an idle app doesn't touch the disk.
        try:
            cur = self.doc.dumps()
            state = cur + str(self.path) + str(self.dirty)
            if state != self._last_autosave:
                settings_mod.write_autosave(self.doc, self.path, self.dirty)
                self._last_autosave = state
        except Exception:  # noqa: BLE001
            log.exception("autosave failed")
        self.root.after(AUTOSAVE_MS, self._autosave_tick)

    @property
    def dirty(self) -> bool:
        """Unsaved changes: the document differs from what was last saved/opened."""
        return self.doc.dumps() != self.saved_json

    def _update_title(self):
        name = self.doc.title() or "New label"
        extra = " (not saved yet)" if self.dirty else ""
        self.root.title(f"{APP_NAME} — {name}{extra}")

    # ------------------------------------------------------------------ changes
    def changed(self, history=True):
        """Call after any edit: updates title and preview; undo snapshot after 0.7 s of quiet."""
        if self._loading:
            return
        self._update_title()
        self.schedule_render()
        if history:
            if self._hist_job:
                self.root.after_cancel(self._hist_job)
            self._hist_job = self.root.after(700, self._snapshot)

    def _snapshot(self):
        self._hist_job = None
        cur = self.doc.dumps()
        if self.history and self.history[self.hpos] == cur:
            return
        self.history = self.history[: self.hpos + 1] + [cur]
        self.history = self.history[-100:]
        self.hpos = len(self.history) - 1

    def undo(self):
        """Go back one snapshot (a pending snapshot is taken first so typing is undoable)."""
        if self._hist_job:
            self.root.after_cancel(self._hist_job)
            self._snapshot()
        if self.hpos <= 0:
            self.flash("Nothing more to undo.")
            return
        self.hpos -= 1
        self._load_snapshot()
        self.flash("Undone.")

    def redo(self):
        """Ctrl+Y: forward one snapshot."""
        if self.hpos >= len(self.history) - 1:
            return
        self.hpos += 1
        self._load_snapshot()

    def _load_snapshot(self):
        self.doc = model.LabelDoc.from_snapshot(self.history[self.hpos])
        self._sync_ui_from_doc()

    def set_field(self, key, value):
        """Store one form value. Kitchen details on package labels are also remembered
        in settings (saved after 1 s) so the next package label starts with them."""
        if self._loading:
            return
        if self.doc.fields.get(key) == value:
            return
        self.doc.fields[key] = value
        if self.doc.template == "package" and key in ("business", "address", "disclaimer",
                                                     "cross_contact"):
            self.cfg["kitchen"][key] = value
            if self._kitchen_job:
                self.root.after_cancel(self._kitchen_job)
            self._kitchen_job = self.root.after(1000, self.cfg.save)
        self.changed()

    def flash(self, text: str, ms=5000):
        """Show a short message next to PRINT for ``ms`` milliseconds."""
        self.message_lbl.configure(text=text)
        if getattr(self, "_flash_job", None):
            self.root.after_cancel(self._flash_job)
        self._flash_job = self.root.after(ms, lambda: self.message_lbl.configure(text=""))

    # ------------------------------------------------------------------ form
    def build_form(self):
        """(Re)create the form for the current template from scratch."""
        for w in self.kind_bar.winfo_children():
            w.destroy()
        for w in self.form.winfo_children():
            w.destroy()
        self.field_frames.clear()
        self.field_setters.clear()

        st = stocks.get(self.doc.stock)
        tname = templates.TEMPLATE_INFO[self.doc.template][0]
        kb = self.kind_bar
        kb.grid_columnconfigure(1, weight=1)
        tk.Label(kb, text="Kind of label:", font="ui", bg=PANEL, fg=MUTED).grid(
            row=0, column=0, sticky="w")
        tk.Label(kb, text=tname, font="ui_bold", bg=PANEL, fg=INK, wraplength=240,
                 justify="left").grid(row=0, column=1,
                                                                        sticky="w", padx=8)
        button(kb, "Change…", self.pick_template, "chip").grid(row=0, column=2, sticky="e")
        tk.Label(kb, text="Label size:", font="ui", bg=PANEL, fg=MUTED).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        tk.Label(kb, text=st.name, font="ui_bold", bg=PANEL, fg=INK, wraplength=240,
                 justify="left").grid(
            row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        button(kb, "Change…", self.pick_stock, "chip").grid(row=1, column=2, sticky="e",
                                                                 pady=(8, 0))
        tk.Label(kb, text="Lettering:", font="ui", bg=PANEL, fg=MUTED).grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        from .font_dialogs import summary
        tk.Label(kb, text=summary(self.doc), font="ui_bold", bg=PANEL, fg=INK, wraplength=240,
                 justify="left").grid(row=2, column=1, sticky="w", padx=8, pady=(8, 0))
        button(kb, "Change…", self.pick_lettering, "chip").grid(row=2, column=2, sticky="e",
                                                                     pady=(8, 0))
        # picture and QR code: on every kind of label
        pic = self.doc.picture
        tk.Label(kb, text="Picture:", font="ui", bg=PANEL, fg=MUTED).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        tk.Label(kb, text=(pic.get("name") or "Yes") if pic else "None", font="ui_bold",
                 bg=PANEL, fg=INK, wraplength=240, justify="left").grid(
            row=3, column=1, sticky="w", padx=8, pady=(8, 0))
        button(kb, "Change…" if pic else "Add a picture…", self.pick_picture, "chip").grid(
            row=3, column=2, sticky="e", pady=(8, 0))
        from . import qrcodes
        qtext = qrcodes.payload(qrcodes.clean(self.doc.qr))
        tk.Label(kb, text="QR code:", font="ui", bg=PANEL, fg=MUTED).grid(
            row=4, column=0, sticky="w", pady=(8, 0))
        tk.Label(kb, text=qrcodes.WHAT[qrcodes.clean(self.doc.qr)["what"]] if qtext else "None",
                 font="ui_bold", bg=PANEL, fg=INK, wraplength=240, justify="left").grid(
            row=4, column=1, sticky="w", padx=8, pady=(8, 0))
        button(kb, "Change…" if qtext else "Add a QR code…", self.pick_qr, "chip").grid(
            row=4, column=2, sticky="e", pady=(8, 0))
        ttk.Separator(kb).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        t = self.doc.template
        f = self.form
        if t == "simple":
            self.entry_field(f, "food", "What food is it?", big=True)
            self.date_field(f, "made_on", "Made on", today_button=True)
            self.date_field(f, "use_by", "Use by", quick_from="made_on")
            self.allergen_field(f, "contains", "Contains (allergens)  —  tap any that are in it")
            self.entry_field(f, "note", "Note (if you want one)")
            self.chips(f, "note", model.NOTE_CHIPS)
            self.entry_field(f, "made_by", "Made by (if you want it)")
            self.kitchen_toggle(f)
        elif t == "package":
            self.entry_field(f, "product", "Product name", big=True)
            self.entry_field(f, "net", "Net weight (for example 8 oz or 227 g)")
            self.text_field(f, "ingredients", "Ingredients", 3)
            self.allergen_field(f, "contains", "Contains (allergens)  —  tap any that are in it")
            self.text_field(f, "cross_contact", "Cross-contact notice", 3)
            self.entry_field(f, "lot", "Lot number")
            self.date_field(f, "best_by", "Best by", quick_from=None)
            tk.Label(f, text="My kitchen details (remembered for next time)", font="ui_bold",
                     bg=PANEL, fg=GREEN_DARK).pack(anchor="w", padx=16, pady=(22, 0))
            self.entry_field(f, "business", "Business name")
            self.text_field(f, "address", "Address", 2)
            self.text_field(f, "disclaimer", "Disclaimer", 3)
        elif t == "cottage":
            self._cottage_form(f)
        elif t == "sticker":
            self.entry_field(f, "lot", "Lot number", big=True)
            self.date_field(f, "made", "Made", today_button=True)
            self.date_field(f, "best_by", "Best by", quick_from="made")
            self.entry_field(f, "count", "How many in the batch (if you want it)")
        elif t == "picture":
            fr = self._section(f, "picture", "Your picture")
            button(fr, "Change the picture…" if self.doc.picture else "Choose a picture…",
                   self.pick_picture, "primary").pack(anchor="w", pady=(4, 0))
            self.text_field(f, "text", "Words under the picture (if you want them)", 2)
        else:
            self.text_field(f, "text", "Type your words (press Enter for a new line)", 5,
                            big=True)
        tk.Frame(f, bg=PANEL, height=30).pack()
        self.scroll.canvas.yview_moveto(0)

    def _section(self, parent, key, title):
        fr = tk.Frame(parent, bg=PANEL, padx=14, pady=4, highlightthickness=3,
                      highlightbackground=PANEL)
        fr.pack(fill="x", pady=(6, 0))
        tk.Label(fr, text=title, font="ui_bold", bg=PANEL, fg=INK).pack(anchor="w")
        self.field_frames[key] = fr
        return fr

    def entry_field(self, parent, key, title, big=False):
        """One-line text field bound to doc.fields[key]."""
        fr = self._section(parent, key, title)
        var = tk.StringVar(value=str(self.doc.fields.get(key) or ""))
        e = tk.Entry(fr, textvariable=var, font="big" if big else "field", relief="flat",
                     highlightthickness=2, highlightbackground=BORDER, highlightcolor=GREEN,
                     bg="#FFFFFF", fg=INK, insertwidth=3)
        e.pack(fill="x", ipady=6, pady=(4, 0))
        var.trace_add("write", lambda *a: self.set_field(key, var.get()))
        self.field_setters[key] = var.set
        return fr

    def text_field(self, parent, key, title, height, big=False):
        """Multi-line text field bound to doc.fields[key]."""
        fr = self._section(parent, key, title)
        t = tk.Text(fr, font="big" if big else "field", height=height, wrap="word",
                    relief="flat", highlightthickness=2, highlightbackground=BORDER,
                    highlightcolor=GREEN, bg="#FFFFFF", fg=INK, insertwidth=3, undo=False,
                    padx=6, pady=4)
        t.insert("1.0", str(self.doc.fields.get(key) or ""))
        t.edit_modified(False)
        t.pack(fill="x", pady=(4, 0))

        def on_mod(_e=None):
            if t.edit_modified():
                t.edit_modified(False)
                self.set_field(key, t.get("1.0", "end-1c"))
        t.bind("<<Modified>>", on_mod)
        # Tab moves on instead of typing a tab
        t.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
        return fr

    def date_field(self, parent, key, title, today_button=False, quick_from=None):
        """Date button + ±1 day/calendar/today chips, and quick offsets for "use by"
        dates (counted from the ``quick_from`` field, or from today)."""
        fr = self._section(parent, key, title)
        row = tk.Frame(fr, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))

        def current():
            return dates.parse(self.doc.fields.get(key)) or dates.today()

        def set_date(d):
            self.doc.fields[key] = d.isoformat()
            show.configure(text="\U0001F4C5  " + dates.fmt_long(d))
            self.changed()

        def pick():
            d = CalendarDialog(self.root, f"Choose the “{title}” date", current()).run()
            if d:
                set_date(d)

        show = button(row, "", pick, font="field")
        show.configure(text="\U0001F4C5  " + dates.fmt_long(current()), anchor="w")
        show.pack(side="left", fill="x", expand=True)
        row2 = tk.Frame(fr, bg=PANEL)
        row2.pack(fill="x", pady=(6, 0))
        button(row2, "− 1 day", lambda: set_date(current() - dates.dt.timedelta(days=1)),
               "chip").pack(side="left", padx=(0, 4))
        button(row2, "+ 1 day", lambda: set_date(current() + dates.dt.timedelta(days=1)),
               "chip").pack(side="left", padx=(0, 4))
        button(row2, "Calendar", pick, "chip").pack(side="left", padx=(0, 4))
        if today_button:
            button(row2, "Today", lambda: set_date(dates.today()), "chip").pack(side="left")
        if quick_from is not None or key in ("use_by", "best_by"):
            hint = "after it was made" if quick_from else "from today"
            tk.Label(fr, text=f"Quick ({hint}):", font="ui", bg=PANEL, fg=MUTED).pack(
                anchor="w", pady=(6, 0))
            q = tk.Frame(fr, bg=PANEL)
            q.pack(fill="x")

            def base():
                if quick_from:
                    return dates.parse(self.doc.fields.get(quick_from)) or dates.today()
                return dates.today()
            for i, (text, kind, n) in enumerate(dates.QUICK):
                button(q, text, lambda k=kind, n=n: set_date(dates.quick(base(), k, n)),
                       "chip").grid(row=i // 3, column=i % 3, sticky="ew", padx=2, pady=2)
            for c in range(3):
                q.grid_columnconfigure(c, weight=1, uniform="q")

        def setter(v):
            d = dates.parse(v) or dates.today()
            show.configure(text="\U0001F4C5  " + dates.fmt_long(d))
        self.field_setters[key] = setter
        return fr

    def allergen_field(self, parent, key, title):
        """Allergen toggles kept in sync with a free-text "Contains" entry (comma list)."""
        fr = self._section(parent, key, title)
        grid = tk.Frame(fr, bg=PANEL)
        grid.pack(fill="x", pady=(4, 6))
        toggles = {}
        var = tk.StringVar(value=str(self.doc.fields.get(key) or ""))

        def current_list():
            return [x.strip() for x in var.get().split(",") if x.strip()]

        def toggled(name):
            items = current_list()
            low = [x.lower() for x in items]
            if toggles[name].value and name.lower() not in low:
                items.append(name)
            elif not toggles[name].value:
                items = [x for x in items if x.lower() != name.lower()]
            var.set(", ".join(items))

        for i, name in enumerate(model.ALLERGENS):
            tg = Toggle(grid, name, lambda n=name: toggled(n))
            tg.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            toggles[name] = tg
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1, uniform="a")
        tk.Label(fr, text="Contains: (you can also type here)", font="ui", bg=PANEL,
                 fg=MUTED).pack(anchor="w")
        e = tk.Entry(fr, textvariable=var, font="field", relief="flat", highlightthickness=2,
                     highlightbackground=BORDER, highlightcolor=GREEN, bg="#FFFFFF", fg=INK)
        e.pack(fill="x", ipady=6, pady=(2, 0))

        def sync(*_a):
            low = [x.lower() for x in current_list()]
            for name, tg in toggles.items():
                tg.set(name.lower() in low)
            self.set_field(key, var.get())
        var.trace_add("write", sync)
        sync()
        self.field_setters[key] = var.set

    def chips(self, parent, key, options):
        """Buttons that fill a field with a ready-made text (e.g. "Keep frozen")."""
        row = tk.Frame(parent, bg=PANEL, padx=16)
        row.pack(fill="x", pady=(6, 0))
        for i, text in enumerate(options):
            b = button(row, text, lambda t=text: self.field_setters[key](t), "chip")
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
        row.grid_columnconfigure(0, weight=1, uniform="c")
        row.grid_columnconfigure(1, weight=1, uniform="c")

    def kitchen_toggle(self, parent):
        """Simple labels: switch to add the kitchen name (kept in settings, not the doc)."""
        fr = self._section(parent, "kitchen", "Add my kitchen name")
        on = bool(self.doc.fields.get("kitchen"))
        name_var = tk.StringVar(value=self.cfg["kitchen"].get("business", ""))
        sub = tk.Frame(fr, bg=PANEL)

        def flip():
            self.doc.fields["kitchen"] = tg.value
            if tg.value:
                sub.pack(fill="x", pady=(6, 0))
            else:
                sub.pack_forget()
            self.changed()
        tg = Toggle(fr, "Put my kitchen name on the label", flip, on)
        tg.pack(anchor="w", pady=(4, 0))
        tk.Label(sub, text="My kitchen name:", font="ui", bg=PANEL, fg=MUTED).pack(anchor="w")
        e = tk.Entry(sub, textvariable=name_var, font="field", relief="flat",
                     highlightthickness=2, highlightbackground=BORDER, highlightcolor=GREEN)
        e.pack(fill="x", ipady=6)

        def name_changed(*_a):
            self.cfg["kitchen"]["business"] = name_var.get()
            if self._kitchen_job:
                self.root.after_cancel(self._kitchen_job)
            self._kitchen_job = self.root.after(1000, self.cfg.save)
            self.schedule_render()
        name_var.trace_add("write", name_changed)
        if on:
            sub.pack(fill="x", pady=(6, 0))

    # ------------------------------------------------------------------ pickers
    def pick_template(self):
        from .dialogs import TemplatePicker
        t = TemplatePicker(self.root, self.doc, self.render_ctx()).run()
        if not t or t == self.doc.template:
            return
        self.doc.set_template(t)
        remembered = self.cfg.lettering_for(t)
        if remembered:
            self.doc.lettering = remembered
        self._fill_kitchen(self.doc)
        if self.doc.stock not in templates.ALLOWED_STOCKS[t]:
            self.doc.stock = "large"
            kind = "Cottage food" if t == "cottage" else "Package"
            self.flash(f"{kind} labels need a bigger label, so I picked Large — 4 × 2 inches.",
                       8000)
        self._sync_ui_from_doc()
        self._snapshot()
        if t == "cottage" and not self.profile["setup_done"]:
            self.bakery_wizard()
        if t == "picture" and not self.doc.picture:
            self.pick_picture()

    def pick_lettering(self):
        """Kind bar → Lettering → Change…: the fonts of this label (remembered as the
        default for new labels of this kind)."""
        from .font_dialogs import LetteringDialog
        got = LetteringDialog(self.root, self.doc, self.render_ctx()).run()
        if got is None:
            return
        if model.clean_lettering(got) == model.clean_lettering(self.doc.lettering):
            return
        self.doc.lettering = model.clean_lettering(got)
        self.cfg.remember_lettering(self.doc.template, self.doc.lettering)
        self._sync_ui_from_doc()
        self._snapshot()

    def pick_stock(self):
        from .dialogs import StockPicker
        s = StockPicker(self.root, self.doc.template, self.doc.stock).run()
        if not s or s == self.doc.stock:
            return
        self.doc.stock = s
        self._sync_ui_from_doc()
        self._snapshot()

    # ------------------------------------------------------------------ preview
    def schedule_render(self):
        """Re-render soon; bursts of typing cause one render, not one per key."""
        if self._render_job:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(RENDER_DELAY_MS, self.render_now)

    def render_now(self):
        """Render the printer bitmap, show the preview, mark an overflowing field."""
        self._render_job = None
        dpi = self.current_dpi()
        res = render.render(self.doc, self.render_ctx(), dpi=dpi)
        self._rendered_dpi = dpi
        self.last_result = res
        cw, ch = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        img = render.preview(res, cw, ch)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        for key, fr in self.field_frames.items():
            bad = res.overflow and key == res.problem_field
            fr.configure(highlightbackground=WARN if bad else PANEL,
                         bg=WARN_BG if bad else PANEL)
        self.warn_lbl.configure(text=("⚠ " + res.message) if res.overflow else "")
        from . import qrcodes
        qtext = qrcodes.payload(qrcodes.clean(self.doc.qr))
        self.qr_lbl.configure(text=f"The QR code holds: {qtext}" if qtext else "")
        if self.doc.template == "cottage":
            self.refresh_check(res)
        return res

    # ------------------------------------------------------------------ copies
    def change_copies(self, step):
        """The big − / + buttons (1..200)."""
        self.copies_var.set(str(max(1, min(200, self.doc.copies + step))))

    def _copies_typed(self):
        txt = self.copies_var.get().strip()
        if not txt:
            return
        try:
            n = int(txt)
        except ValueError:
            self.copies_var.set(str(self.doc.copies))
            return
        n2 = max(1, min(200, n))
        if n2 != n:
            self.copies_var.set(str(n2))
            return
        if n2 != self.doc.copies:
            self.doc.copies = n2
            self.changed()

    # ------------------------------------------------------------------ files
    def refresh_recent(self):
        """Redraw the "My saved labels" bar (three most recent files)."""
        bar = self.recent_bar
        for w in bar.winfo_children():
            w.destroy()
        tk.Label(bar, text="My saved labels:", font="ui_bold", bg=BG, fg=INK).pack(
            side="left", padx=(0, 8))
        rec = self.cfg.recent()[:3]
        if not rec:
            tk.Label(bar, text="none yet — press Save to keep a label here",
                     font="ui", bg=BG, fg=MUTED).pack(side="left")
            return
        for r in rec:
            name = r.get("name") or Path(r["path"]).stem
            if len(name) > 16:
                name = name[:15] + "\u2026"
            button(bar, name, lambda p=r["path"]: self.open_path(p), "chip").pack(
                side="left", padx=3)
        button(bar, "More…", self.open_dialog, "quiet").pack(side="left", padx=3)

    def _ask_save_first(self, question="Save your label first?") -> bool:
        """Returns False if the user cancelled."""
        if not self.dirty:
            return True
        ans = ask(self.root, "Save?", question,
                  [("Save", "save", "primary"), ("Don't save", "no", "normal"),
                   ("Cancel", None, "normal")])
        if ans is None:
            return False
        if ans == "save":
            return self.save()
        return True

    def new_label(self):
        """Start a fresh label of the same kind and size."""
        if not self._ask_save_first("Save your label before starting a new one?"):
            return
        self.set_doc(self._fresh_doc(self.doc.template, self.doc.stock), None)
        self.flash("New label. Type the details on the left.")

    def save(self) -> bool:
        """Save to the current file, or ask for a name. False if cancelled/failed."""
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        """Ask for a name (Ctrl+Shift+S) and save there."""
        from .dialogs import NameDialog
        name = self.doc.title() or "My label"
        target = NameDialog(self.root, name, settings_mod.labels_dir()).run()
        if not target:
            return False
        return self._write(target)

    def _write(self, path) -> bool:
        try:
            p = model.save(self.doc, path)
        except OSError:
            log.exception("save failed")
            tell(self.root, "Couldn't save",
                 "I couldn't save the label there. Please try again, or choose "
                 "“Save somewhere else”.")
            return False
        self.path = str(p)
        self.saved_json = self.doc.dumps()
        self.cfg.add_recent(p, self.doc.title() or p.stem)
        self.refresh_recent()
        self._update_title()
        settings_mod.write_autosave(self.doc, self.path, False)
        self.flash(f"✔ Saved “{p.stem}” in {p.parent.name}.")
        return True

    def open_dialog(self):
        """Show the list of saved labels and open the chosen one."""
        from .dialogs import OpenDialog
        path = OpenDialog(self.root, settings_mod.labels_dir()).run()
        if path:
            self.open_path(path)

    def open_path(self, path):
        """Open a label file, offering to move its dates to today."""
        if self.path and Path(path).resolve() == Path(self.path).resolve() and not self.dirty:
            pass
        elif not self._ask_save_first("Save the label you are working on first?"):
            return
        try:
            doc = model.load(path)
        except model.LabelFileError as e:
            self.cfg.remove_recent(path)
            self.refresh_recent()
            tell(self.root, "Couldn't open", str(e))
            return
        made = doc.made_date()
        today = dates.today()
        if made and made != today:
            ans = ask(self.root, "Update the dates?",
                      f"This label says it was made on {dates.fmt(made)}.\n\n"
                      "Change the dates to today? (The “use by” date moves too, "
                      "keeping the same number of days.)",
                      [("Yes, use today", True, "primary"), ("No, keep them", False, "normal")])
            if ans:
                doc.refresh_dates(today)
        self.set_doc(doc, str(Path(path).resolve()))
        self.cfg.add_recent(path, doc.title() or Path(path).stem)
        self.refresh_recent()
        self.flash(f"Opened “{Path(path).stem}”.")
        # A font this computer doesn't have: say so gently and offer to get it.
        from .font_dialogs import offer_missing_fonts
        if offer_missing_fonts(self.root, self.doc):
            self._sync_ui_from_doc()

    def export_picture(self):
        """Save the printer bitmap as a PNG."""
        res = self.last_result or self.render_now()
        name = model.safe_filename(self.doc.title() or "label")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save a picture of the label",
            initialdir=str(settings_mod.labels_dir()), initialfile=f"{name}.png",
            defaultextension=".png", filetypes=[("Picture", "*.png")])
        if not path:
            return
        try:
            render.export_png(res, path)
            self.flash(f"✔ Picture saved: {Path(path).name}")
        except OSError:
            log.exception("export failed")
            tell(self.root, "Couldn't save picture", "I couldn't save the picture there.")

    # ------------------------------------------------------------------ printing
    def print_dialog(self):
        """Ctrl+P / Print…: confirm, then print_now()."""
        from .dialogs import PrintDialog
        ans = PrintDialog(self.root, self).run()
        if ans == "print":
            self.print_now()

    # ---- printer list ------------------------------------------------------
    def rescan_printers(self, user=False):
        """Look for printers in the background (lpstat/sysfs/EnumPrinters can be slow)."""
        if self._scanning:
            return
        self._scanning = True
        if user:
            self.flash("Looking for printers…")

        def work():
            try:
                found = printers.discover(self.known)
            except Exception:  # noqa: BLE001
                log.exception("discovery failed")
                found = []
            self._scan_q.put(found)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, lambda: self._poll_scan(user))

    def _poll_scan(self, user):
        try:
            found = self._scan_q.get_nowait()
        except queue.Empty:
            self.root.after(100, lambda: self._poll_scan(user))
            return
        self._scanning = False
        self.set_found(found)
        if user:
            n = len(self.found)
            self.flash(f"Found {n} printer{'s' if n != 1 else ''}." if n else
                       "No printers found. Check the printer is plugged in and switched on.")
        if getattr(self, "_rescan_job", None):
            self.root.after_cancel(self._rescan_job)
        self._rescan_job = self.root.after(15000, self.rescan_printers)

    def set_found(self, found):
        """Take a fresh discovery result; auto-select the only label printer if none is chosen."""
        # add printers typed in by hand (network)
        for pid, info in self.cfg["printers"].items():
            if info.get("manual") and info.get("target") and not any(p.id == pid for p in found):
                try:
                    p = printers.network_printer(info["target"], info.get("kind") or "tspl")
                    p.id = pid
                    found.append(p)
                except printers.PrinterError:
                    pass
        self.found = found
        sel = self.cfg["selected"]
        if not sel or (sel not in self.cfg["printers"] and not self.current_printer()):
            pick = printers.auto_pick(found)
            if pick is not None and not sel:
                self.cfg["selected"] = pick.id
                self.cfg.printer_info(pick.id)
                self.cfg.save()
        self.refresh_printer_combo()

    def printer_name(self, p) -> str:
        """The user's nickname for a printer, else its default name."""
        return self.cfg.nickname(p.id) or p.default_name()

    def current_printer(self):
        """The selected printer if it is connected right now, else None."""
        sel = self.cfg["selected"]
        return next((p for p in self.found if p.id == sel), None)

    def printer_dpi(self, p) -> int:
        """A printer's resolution: the user's choice in My printers, else detected."""
        return printers.printer_dpi(p, self.cfg["printers"].get(p.id, {}))

    def current_dpi(self) -> int:
        """Resolution the label is drawn at: the selected printer's (a chosen but
        unplugged printer keeps the user's choice for it); no printer: 203."""
        sel = self.cfg["selected"]
        if not sel:
            return stocks.BASE_DPI
        p = self.current_printer()
        if p is not None:
            return self.printer_dpi(p)
        return printers.printer_dpi(None, self.cfg["printers"].get(sel, {}))

    def _rerender_if_dpi_changed(self):
        """Printer changed to one with another resolution: draw the label again."""
        if self.current_dpi() != self._rendered_dpi:
            self.schedule_render()

    def refresh_printer_combo(self):
        """Rebuild the printer menu above PRINT. A chosen but unplugged printer stays
        listed as "not connected" so the choice isn't silently lost."""
        values, ids = [], []
        for p in self.found:
            values.append(p.display(self.cfg.nickname(p.id)))
            ids.append(p.id)
        sel = self.cfg["selected"]
        if sel and sel not in ids:
            nick = self.cfg.nickname(sel) or "My printer"
            values.insert(0, f"{nick} \u2014 not connected")
            ids.insert(0, sel)
        if not values:
            values = ["No printer found \u2014 plug it in and press \u201cLook for printers again\u201d"]
            ids = [""]
        self._choices = ids
        m = self.printer_menu
        m.delete(0, "end")
        for v, pid in zip(values, ids):
            m.add_radiobutton(label=v, value=pid, variable=self._printer_choice,
                              command=lambda pid=pid: self._menu_picked(pid))
        m.add_separator()
        m.add_command(label="Look for printers again",
                      command=lambda: self.rescan_printers(user=True))
        m.add_command(label="My printer isn't in the list\u2026", command=self.usb_devices)
        self._printer_choice.set(sel)
        idx = ids.index(sel) if sel in ids else -1
        if idx >= 0 and ids[idx]:
            p = next((x for x in self.found if x.id == ids[idx]), None)
            if p is not None:
                short = self.cfg.nickname(p.id) or getattr(p.family, "name", "") or p.default_name()
                text = f"{short} \u2014 {p.port}" if p.port else short
            else:
                text = values[idx]
        elif ids == [""]:
            text = "No printer found \u2014 plug it in, then press \u201cLook for printers again\u201d"
        else:
            text = "Pick your printer here"
        self.printer_btn.configure(text=text + "\u00A0\u00A0\u25BE")  # no-break spaces: the arrow stays with the name
        self.refresh_status()
        self.refresh_roll_notice()
        self._rerender_if_dpi_changed()

    def _menu_picked(self, pid):
        if pid:
            self.select_printer(pid)
        self.printer_box.configure(highlightbackground=PANEL)

    def _status_clicked(self):
        if self.current_printer() is None and self.found:
            self.printer_btn.event_generate("<Button-1>")
        else:
            self.setup_wizard()

    def select_printer(self, pid: str, use_its_size=True):
        """Choose a printer; optionally switch to the label size it printed last."""
        self.cfg["selected"] = pid
        info = self.cfg.printer_info(pid)
        self.cfg.save()
        last = info.get("stock")
        if use_its_size and last and last != self.doc.stock and \
                last in templates.ALLOWED_STOCKS[self.doc.template]:
            self.doc.stock = last
            self._sync_ui_from_doc()
            self._snapshot()
            self.flash(f"This printer last used \u201c{stocks.get(last).name}\u201d labels, "
                       "so I picked that size.", 8000)
        self.refresh_printer_combo()

    # ------------------------------------------------------------------ new roll
    def refresh_roll_notice(self):
        """Show "New roll in the …? Set it up" under the printer when the label size
        differs from the roll last set up on it (see calibrate.show_notice). This
        only shows words and buttons; nothing is ever sent from here."""
        if not hasattr(self, "roll_notice"):
            return
        p = self.current_printer()
        info = self.cfg["printers"].get(p.id, {}) if p is not None else {}
        if p is not None and calibrate.show_notice(info, self.doc.stock):
            self.roll_lbl.configure(text=calibrate.notice_text(self.printer_name(p)))
            self.roll_notice.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        else:
            self.roll_notice.grid_remove()

    def _same_roll(self):
        p = self.current_printer()
        if p is not None:
            calibrate.dismiss_notice(self.cfg.printer_info(p.id), self.doc.stock)
            self.cfg.save()
        self.refresh_roll_notice()

    def _roll_notice_clicked(self):
        p = self.current_printer()
        if p is not None:
            self.setup_roll(self.root, p)

    def setup_roll(self, parent, p=None):
        """Open "Set up a new roll" for printer ``p`` (default: the chosen one).

        Only the window's own "Set it up" button, after its OK question, sends
        anything. If a different label size was set up and this kind of label
        allows it, the label switches to that size. Returns the size set up or None.
        """
        p = p or self.current_printer()
        if p is None:
            self._highlight_printer_box()
            tell(parent, "Which printer?", "Pick your printer first, then set up its roll.")
            return None
        from .picture_dialogs import RollSetupDialog
        got = RollSetupDialog(parent, self, p).run()
        if got and got != self.doc.stock and got in templates.ALLOWED_STOCKS[self.doc.template]:
            self.doc.stock = got
            self._sync_ui_from_doc()
            self._snapshot()
            self.flash(f"Your label is now \u201c{stocks.get(got).name}\u201d, to match the "
                       "roll.", 8000)
        self.refresh_roll_notice()
        return got

    def print_settings_for(self, p) -> dict:
        """This printer's print settings ({} = normal)."""
        return printsettings.clean(self.cfg["printers"].get(p.id, {}).get("print"))

    def print_settings(self):
        """"Print settings…" next to the printer: darkness, speed, nudge, … for it."""
        p = self.current_printer()
        if p is None:
            self._highlight_printer_box()
            tell(self.root, "Which printer?", "Pick your printer first; print settings are "
                 "kept for each printer.")
            return
        from .picture_dialogs import PrintSettingsDialog
        PrintSettingsDialog(self.root, self, p).run()
        self.refresh_roll_notice()

    def pick_picture(self):
        """Kind bar → Picture: add, change or take off the label's picture."""
        from .picture_dialogs import PictureDialog
        got = PictureDialog(self.root, self).run()
        if got is None:
            return
        self.doc.picture = None if got == "remove" else got
        self._sync_ui_from_doc()
        self._snapshot()

    def pick_qr(self):
        """Kind bar → QR code: add, change or take off the label's QR code."""
        from .picture_dialogs import QrDialog
        got = QrDialog(self.root, self).run()
        if got is None:
            return
        self.doc.qr = None if got == "remove" else got
        self._sync_ui_from_doc()
        self._snapshot()

    def printer_config(self, p) -> dict:
        """Printer.config() with the user's overrides: language ("Type") and the
        Windows "print through driver" fallback."""
        info = self.cfg["printers"].get(p.id, {})
        cfg = p.config(info.get("kind") or "")
        if info.get("via_driver") and p.method == "windows_raw":
            cfg["method"] = "windows_driver"      # fallback: picture through the driver
        return cfg

    def _highlight_printer_box(self):
        self.printer_box.configure(highlightbackground=WARN)
        self.root.after(8000, lambda: self.printer_box.configure(highlightbackground=PANEL))

    def print_now(self):
        """PRINT: check the label fits and a printer is there, then send in the background."""
        if self._printing:
            return
        res = self.render_now()
        if res.overflow:
            fr = self.field_frames.get(res.problem_field)
            if fr is not None:
                self.scroll.scroll_to(fr)
            tell(self.root, "Too much writing", res.message)
            return
        if not res.layout.lines and not res.layout.qr and not res.layout.images:
            tell(self.root, "Nothing to print yet",
                 "The label is empty. Type something on the left first.")
            return
        if self.doc.template == "cottage" and not self._cottage_ok_to_print():
            return
        p = self.current_printer()
        sel = self.cfg["selected"]
        if p is None:
            self._highlight_printer_box()
            if sel:
                nick = self.cfg.nickname(sel) or "My printer"
                tell(self.root, "Printer not connected",
                     f"Your printer \u201c{nick}\u201d isn't connected. Pick one from the list.")
            elif self.found:
                tell(self.root, "Which printer?",
                     "Please pick your printer from the list next to \u201cPrinter:\u201d.")
            elif ask(self.root, "Printer", printers.MSG_NO_PRINTER + "\n\nSet it up now?",
                     [("Set up my printer", True, "primary"), ("Not now", False, "normal")]):
                self.setup_wizard()
            return
        n = self.doc.copies
        if n > 20 and not ask(self.root, "Lots of labels",
                              f"Print {n} labels? That's quite a lot.",
                              [(f"Yes, print {n}", True, "primary"), ("No", False, "normal")]):
            return
        stock = res.stock
        if stock.dpi != self.printer_dpi(p):     # printer changed since the last render
            res = self.render_now()
            stock = res.stock
        fam = p.family
        wide = printers.too_wide_message(stock, fam)
        if wide:
            tell(self.root, "Label too wide", wide)
            return
        if fam is not None and stock.id not in fam.stocks:
            if not ask(self.root, "Label size",
                       f"This printer might not take \u201c{stock.name}\u201d labels. Print anyway?",
                       [("Print anyway", True, "primary"), ("Cancel", False, "normal")]):
                return
        ps = self.print_settings_for(p)
        img = printsettings.adjust_image(res.image, stock, ps)
        try:
            data = printers.build_job(img, stock, self.printer_config(p),
                                      self.cfg["advanced"], n, family=fam, print_settings=ps)
        except printers.PrinterError as e:
            tell(self.root, "Printing didn't work", str(e))
            return
        self.cfg.printer_info(p.id)["stock"] = stock.id
        self.cfg.save()
        self._start_print(self.printer_config(p), data, img, n,
                          f"\u2714 Done! {n} label{'s' if n != 1 else ''} sent to "
                          f"{self.printer_name(p)}.")

    def print_text_label(self, p, lines, stock_id=None):
        """Test / identify labels (only ever on a click)."""
        stock = stocks.get(stock_id or self.cfg["printers"].get(p.id, {}).get("stock")
                           or self.doc.stock, self.printer_dpi(p))
        ps = self.print_settings_for(p)
        img = printsettings.adjust_image(render.render_text_label(lines, stock), stock, ps)
        try:
            data = printers.build_job(img, stock, self.printer_config(p), self.cfg["advanced"],
                                      1, family=p.family, print_settings=ps)
        except printers.PrinterError as e:
            tell(self.root, "Printing didn't work", str(e))
            return
        self._start_print(self.printer_config(p), data, img, 1,
                          f"\u2714 Sent a test label to {self.printer_name(p)}.")

    def _start_print(self, pcfg, data, image, n, done_text):
        # Sending can block for seconds (spooler, USB, network): do it on a
        # thread and report back through self._q, polled from the Tk loop.
        self._printing = True
        self.print_btn.configure(state="disabled", text="Printing\u2026")
        self.flash(f"Printing {n} label{'s' if n != 1 else ''}\u2026", 60000)

        def work():
            try:
                printers.send(pcfg, data, image=image, copies=n)
                self._q.put(("ok", done_text))
            except printers.PrinterError as e:
                self._q.put(("err", str(e)))
            except Exception:  # noqa: BLE001
                log.exception("print crashed")
                self._q.put(("err", printers.MSG_NOT_ANSWERING))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._poll_print)

    def _poll_print(self):
        try:
            kind, text = self._q.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_print)
            return
        self._printing = False
        self.print_btn.configure(state="normal", text="PRINT")
        if kind == "ok":
            self.flash(text, 10000)
        else:
            self.flash("")
            tell(self.root, "Printing didn't work", text)
        self.refresh_status()

    def refresh_status(self):
        """Update the line under the printer menu (ready / not connected / offline…)."""
        p = self.current_printer()
        sel = self.cfg["selected"]
        if p is None and sel:
            state, text = "problem", f"\u201c{self.cfg.nickname(sel) or 'My printer'}\u201d isn't connected"
        elif p is None and self.found:
            state, text = "problem", "Pick your printer in the list above"
        else:
            state, text = printers.status(p, self.printer_name(p) if p else "")
        self.status_lbl.configure(text=text, fg=GREEN_DARK if state == "ready" else WARN)

    def usb_devices(self):
        """The "My printer isn't in the list" window (all USB devices)."""
        from .dialogs import UsbDevicesDialog
        UsbDevicesDialog(self.root, self).run()
        self.rescan_printers()

    def my_printers(self):
        """The "My printers…" window: names, identify, type."""
        from .dialogs import MyPrintersDialog
        MyPrintersDialog(self.root, self).run()
        self.refresh_printer_combo()

    def setup_wizard(self):
        """Three-step printer setup with a test label."""
        from .dialogs import SetupWizard
        SetupWizard(self.root, self).run()
        self.refresh_status()

    # ------------------------------------------------------------------ cottage food
    @property
    def ingredients(self) -> bakery.Ingredients:
        """My ingredients (read on first use; the starter list is copied in then)."""
        if self._ingredients is None:
            self._ingredients = bakery.Ingredients(settings_mod.data_dir()
                                                   / bakery.INGREDIENTS_NAME)
        return self._ingredients

    @property
    def products(self) -> bakery.Products:
        if self._products is None:
            self._products = bakery.Products(settings_mod.data_dir() / bakery.PRODUCTS_NAME)
        return self._products

    def cottage_rule(self) -> cottage.Effective:
        """The chosen state's rules with the user's own edits."""
        return self.rules.effective(self.profile["state"] or cottage.CUSTOM_ID)

    def render_ctx(self) -> dict:
        """Settings that change the printout, plus the cottage rules and My bakery."""
        ctx = self.cfg.render_ctx()
        ctx["cottage"] = {"rule": self.cottage_rule().to_ctx(), "profile": dict(self.profile.data)}
        return ctx

    def _bakery_start(self):
        """Once, at start: offer "Set up my bakery"; later, ask about state wording
        that changed under the user's own edits."""
        try:
            if not self.profile.exists and not self.cfg["bakery_offered"]:
                self.cfg["bakery_offered"] = True
                self.cfg.save()
                if ask(self.root, "Do you sell home-baked food?",
                       "Food Labeler can make labels for home bakers with the wording your "
                       "state asks for. Set that up now? (You can always do it later in "
                       "Settings.)",
                       [("Set up my bakery", True, "primary"), ("Not now", False, "normal")]):
                    self.bakery_wizard()
                return
            if self.profile["state"] and self.rules.pending_changes(self.profile["state"]):
                from .bakery_dialogs import ask_about_changes
                ask_about_changes(self.root, self)
                self._sync_ui_from_doc()
        except Exception:  # noqa: BLE001 - never stop the app over this
            log.exception("bakery start")

    def _cottage_form(self, f):
        """The cottage food label form (fields from the label; the rest from My bakery)."""
        eff = self.cottage_rule()
        top = tk.Frame(f, bg=PANEL, padx=16, pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Rules for:", font="ui", bg=PANEL, fg=MUTED).pack(side="left")
        tk.Label(top, text=eff.name if self.profile["state"] else "not chosen yet",
                 font="ui_bold", bg=PANEL, fg=INK).pack(side="left", padx=6)
        button(top, "My bakery…", self.my_bakery, "chip").pack(side="right")
        self.check_frame = tk.Frame(f, bg=PANEL, padx=12, pady=8, highlightthickness=2,
                                    highlightbackground=BORDER)
        self.check_frame.pack(fill="x", padx=14, pady=(4, 0))
        self._check_sig = None
        row = tk.Frame(f, bg=PANEL, padx=14)
        row.pack(fill="x", pady=(10, 0))
        button(row, "Choose from My products…", self.choose_product).pack(side="left")
        button(row, "Save to My products", self.save_product, "chip").pack(side="left", padx=8)
        self.entry_field(f, "product", "Product name", big=True)
        fr = self.entry_field(f, "net", "Net weight (for example 8 oz, 1.5 lb or 12 cookies)")
        self.net_hint = tk.Label(fr, text="", font="ui", bg=PANEL, fg=MUTED, anchor="w",
                                 justify="left")
        self.net_hint.pack(anchor="w", pady=(2, 0))
        fr = self.text_field(f, "ingredients", "Ingredients, heaviest first", 3)
        button(fr, "Build from My ingredients…", self.build_ingredients, "chip").pack(
            anchor="w", pady=(6, 0))
        self.allergen_field(f, "contains", "Contains (allergens)  —  tap any that are in it")
        cf = self.field_frames["contains"]

        def none_flip():
            self.doc.fields["no_allergens"] = none.value
            if none.value and self.field_setters.get("contains"):
                self.field_setters["contains"]("")
            self.changed()
        none = Toggle(cf, "None of these 9 allergens are in it", none_flip,
                      bool(self.doc.fields.get("no_allergens")))
        none.pack(anchor="w", pady=(6, 0))
        self.entry_field(f, "storage", "How to store it (if you want it on the label)")
        self.chips(f, "storage", model.STORAGE_CHIPS)
        self.date_field(f, "made_on", "Made on", today_button=True)
        self._show_date_toggle(self.field_frames["made_on"], "show_made", "date_made", eff)
        self.date_field(f, "best_by", "Best by", quick_from="made_on")
        self._show_date_toggle(self.field_frames["best_by"], "show_best_by", "sell_by", eff)

    def _show_date_toggle(self, frame, flag, field_id, eff):
        if field_id in eff.required:
            tk.Label(frame, text=f"Always on the label: {eff.name} asks for it.", font="ui",
                     bg=PANEL, fg=MUTED).pack(anchor="w", pady=(6, 0))
            return

        def flip():
            self.doc.fields[flag] = tg.value
            self.changed()
        tg = Toggle(frame, "Put this date on the label", flip, bool(self.doc.fields.get(flag)))
        tg.pack(anchor="w", pady=(6, 0))

    def refresh_check(self, res):
        """Redraw the Label check (green = there, red = missing) if anything changed."""
        fr = self.check_frame
        try:
            if fr is None or not fr.winfo_exists():
                return
        except tk.TclError:
            return
        eff = self.cottage_rule()
        ctx = eff.to_ctx()
        items = cottage.check_label(self.doc.fields, self.profile.data, ctx)
        if self.net_hint is not None and self.net_hint.winfo_exists():
            metric = self.profile.metric_for(eff.rule.metric_required)
            net = cottage.format_net(self.doc.fields.get("net"), metric)
            self.net_hint.configure(text=f"Prints as: {net}" if net else "")
        sig = (tuple((i.key, i.ok, i.label) for i in items), res.overflow, eff.id)
        if sig == self._check_sig:
            return
        self._check_sig = sig
        for w in fr.winfo_children():
            w.destroy()
        bad = cottage.missing(items)
        if bad:
            title = f"Label check: {len(bad)} thing{'s' if len(bad) != 1 else ''} missing"
        else:
            title = f"Label check: all {len(items)} things are there"
        tk.Label(fr, text=title, font="ui_bold", bg=PANEL, wraplength=520, justify="left",
                 fg=WARN if bad else GREEN_DARK).pack(anchor="w")
        # Only the missing items are listed, so the form below stays in view on a
        # laptop screen; "About ...'s rules" shows everything the state asks for.
        for it in bad:
            text = "✘ " + it.label + (f" — {it.hint}" if it.hint else "")
            tk.Label(fr, text=text, font="ui", bg=PANEL, fg=GREEN_DARK if it.ok else WARN,
                     wraplength=520, justify="left").pack(anchor="w")
        if res.overflow:
            tk.Label(fr, text="✘ It doesn't fit on this label size (see the message on the "
                     "right)", font="ui", bg=PANEL, fg=WARN, wraplength=520,
                     justify="left").pack(anchor="w")
        rule = eff.rule
        if not self.profile["state"]:
            tk.Label(fr, text="Choose your state in My bakery to get its wording.", font="ui",
                     bg=PANEL, fg=WARN, wraplength=520, justify="left").pack(anchor="w")
        elif rule.sales_allowed is False:
            tk.Label(fr, text="The public guidance we found says home-baked goods can't be "
                     "sold this way here. Please check with your state.", font="ui", bg=PANEL,
                     fg=WARN, wraplength=520, justify="left").pack(anchor="w")
        elif rule.id != cottage.CUSTOM_ID and not rule.verified:
            tk.Label(fr, text="Unverified — check with your state.", font="ui", bg=PANEL,
                     fg=WARN).pack(anchor="w")
        tk.Label(fr, text=cottage.RESPONSIBILITY, font="small", bg=PANEL, fg=MUTED,
                 wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))
        button(fr, f"About {rule.name}'s rules…", self.about_rules, "quiet").pack(anchor="w")

    def about_rules(self):
        eff = self.cottage_rule()
        rule = eff.rule
        items = cottage.check_label(self.doc.fields, self.profile.data, eff.to_ctx())
        parts = ["What the label needs:\n" + "\n".join(
            ("✔ " if i.ok else "✘ ") + i.label for i in items)]
        parts.append(rule.notes or "No notes.")
        if rule.source_url:
            parts.append("Source: " + rule.source_url
                         + (f" (checked {rule.checked_on})" if rule.checked_on else ""))
        parts.append(cottage.RESPONSIBILITY)
        tell(self.root, f"{rule.name}: cottage food rules", "\n\n".join(parts))

    def _cottage_ok_to_print(self) -> bool:
        """Ask (never block) when the Label check finds something missing."""
        eff = self.cottage_rule()
        bad = cottage.missing(cottage.check_label(self.doc.fields, self.profile.data,
                                                  eff.to_ctx()))
        if not bad:
            return True
        names = [i.label for i in bad]
        what = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        who = "Your state requires" if eff.id != cottage.CUSTOM_ID else "Your rules ask for"
        return bool(ask(self.root, "Label check",
                        f"{who} {what} on the label. Print anyway?",
                        [("Go back and fix it", False, "primary"),
                         ("Print anyway", True, "warn")]))

    def bakery_wizard(self):
        """First-run "Set up my bakery" (also in Settings)."""
        from .bakery_dialogs import BakeryWizard
        if BakeryWizard(self.root, self).run():
            self._sync_ui_from_doc()

    def my_bakery(self):
        """Settings → My bakery: state, details, wording, required items."""
        from .bakery_dialogs import MyBakeryDialog
        MyBakeryDialog(self.root, self).run()
        self._sync_ui_from_doc()

    def build_ingredients(self):
        """Pick from My ingredients: fills the ingredient line and the allergens."""
        from .bakery_dialogs import IngredientPicker
        picked = IngredientPicker(self.root, self).run()
        if not picked:
            return
        self.doc.fields["ingredients"] = bakery.build_ingredients(picked)
        allergens = bakery.allergens_for(picked)
        if allergens:
            self.doc.fields["contains"] = ", ".join(allergens)
            self.doc.fields["no_allergens"] = False
        self._sync_ui_from_doc()
        self.changed()
        if any(p.get("check") for p in picked):
            self.flash("Some ingredients are starter examples: check them against your "
                       "packages (My ingredients → Change…).", 10000)

    def choose_product(self):
        from .bakery_dialogs import ProductPicker
        p = ProductPicker(self.root, self).run()
        if not p:
            return
        self.doc.fields = bakery.apply_product(self.doc.fields, p)
        self._sync_ui_from_doc()
        self.changed()

    def save_product(self):
        from .bakery_dialogs import ask_text
        name = str(self.doc.fields.get("product") or "").strip()
        name = ask_text(self.root, "Save to My products", "What is this product called?", name)
        if not name:
            return
        existing = self.products.find(name)
        if existing and not ask(self.root, "Replace?",
                                f"You already have “{name}” in My products. Replace it?",
                                [("Replace it", True, "primary"), ("Cancel", False, "normal")]):
            return
        entry = bakery.product_from_fields(self.doc.fields, name,
                                           existing["id"] if existing else None)
        self.products.put(entry)
        self.flash(f"✔ Saved “{name}” to My products.")

    def my_products(self):
        """Settings → My products (choosing one switches to a cottage label)."""
        from .bakery_dialogs import ProductPicker
        p = ProductPicker(self.root, self).run()
        if not p:
            return
        if self.doc.template != "cottage":
            self.doc.set_template("cottage")
            if self.doc.stock not in templates.ALLOWED_STOCKS["cottage"]:
                self.doc.stock = "large"
        self.doc.fields = bakery.apply_product(self.doc.fields, p)
        self._sync_ui_from_doc()
        self.changed()

    def settings_dialog(self):
        """Settings; afterwards re-apply kitchen details and redraw."""
        from .dialogs import SettingsDialog
        SettingsDialog(self.root, self).run()
        self.cfg.save()
        self._fill_kitchen(self.doc)
        self._sync_ui_from_doc()
        self.refresh_status()

    # ------------------------------------------------------------------ errors & close
    def on_error(self, exc, val, tb):
        """Any uncaught Tk callback error: log it, autosave, show a calm message."""
        log.error("unexpected error", exc_info=(exc, val, tb))
        try:
            settings_mod.write_autosave(self.doc, self.path, self.dirty)
        except Exception:  # noqa: BLE001
            pass
        try:
            tell(self.root, "Sorry",
                 "Sorry, something went wrong. Your label is safe.\n\n"
                 "If it keeps happening, ask your helper to look at the log file:\n"
                 f"{settings_mod.data_dir() / 'food-labeler.log'}")
        except Exception:  # noqa: BLE001
            pass

    def on_close(self):
        """Window closed: offer to save, then write a final autosave."""
        if self.dirty:
            ans = ask(self.root, "Save?", "Save your label before closing?",
                      [("Save", "save", "primary"), ("Don't save", "no", "normal"),
                       ("Cancel", None, "normal")])
            if ans is None:
                return
            if ans == "save" and not self.save():
                return
        try:
            settings_mod.write_autosave(self.doc, self.path, self.dirty)
        except Exception:  # noqa: BLE001
            log.exception("final autosave")
        self.cfg.save()
        self.root.destroy()


def main(argv=None):
    """Start the app. A .label file given on the command line (double-click, or
    the Linux menu entry's %f) is opened once the window is up."""
    settings_mod.setup_logging()
    cfg = settings_mod.Settings()
    root = tk.Tk(className="FoodLabeler")
    app = App(root, cfg)
    files = [a for a in (argv or []) if not a.startswith("-") and Path(a).is_file()]
    if files:
        root.after(300, lambda: app.open_path(files[0]))
    root.mainloop()
    return app
