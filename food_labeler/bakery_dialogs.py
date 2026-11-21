"""Windows for cottage food labels: "Set up my bakery", My bakery settings,
My ingredients, My products, and the "your state's wording was updated" question.

Like dialogs.py, every window is a widgets.Modal and talks to the main window
through ``app`` (app.rules, app.profile, app.ingredients, app.products). All the
rules and file handling lives in cottage.py and bakery.py; this file is only
the screens.
"""
from __future__ import annotations

import logging
import tkinter as tk
import webbrowser
from tkinter import filedialog

from . import bakery, cottage, model
from .widgets import (BG, BORDER, GREEN, GREEN_DARK, INK, MUTED, PANEL, WARN, Modal,
                      ScrollFrame, Toggle, ask, button, tell)

log = logging.getLogger("food_labeler.bakery_dialogs")

DETAIL_FIELDS = [
    ("business", "Business name (as customers know you)"),
    ("legal_entity", "Legal name, if different (for example an LLC)"),
    ("street", "Street address"),
    ("street2", "Apartment or unit (if any)"),
    ("city", "City"),
    ("region", "State"),
    ("zip", "ZIP code"),
    ("phone", "Phone number"),
    ("email", "Email address"),
    ("permit", "Permit or registration number (if you have one)"),
    ("county", "County (only if your state's wording asks for it)"),
]


def _label(parent, text, font="ui", fg=INK, bg=BG, wrap=700, **kw):
    lbl = tk.Label(parent, text=text, font=font, bg=bg, fg=fg, wraplength=wrap,
                   justify="left", **kw)
    return lbl


def _entry(parent, value, width=40):
    var = tk.StringVar(value=value)
    e = tk.Entry(parent, textvariable=var, font="field", width=width, relief="flat",
                 highlightthickness=2, highlightbackground=BORDER, highlightcolor=GREEN,
                 bg="#FFFFFF", fg=INK)
    return var, e


def _text(parent, value, height=3, width=56):
    t = tk.Text(parent, font="field", height=height, width=width, wrap="word", relief="flat",
                highlightthickness=2, highlightbackground=BORDER, highlightcolor=GREEN,
                bg="#FFFFFF", fg=INK, padx=6, pady=4)
    t.insert("1.0", value)
    return t


def link(parent, url, text=None, bg=BG):
    """A clickable web address (opens the browser only when clicked)."""
    lbl = tk.Label(parent, text=text or url, font="small", bg=bg, fg=GREEN_DARK,
                   cursor="hand2", wraplength=700, justify="left")
    lbl.bind("<Button-1>", lambda e: webbrowser.open(url))
    return lbl


def responsibility(parent, rule: cottage.StateRule, bg=BG):
    """The "these are suggestions" note with the state's source link."""
    fr = tk.Frame(parent, bg=bg)
    _label(fr, cottage.RESPONSIBILITY, font="ui_bold", fg=INK, bg=bg).pack(anchor="w")
    if rule.id != cottage.CUSTOM_ID:
        status = ("Checked against the official source on " + rule.checked_on
                  if rule.verified and rule.checked_on else
                  "Unverified — check with your state.")
        _label(fr, status, font="small", fg=MUTED if rule.verified else WARN, bg=bg).pack(
            anchor="w", pady=(2, 0))
    if rule.source_url:
        link(fr, rule.source_url, "Source: " + rule.source_url, bg=bg).pack(anchor="w")
    return fr


def ask_text(parent, title, question, value="") -> str | None:
    """One line of text, or None if cancelled."""
    m = Modal(parent, title)
    _label(m.body, question, font="big").pack(anchor="w", pady=(0, 8))
    var, e = _entry(m.body, value)
    e.pack(fill="x", ipady=6)
    e.focus_set()
    e.bind("<Return>", lambda ev: m.finish(var.get().strip()))
    row = tk.Frame(m.body, bg=BG)
    row.pack(fill="x", pady=(14, 0))
    button(row, "OK", lambda: m.finish(var.get().strip()), "primary").pack(side="left")
    button(row, "Cancel", m.cancel, "quiet").pack(side="right")
    return m.run()


# ---------------------------------------------------------------------------
# choosing a state
# ---------------------------------------------------------------------------

def state_choices(rules: cottage.CottageRules) -> list[tuple[str, str]]:
    out = []
    for r in rules.states():
        tag = ""
        if r.id != cottage.CUSTOM_ID:
            if r.sales_allowed is False:
                tag = "  (home baked goods: not allowed, see notes)"
            elif not r.verified:
                tag = "  (unverified)"
        out.append((r.id, r.name + tag))
    return out


class StateList(tk.Frame):
    """A big list of states; .get() returns the chosen preset id or ""."""

    def __init__(self, parent, rules, current=""):
        super().__init__(parent, bg=BG)
        self.choices = state_choices(rules)
        self.lb = tk.Listbox(self, font="ui", height=10, width=48, activestyle="none",
                             selectbackground=GREEN, exportselection=False)
        sb = tk.Scrollbar(self, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        for _sid, text in self.choices:
            self.lb.insert("end", text)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ids = [c[0] for c in self.choices]
        if current in ids:
            i = ids.index(current)
            self.lb.selection_set(i)
            self.lb.see(i)

    def get(self) -> str:
        sel = self.lb.curselection()
        return self.choices[sel[0]][0] if sel and sel[0] < len(self.choices) else ""


# ---------------------------------------------------------------------------
# first run: Set up my bakery
# ---------------------------------------------------------------------------

class BakeryWizard(Modal):
    """Three big steps: your state -> your details -> done."""

    def __init__(self, parent, app):
        super().__init__(parent, "Set up my bakery")
        self.app = app
        self.state = app.profile["state"]
        self.frame = tk.Frame(self.body, bg=BG, width=760)
        self.frame.pack(fill="both", expand=True)
        self.vars = {}
        self.step1()

    def _clear(self, n, title):
        for w in self.frame.winfo_children():
            w.destroy()
        _label(self.frame, f"Step {n} of 3", fg=MUTED).pack(anchor="w")
        _label(self.frame, title, font="big").pack(anchor="w", pady=(2, 12))

    def step1(self):
        self._clear(1, "Which state do you sell in?")
        _label(self.frame, "Food Labeler puts the wording your state asks for on your labels. "
               "Pick your state (or “Custom” to type your own rules).").pack(
            anchor="w", pady=(0, 8))
        self.lst = StateList(self.frame, self.app.rules, self.state)
        self.lst.pack(fill="x")
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=(20, 0))
        button(row, "Cancel", self.cancel, "quiet").pack(side="left")
        button(row, "Next ▶", self._picked, "primary").pack(side="right")

    def _picked(self):
        sid = self.lst.get()
        if not sid:
            tell(self, "Pick one", "Please tap your state in the list first.")
            return
        self.state = sid
        self.step2()

    def step2(self):
        self._clear(2, "Your bakery's details")
        _label(self.frame, "These go on your labels. You can change them later in "
               "Settings → My bakery.").pack(anchor="w", pady=(0, 8))
        sf = ScrollFrame(self.frame, bg=BG)
        sf.configure(width=740, height=min(420, self.winfo_screenheight() - 360))
        sf.pack_propagate(False)
        sf.pack(fill="both", expand=True)
        p = self.app.profile
        for key, title in DETAIL_FIELDS:
            _label(sf.inner, title, font="ui_bold").pack(anchor="w", pady=(6, 0))
            var, e = _entry(sf.inner, self.vars[key].get() if key in self.vars else p[key])
            e.pack(fill="x", ipady=4)
            self.vars[key] = var
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        button(row, "◀ Back", self.step1, "quiet").pack(side="left")
        button(row, "Next ▶", self.step3, "primary").pack(side="right")

    def step3(self):
        details = {k: v.get().strip() for k, v in self.vars.items()}
        self._clear(3, "All set!")
        rule = self.app.rules.base(self.state)
        _label(self.frame, f"Your cottage food labels will follow the suggestions for "
               f"{rule.name}.").pack(anchor="w")
        if not bakery.address_lines(details):
            _label(self.frame, "Your full address (street, city, state and ZIP) isn't complete "
                   "yet. The Label check will remind you.", fg=WARN).pack(anchor="w",
                                                                           pady=(8, 0))
        if rule.sales_allowed is False:
            _label(self.frame, "Note: the public guidance we found says home-baked goods "
                   "can't be sold this way in " + rule.name + ". Please check with your state.",
                   fg=WARN).pack(anchor="w", pady=(8, 0))
        responsibility(self.frame, rule).pack(anchor="w", pady=(12, 0))
        row = tk.Frame(self.frame, bg=BG)
        row.pack(fill="x", pady=(20, 0))
        button(row, "◀ Back", self.step2, "quiet").pack(side="left")
        button(row, "Finish", lambda: self._finish(details), "primary").pack(side="right")

    def _finish(self, details):
        p = self.app.profile
        p.data.update(details)
        p["state"] = self.state
        p["setup_done"] = True
        p.save()
        k = self.app.cfg["kitchen"]
        if not str(k.get("business") or "").strip() and details.get("business"):
            k["business"] = details["business"]          # also used by simple labels
            self.app.cfg.save()
        self.finish(True)


# ---------------------------------------------------------------------------
# Settings -> My bakery
# ---------------------------------------------------------------------------

class MyBakeryDialog(Modal):
    """State, kitchen details, label options, the wording and required items."""

    def __init__(self, parent, app):
        super().__init__(parent, "My bakery")
        self.app = app
        self.sf = ScrollFrame(self.body, bg=BG)
        self.sf.configure(width=800, height=min(640, parent.winfo_screenheight() - 200))
        self.sf.pack_propagate(False)
        self.sf.pack(fill="both", expand=True)
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(12, 0))
        button(row, "Done", self._done, "primary").pack(side="right")
        self._draw()

    # -- helpers -------------------------------------------------------------
    def heading(self, text):
        _label(self.b, text, font="big", fg=GREEN_DARK).pack(anchor="w", pady=(18, 6))

    @property
    def sid(self):
        return self.app.profile["state"] or cottage.CUSTOM_ID

    def _draw(self):
        """(Re)build everything from the current profile and rules."""
        for w in self.sf.inner.winfo_children():
            w.destroy()
        self.b = b = self.sf.inner
        p = self.app.profile
        rules = self.app.rules
        rule = rules.base(self.sid)
        eff = rules.effective(self.sid)

        self.heading("My state")
        row = tk.Frame(b, bg=BG)
        row.pack(anchor="w", fill="x")
        _label(row, rule.name, font="ui_bold").pack(side="left")
        button(row, "Change…", self._change_state, "chip").pack(side="left", padx=10)
        responsibility(b, rule).pack(anchor="w", pady=(6, 0))
        if rule.sales_allowed is False:
            _label(b, "The public guidance we found says home-baked goods can't be sold this "
                   "way here. Please check with your state.", fg=WARN).pack(anchor="w")
        if rule.notes:
            _label(b, rule.notes, font="small", fg=MUTED).pack(anchor="w", pady=(6, 0))

        self.heading("My kitchen details")
        self.vars = {}
        for key, title in DETAIL_FIELDS:
            _label(b, title, font="ui_bold").pack(anchor="w", pady=(6, 0))
            var, e = _entry(b, p[key])
            e.pack(fill="x", ipady=4)
            self.vars[key] = var
        _label(b, "Words before your permit number on the label", font="ui_bold").pack(
            anchor="w", pady=(6, 0))
        self.vars["permit_label"], e = _entry(b, p["permit_label"], 20)
        e.pack(anchor="w", ipady=4)

        self.heading("On the label")
        self.metric = None
        if rule.metric_required:
            _label(b, "Grams are always shown next to ounces: " + rule.name + " asks for it.",
                   fg=MUTED).pack(anchor="w")
        else:
            self.metric = tk.StringVar(value={None: "off", True: "on", False: "off"}.get(
                p["metric"], "auto"))
            for val, text in [("off", "Weight in ounces and pounds only"),
                              ("on", "Also show grams, for example 8 oz (226 g)")]:
                tk.Radiobutton(b, text=text, value=val, variable=self.metric, font="ui",
                               bg=BG, activebackground=BG, selectcolor="white").pack(anchor="w")
        self.show_phone = Toggle(b, "Put my phone number on the label", None, p["show_phone"])
        self.show_phone.pack(anchor="w", pady=(6, 2))
        self.show_email = Toggle(b, "Put my email address on the label", None, p["show_email"])
        self.show_email.pack(anchor="w", pady=2)
        _label(b, "Cross-contact notice (optional)", font="ui_bold").pack(anchor="w",
                                                                          pady=(8, 0))
        self.cross = _text(b, p["cross_contact"], 3)
        self.cross.pack(fill="x")
        button(b, "Use the usual wording", lambda: (self.cross.delete("1.0", "end"),
                                                    self.cross.insert("1.0",
                                                                      model.DEFAULT_CROSS_CONTACT)),
               "chip").pack(anchor="w", pady=(4, 0))
        _label(b, "Only if it is true for your kitchen: list what else you bake with.",
               font="small", fg=MUTED).pack(anchor="w")

        self.heading("Wording on the label")
        self.stmt_widgets = {}
        if not eff.statements:
            _label(b, "No required wording for this state." if rule.id != cottage.CUSTOM_ID
                   else "Add the wording your state or county asks for below.",
                   fg=MUTED).pack(anchor="w")
        for st in eff.statements:
            box = tk.Frame(b, bg=PANEL, highlightthickness=1, highlightbackground=BORDER,
                           padx=10, pady=8)
            box.pack(fill="x", pady=4)
            top = tk.Frame(box, bg=PANEL)
            top.pack(fill="x")
            size = eff.min_pt(st)
            title = "Your own statement" if st.own else "Statement"
            if size:
                title += f" (printed at least {cottage._trim(size, 1)} pt tall)"
            _label(top, title, font="ui_bold", bg=PANEL).pack(side="left")
            if st.edited:
                _label(top, "  ✎ edited by you", font="ui_bold", fg=WARN, bg=PANEL).pack(
                    side="left")
            t = _text(box, st.text, 3)
            t.pack(fill="x", pady=(4, 0))
            self.stmt_widgets[st.id] = (t, st.text)
            r2 = tk.Frame(box, bg=PANEL)
            r2.pack(fill="x", pady=(4, 0))
            if st.own:
                button(r2, "Remove", lambda i=st.id: self._reset_stmt(i), "chip").pack(
                    side="left")
            elif st.edited:
                button(r2, "Reset to state default", lambda i=st.id: self._reset_stmt(i),
                       "chip").pack(side="left")
                if st.default:
                    _label(box, "State's suggestion: " + st.default, font="small", fg=MUTED,
                           bg=PANEL).pack(anchor="w", pady=(4, 0))
        alts = rules.other_statements(rule, "alternative")
        if alts and eff.statements:
            _label(b, "Other wording your state allows:", font="ui_bold").pack(anchor="w",
                                                                              pady=(8, 0))
            first = next((s for s in eff.statements if not s.own), None)
            for a in alts:
                row = tk.Frame(b, bg=BG)
                row.pack(fill="x", pady=2)
                _label(row, "“" + a["text"] + "”", wrap=520).pack(side="left")
                if first is not None:
                    button(row, "Use this", lambda t=a["text"], i=first.id: self._use_alt(i, t),
                           "chip").pack(side="right")
        mine = {s.text for s in eff.statements}
        for o in rules.other_statements(rule, "optional"):
            row = tk.Frame(b, bg=BG)
            row.pack(fill="x", pady=(8, 2))
            size = f" (at least {cottage._trim(o['min_pt'], 1)} pt)" if o.get("min_pt") else ""
            _label(row, "Needed only for some foods (see the notes above)" + size + ":\n“"
                   + o["text"] + "”", wrap=520).pack(side="left")
            if o["text"] not in mine:
                button(row, "Add to my label",
                       lambda o=o: self._add_optional(o), "chip").pack(side="right")
        signs = rules.other_statements(rule, "sign")
        for s in signs:
            _label(b, "For a sign where you sell (not the label): “" + s["text"] + "”",
                   font="small", fg=MUTED).pack(anchor="w", pady=(6, 0))
        button(b, "Add my own statement…", self._add_own).pack(anchor="w", pady=(8, 0))

        self.heading("What must be on the label")
        _label(b, "Ticked items are checked by the Label check before printing.",
               fg=MUTED).pack(anchor="w")
        if eff.required_edited:
            r = tk.Frame(b, bg=BG)
            r.pack(anchor="w", pady=(4, 0))
            _label(r, "✎ edited by you", font="ui_bold", fg=WARN).pack(side="left")
            button(r, "Reset to state default", self._reset_required, "chip").pack(
                side="left", padx=10)
        self.req_toggles = {}
        grid = tk.Frame(b, bg=BG)
        grid.pack(anchor="w", fill="x")
        for i, (key, title) in enumerate(cottage.FIELDS.items()):
            tg = Toggle(grid, title, None, key in eff.required)
            tg.grid(row=i, column=0, sticky="ew", pady=2)
            self.req_toggles[key] = tg

        self.heading("State rules updates")
        _label(b, "High Thyme Kitchen may send a file with newer state rules. Your own "
               "changes above are kept.", fg=MUTED).pack(anchor="w")
        button(b, "Add state rules update file…", self._import).pack(anchor="w",
                                                                          pady=(6, 0))
        self.sf.canvas.yview_moveto(0)

    # -- actions -------------------------------------------------------------
    def _commit(self):
        """Store everything typed so far (called before any redraw and on Done)."""
        p = self.app.profile
        for key, var in self.vars.items():
            p[key] = var.get().strip()
        if self.metric is not None:
            p["metric"] = {"auto": None, "on": True, "off": False}[self.metric.get()]
        p["show_phone"] = self.show_phone.value
        p["show_email"] = self.show_email.value
        p["cross_contact"] = self.cross.get("1.0", "end-1c").strip()
        p.save()
        rules = self.app.rules
        for stid, (t, before) in self.stmt_widgets.items():
            now = t.get("1.0", "end-1c").strip()
            if now != before:
                if not now:
                    rules.reset_statement(self.sid, stid)
                else:
                    rules.set_statement(self.sid, stid, now)
        req = [k for k, tg in self.req_toggles.items() if tg.value]
        if req != rules.effective(self.sid).required:
            rules.set_required(self.sid, req)

    def _change_state(self):
        self._commit()
        m = Modal(self, "Which state?")
        _label(m.body, "Which state do you sell in?", font="big").pack(anchor="w",
                                                                         pady=(0, 8))
        lst = StateList(m.body, self.app.rules, self.app.profile["state"])
        lst.pack(fill="x")
        row = tk.Frame(m.body, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        button(row, "Use this state", lambda: m.finish(lst.get()), "primary").pack(side="left")
        button(row, "Cancel", m.cancel, "quiet").pack(side="right")
        sid = m.run()
        if sid:
            self.app.profile["state"] = sid
            self.app.profile.save()
            self._draw()

    def _reset_stmt(self, stid):
        self._commit()
        self.app.rules.reset_statement(self.sid, stid)
        self._draw()

    def _use_alt(self, stid, text):
        self._commit()
        self.app.rules.set_statement(self.sid, stid, text)
        self._draw()

    def _add_own(self):
        self._commit()
        text = ask_text(self, "My own statement", "What should the statement say?")
        if text:
            self.app.rules.add_own_statement(self.sid, text)
        self._draw()

    def _add_optional(self, o):
        self._commit()
        self.app.rules.add_own_statement(self.sid, o["text"], o.get("min_pt"))
        self._draw()

    def _reset_required(self):
        self._commit()
        self.app.rules.reset_required(self.sid)
        self._draw()

    def _import(self):
        self._commit()
        import_rules(self, self.app)
        self._draw()

    def _done(self):
        self._commit()
        self.finish(True)


def import_rules(parent, app):
    """Ask for a state rules update file, validate it, store it, say what changed."""
    path = filedialog.askopenfilename(parent=parent, title="State rules update file",
                                      filetypes=[("State rules", "*.json"), ("All", "*")])
    if not path:
        return
    try:
        lines = app.rules.import_file(path)
    except cottage.RulesError as e:
        tell(parent, "Not added", str(e))
        return
    tell(parent, "Thank you", "The state rules were updated:\n\n" + "\n".join(lines[:20])
         + ("\n…" if len(lines) > 20 else ""))
    ask_about_changes(parent, app)


def ask_about_changes(parent, app) -> None:
    """If a state default moved under one of the user's edits, ask once per change."""
    sid = app.profile["state"]
    if not sid:
        return
    for item in app.rules.pending_changes(sid):
        if item["kind"] == "statement":
            msg = ("Your state's suggested wording was updated — keep yours or use the "
                   "new one?\n\nYours:\n“" + item["yours"] + "”\n\n"
                   + ("New suggestion:\n“" + item["new"] + "”" if item["new"] else
                      "The state no longer suggests this statement."))
        else:
            names = lambda keys: ", ".join(cottage.FIELDS[k] for k in keys)  # noqa: E731
            msg = ("Your state's list of what must be on the label was updated — keep "
                   "yours or use the new one?\n\nYours: " + names(item["yours"])
                   + "\n\nNew suggestion: " + names(item["new"]))
        ans = ask(parent, "An update from your state", msg,
                  [("Keep mine", "keep", "primary"), ("Use the new one", "new", "normal")])
        if ans == "new":
            app.rules.use_new(sid, item)
        else:
            app.rules.keep_mine(sid, item)      # closing the window keeps yours too


# ---------------------------------------------------------------------------
# My ingredients
# ---------------------------------------------------------------------------

class IngredientEditor(Modal):
    """Add or change one ingredient: name, what's in it, allergens."""

    def __init__(self, parent, entry=None):
        super().__init__(parent, "Ingredient")
        e = dict(entry or {"name": "", "sub": "", "allergens": [], "check": False})
        self.entry = e
        _label(self.body, "Name (as it should appear on the label)", font="ui_bold").pack(
            anchor="w")
        self.name, w = _entry(self.body, e["name"])
        w.pack(fill="x", ipady=4)
        _label(self.body, "What's in it, from the package (if it has more than one "
               "ingredient)", font="ui_bold").pack(anchor="w", pady=(10, 0))
        self.sub = _text(self.body, e.get("sub", ""), 3, 50)
        self.sub.pack(fill="x")
        _label(self.body, "Allergens in it", font="ui_bold").pack(anchor="w", pady=(10, 0))
        grid = tk.Frame(self.body, bg=BG)
        grid.pack(fill="x")
        have = {a.lower() for a in e.get("allergens", [])}
        self.toggles = {}
        for i, name in enumerate(model.ALLERGENS):
            tg = Toggle(grid, name, None, name.lower() in have)
            tg.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            self.toggles[name] = tg
        other = [a for a in e.get("allergens", []) if a.lower() not in
                 {x.lower() for x in model.ALLERGENS}]
        _label(self.body, "Other or more exact (for example “Tree nuts (pecans)”), "
               "separated by commas", fg=MUTED).pack(anchor="w", pady=(6, 0))
        self.other, w = _entry(self.body, ", ".join(other))
        w.pack(fill="x", ipady=4)
        self.checked = Toggle(self.body, "I checked this against my package", None,
                              not e.get("check", False))
        self.checked.pack(anchor="w", pady=(10, 0))
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        button(row, "Save", self._save, "primary").pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")

    def _save(self):
        name = self.name.get().strip()
        if not name:
            tell(self, "Name", "Please type the ingredient's name.")
            return
        other = [x.strip() for x in self.other.get().split(",") if x.strip()]
        allergens = [n for n, tg in self.toggles.items() if tg.value]
        # "Tree nuts (pecans)" replaces a plain "Tree nuts"
        for o in other:
            base = o.split("(")[0].strip().lower()
            allergens = [a for a in allergens if a.lower() != base]
        e = dict(self.entry, name=name, sub=self.sub.get("1.0", "end-1c").strip(),
                 allergens=allergens + other, check=not self.checked.value)
        self.finish(e)


class IngredientPicker(Modal):
    """Pick ingredients heaviest first. Result: list of ingredient entries, or None."""

    def __init__(self, parent, app):
        super().__init__(parent, "My ingredients")
        self.app = app
        self.lib = app.ingredients
        self.picked: list[dict] = []
        _label(self.body, "Tap an ingredient, then “Add ▶”. Add the heaviest "
               "first (the label lists them in that order).", wrap=860).pack(anchor="w")
        _label(self.body, "⚠ = an example from the starter list: check your package "
               "and press Change… to match it.", fg=WARN, font="small").pack(anchor="w",
                                                                                   pady=(2, 8))
        cols = tk.Frame(self.body, bg=BG)
        cols.pack(fill="both", expand=True)
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        _label(left, "My ingredients", font="ui_bold").pack(anchor="w")
        self.lib_lb = tk.Listbox(left, font="ui", height=12, width=34, activestyle="none",
                                 selectbackground=GREEN, exportselection=False)
        self.lib_lb.pack(fill="both", expand=True)
        self.lib_lb.bind("<Double-Button-1>", lambda e: self._add())
        r = tk.Frame(left, bg=BG)
        r.pack(fill="x", pady=(6, 0))
        button(r, "New…", self._new, "chip").pack(side="left")
        button(r, "Change…", self._edit, "chip").pack(side="left", padx=4)
        button(r, "Delete", self._delete, "chip").pack(side="left")
        mid = tk.Frame(cols, bg=BG, padx=10)
        mid.pack(side="left", fill="y")
        button(mid, "Add ▶", self._add, "primary").pack(pady=(60, 6), fill="x")
        button(mid, "◀ Take out", self._remove).pack(pady=6, fill="x")
        button(mid, "Up ▲", lambda: self._move(-1), "chip").pack(pady=6, fill="x")
        button(mid, "Down ▼", lambda: self._move(1), "chip").pack(pady=6, fill="x")
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        _label(right, "In this product (heaviest first)", font="ui_bold").pack(anchor="w")
        self.pick_lb = tk.Listbox(right, font="ui", height=12, width=34, activestyle="none",
                                  selectbackground=GREEN, exportselection=False)
        self.pick_lb.pack(fill="both", expand=True)
        self.preview = _label(self.body, "", font="small", fg=MUTED, wrap=860)
        self.preview.pack(anchor="w", pady=(8, 0))
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(12, 0))
        button(row, "Use these on my label", self._use, "primary").pack(side="left")
        button(row, "Cancel", self.cancel, "quiet").pack(side="right")
        self._fill()

    def _fill(self):
        self.lib_lb.delete(0, "end")
        self.view = self.lib.sorted()
        for e in self.view:
            self.lib_lb.insert("end", ("⚠ " if e.get("check") else "") + e["name"])
        self.pick_lb.delete(0, "end")
        for e in self.picked:
            self.pick_lb.insert("end", e["name"])
        line = bakery.build_ingredients(self.picked)
        alg = bakery.allergens_for(self.picked)
        self.preview.configure(text=("INGREDIENTS: " + line if line else "")
                               + ("\nCONTAINS: " + ", ".join(alg) if alg else ""))

    def _sel(self):
        s = self.lib_lb.curselection()
        return self.view[s[0]] if s and s[0] < len(self.view) else None

    def _add(self):
        e = self._sel()
        if e is not None:
            self.picked.append(e)
            self._fill()

    def _remove(self):
        s = self.pick_lb.curselection()
        if s and s[0] < len(self.picked):
            del self.picked[s[0]]
            self._fill()

    def _move(self, d):
        s = self.pick_lb.curselection()
        if not s:
            return
        i, j = s[0], s[0] + d
        if 0 <= j < len(self.picked):
            self.picked[i], self.picked[j] = self.picked[j], self.picked[i]
            self._fill()
            self.pick_lb.selection_set(j)

    def _new(self):
        e = IngredientEditor(self).run()
        if e:
            try:
                self.lib.put(e)
            except bakery.LibraryError as err:
                tell(self, "Not saved", str(err))
            self._fill()

    def _edit(self):
        cur = self._sel()
        if cur is None:
            tell(self, "Pick one", "Tap an ingredient in “My ingredients” first.")
            return
        e = IngredientEditor(self, cur).run()
        if e:
            saved = self.lib.put(e)
            self.picked = [saved if p["id"] == saved["id"] else p for p in self.picked]
            self._fill()

    def _delete(self):
        cur = self._sel()
        if cur is None:
            return
        if ask(self, "Delete?", f"Delete “{cur['name']}” from My ingredients?",
               [("Delete", True, "warn"), ("Keep it", False, "normal")]):
            self.lib.remove(cur["id"])
            self.picked = [p for p in self.picked if p["id"] != cur["id"]]
            self._fill()

    def _use(self):
        if not self.picked:
            tell(self, "Nothing picked", "Add at least one ingredient first.")
            return
        self.finish(list(self.picked))


# ---------------------------------------------------------------------------
# My products
# ---------------------------------------------------------------------------

class ProductPicker(Modal):
    """Choose a saved product to fill the label; also delete, back up, restore."""

    def __init__(self, parent, app):
        super().__init__(parent, "My products")
        self.app = app
        self.lib = app.products
        _label(self.body, "Which product?", font="big").pack(anchor="w", pady=(0, 8))
        self.lb = tk.Listbox(self.body, font="ui", height=12, width=50, activestyle="none",
                             selectbackground=GREEN, exportselection=False)
        self.lb.pack(fill="both", expand=True)
        self.lb.bind("<Double-Button-1>", lambda e: self._use())
        self.empty = _label(self.body, "", fg=MUTED)
        self.empty.pack(anchor="w")
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        button(row, "Use this product", self._use, "primary").pack(side="left")
        button(row, "Delete", self._delete, "chip").pack(side="left", padx=8)
        row2 = tk.Frame(self.body, bg=BG)
        row2.pack(fill="x", pady=(8, 0))
        button(row2, "Back up my products…", self._export, "quiet").pack(side="left")
        button(row2, "Restore from a backup…", self._import, "quiet").pack(side="left",
                                                                                   padx=8)
        button(row2, "Cancel", self.cancel, "quiet").pack(side="right")
        self._fill()

    def _fill(self):
        self.view = self.lib.sorted()
        self.lb.delete(0, "end")
        for p in self.view:
            self.lb.insert("end", p["name"] + (f"   ({p['net']})" if p["net"] else ""))
        self.empty.configure(text="" if self.view else
                             "No products yet. Fill in a label and press "
                             "“Save to My products”.")

    def _sel(self):
        s = self.lb.curselection()
        return self.view[s[0]] if s and s[0] < len(self.view) else None

    def _use(self):
        p = self._sel()
        if p is None:
            tell(self, "Pick one", "Tap a product in the list first.")
            return
        self.finish(p)

    def _delete(self):
        p = self._sel()
        if p and ask(self, "Delete?", f"Delete “{p['name']}” from My products?",
                     [("Delete", True, "warn"), ("Keep it", False, "normal")]):
            self.lib.remove(p["id"])
            self._fill()

    def _export(self):
        path = filedialog.asksaveasfilename(parent=self, title="Back up my products",
                                            initialfile="My products.json",
                                            defaultextension=".json",
                                            filetypes=[("Backup", "*.json")])
        if not path:
            return
        try:
            self.lib.export_file(path)
            tell(self, "Saved", "Your products were saved to:\n" + path)
        except OSError:
            tell(self, "Not saved", "That file couldn't be written. Try another place.")

    def _import(self):
        path = filedialog.askopenfilename(parent=self, title="Restore my products",
                                          filetypes=[("Backup", "*.json"), ("All", "*")])
        if not path:
            return
        try:
            added, updated = self.lib.import_file(path)
        except bakery.LibraryError as e:
            tell(self, "Not restored", str(e))
            return
        msg = []
        if added:
            msg.append("Added: " + ", ".join(added))
        if updated:
            msg.append("Updated: " + ", ".join(updated))
        tell(self, "Restored", "\n\n".join(msg))
        self._fill()


def backup_ingredients(parent, app):
    """Settings: back up or restore My ingredients."""
    ans = ask(parent, "My ingredients", "Back up your ingredients to a file, or restore them "
              "from a backup?", [("Back up…", "out", "primary"),
                                 ("Restore…", "in", "normal"), ("Cancel", None, "quiet")])
    lib = app.ingredients
    if ans == "out":
        path = filedialog.asksaveasfilename(parent=parent, title="Back up my ingredients",
                                            initialfile="My ingredients.json",
                                            defaultextension=".json",
                                            filetypes=[("Backup", "*.json")])
        if path:
            lib.export_file(path)
            tell(parent, "Saved", "Your ingredients were saved to:\n" + path)
    elif ans == "in":
        path = filedialog.askopenfilename(parent=parent, title="Restore my ingredients",
                                          filetypes=[("Backup", "*.json"), ("All", "*")])
        if not path:
            return
        try:
            added, updated = lib.import_file(path)
        except bakery.LibraryError as e:
            tell(parent, "Not restored", str(e))
            return
        tell(parent, "Restored", f"Added {len(added)}, updated {len(updated)} ingredients.")
