"""Cottage food (home bakery) label rules: per-state presets, the user's own
edits layered on top, the "Label check" and net-quantity wording.

Three layers, lowest first:

1. ``cottage_rules.json`` bundled in the package (replaced by every app update);
2. an imported rules update in the data folder (``<data dir>/cottage_rules.json``),
   used for a state only when it was checked on the same day or later than the
   bundled entry, so an old update file can never hide newer bundled rules;
3. the user's own edits in ``<data dir>/cottage_overrides.json``. App updates
   never touch this file. Each edit remembers the default it was based on
   (``based_on``), so when the default changes underneath an edit we can ask
   once ("keep yours or use the new one?") instead of overwriting.

See docs/cottage-rules.md for both file formats. Nothing here imports Tk.
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("food_labeler.cottage")

BUILTIN = Path(__file__).resolve().parent / "cottage_rules.json"
FORMAT = "food-labeler-cottage-rules"
VERSION = 1
OVERRIDES_FORMAT = "food-labeler-cottage-overrides"
OVERRIDES_VERSION = 1
USER_RULES_NAME = "cottage_rules.json"
OVERRIDES_NAME = "cottage_overrides.json"
CUSTOM_ID = "custom"
CUSTOM_NAME = "Custom / my own rules"
MAX_STATES = 80
MAX_TEXT = 1000

RESPONSIBILITY = ("These are suggestions from public state guidance. You are responsible "
                  "for following your state's rules.")

# Everything a state may require on a cottage label, in label order, with the
# plain-English name the Label check shows.
FIELDS = {
    "product_name": "Product name",
    "net_quantity": "Net weight or amount",
    "ingredients": "Ingredients (heaviest first)",
    "allergens": "Allergens (“Contains:”)",
    "business_name": "Your business name",
    "address": "Your full address (street, city, state and ZIP)",
    "city_state_zip": "Your city, state and ZIP",
    "phone": "Your phone number",
    "email": "Your email address",
    "permit_number": "Your permit or registration number",
    "date_made": "Date it was made",
    "sell_by": "Best-by or sell-by date",
    "storage": "How to store it",
}
# Always asked for on a cottage label, whatever the state preset says: the
# basics of any food label, and (as High Thyme Kitchen's own labels do) the
# producer's complete address.
BASELINE = ["product_name", "ingredients", "allergens", "business_name", "address"]

STATE_KEYS = {"id", "name", "sales_allowed", "verified", "statements", "required", "optional",
              "min_statement_pt", "metric_required", "notes", "source_url", "extra_sources",
              "checked_on"}
STATEMENT_KEYS = {"id", "text", "min_pt", "kind"}
# "label": prints on the label; "alternative": other wording the state allows
# (the user can switch to it); "optional": needed only in some cases (for example
# foods kept cold), the user can add it; "sign": for a sign where you sell, not the label.
STATEMENT_KINDS = ("label", "alternative", "optional", "sign")
# Blanks a statement may contain, filled from My bakery when the label is drawn.
PLACEHOLDERS = {"business_name": "business", "permit_number": "permit", "county": "county"}
ID_RE = re.compile(r"^(?:[A-Z]{2}|custom)$")
STMT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RulesError(Exception):
    """A rules or overrides file isn't valid. Message is friendly."""


# ---------------------------------------------------------------------------
# the rules file
# ---------------------------------------------------------------------------

@dataclass
class StateRule:
    """One state's preset, as it comes from a rules file (before user edits)."""
    id: str
    name: str
    sales_allowed: bool | None = True     # None: not known
    verified: bool = False
    statements: list = field(default_factory=list)   # [{"id", "text", "min_pt"}]
    required: list = field(default_factory=list)
    optional: list = field(default_factory=list)
    min_statement_pt: float | None = None
    metric_required: bool = False
    notes: str = ""
    source_url: str = ""
    extra_sources: list = field(default_factory=list)
    checked_on: str = ""

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "sales_allowed": self.sales_allowed,
                "verified": self.verified,
                "statements": [dict(s) for s in self.statements],
                "required": list(self.required), "optional": list(self.optional),
                "min_statement_pt": self.min_statement_pt,
                "metric_required": self.metric_required, "notes": self.notes,
                "source_url": self.source_url, "extra_sources": list(self.extra_sources),
                "checked_on": self.checked_on}


def _pt(v, what):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 4 <= v <= 36:
        raise RulesError(f"{what} has a font size that isn't a sensible number of points.")
    return v


def _fields(v, what):
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise RulesError(f"{what} has a bad list of label items.")
    bad = [x for x in v if x not in FIELDS]
    if bad:
        raise RulesError(f"{what} mentions label items this version doesn't know: "
                         + ", ".join(bad))
    return [x for x in FIELDS if x in v]          # canonical order, no duplicates


def validate_state(e) -> StateRule:
    """Check one "states" entry. Raises RulesError (whole file is then refused)."""
    if not isinstance(e, dict):
        raise RulesError("The rules file has something in it that isn't a state.")
    extra = set(e) - STATE_KEYS
    if extra:
        raise RulesError("The rules file has things in it this version doesn't understand: "
                         + ", ".join(sorted(extra)))
    sid, name = e.get("id"), e.get("name")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise RulesError("A state in the rules file has a missing or bad “id”.")
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise RulesError(f"State “{sid}” has a missing or bad name.")
    what = f"The entry for {name}"
    sales = e.get("sales_allowed", True)
    if sales not in (True, False, None):
        raise RulesError(f"{what} has a bad “sales_allowed”.")
    for key in ("verified", "metric_required"):
        if not isinstance(e.get(key, False), bool):
            raise RulesError(f"{what} has a bad “{key}”.")
    stmts = e.get("statements", [])
    if not isinstance(stmts, list) or len(stmts) > 8:
        raise RulesError(f"{what} has a bad list of statements.")
    clean, seen = [], set()
    for s in stmts:
        if not isinstance(s, dict) or set(s) - STATEMENT_KEYS:
            raise RulesError(f"{what} has a statement this version doesn't understand.")
        stid, text = s.get("id"), s.get("text")
        if not isinstance(stid, str) or not STMT_ID_RE.match(stid) or stid in seen:
            raise RulesError(f"{what} has a statement with a missing or repeated id.")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise RulesError(f"{what} has an empty or very long statement.")
        kind = s.get("kind", "label")
        if kind not in STATEMENT_KINDS:
            raise RulesError(f"{what} has a statement of an unknown kind.")
        for ph in re.findall(r"\{([^{}]*)\}", text):
            if ph not in PLACEHOLDERS:
                raise RulesError(f"{what} has a blank this version can't fill: {{{ph}}}")
        seen.add(stid)
        clean.append({"id": stid, "text": text.strip(),
                      "min_pt": _pt(s.get("min_pt"), what), "kind": kind})
    for key in ("notes", "source_url", "checked_on"):
        v = e.get(key, "")
        if not isinstance(v, str) or len(v) > 4000:
            raise RulesError(f"{what} has a bad “{key}”.")
    url = e.get("source_url", "")
    if url and not url.startswith("https://") and not url.startswith("http://"):
        raise RulesError(f"{what} has a source link that isn't a web address.")
    extra_src = e.get("extra_sources", [])
    if not isinstance(extra_src, list) or len(extra_src) > 10 or not all(
            isinstance(x, str) and x.startswith(("https://", "http://")) and len(x) < 600
            for x in extra_src):
        raise RulesError(f"{what} has a bad list of extra sources.")
    checked = e.get("checked_on", "")
    if checked and not DATE_RE.match(checked):
        raise RulesError(f"{what} has a “checked_on” date that isn't YYYY-MM-DD.")
    return StateRule(
        id=sid, name=name.strip(), sales_allowed=sales, verified=e.get("verified", False),
        statements=clean, required=_fields(e.get("required", []), what),
        optional=_fields(e.get("optional", []), what),
        min_statement_pt=_pt(e.get("min_statement_pt"), what),
        metric_required=e.get("metric_required", False), notes=e.get("notes", ""),
        source_url=url, extra_sources=list(extra_src), checked_on=checked)


def _read_update(path) -> str:
    """A state rules file's text (refused if bigger than any real one)."""
    from .model import MAX_UPDATE_BYTES, read_text_limited
    return read_text_limited(path, MAX_UPDATE_BYTES)


def parse_rules_text(text: str) -> tuple[dict, list[StateRule]]:
    """Parse and validate a whole rules file. Returns (header, states)."""
    text = text.lstrip("﻿")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):   # RecursionError: absurdly deep "[[[[…"
        raise RulesError("This isn't a Food Labeler state rules file.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise RulesError("This isn't a Food Labeler state rules file.")
    if data.get("version") != VERSION:
        raise RulesError("This state rules file is for a different version of Food Labeler.")
    entries = data.get("states")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_STATES:
        raise RulesError("This state rules file has no states in it.")
    rules = [validate_state(e) for e in entries]
    ids = [r.id for r in rules]
    if len(set(ids)) != len(ids):
        raise RulesError("This state rules file lists the same state twice.")
    updated = data.get("updated", "")
    if not isinstance(updated, str):
        raise RulesError("This state rules file has a bad date.")
    return {"updated": updated}, rules


def describe_changes(old: StateRule | None, new: StateRule) -> str:
    """One plain line saying what an update changes for a state ("" if nothing)."""
    if old is None:
        return f"{new.name}: added"
    bits = []
    if [s["text"] for s in old.statements] != [s["text"] for s in new.statements]:
        bits.append("wording")
    if old.required != new.required or old.optional != new.optional:
        bits.append("required items")
    if old.min_statement_pt != new.min_statement_pt or \
            [s.get("min_pt") for s in old.statements] != [s.get("min_pt") for s in new.statements]:
        bits.append("text size")
    if old.metric_required != new.metric_required:
        bits.append("metric weight")
    if old.sales_allowed != new.sales_allowed or old.verified != new.verified:
        bits.append("status")
    if old.notes != new.notes or old.source_url != new.source_url:
        bits.append("notes")
    if not bits:
        return ""
    return f"{new.name}: " + ", ".join(bits) + " updated"


def custom_rule() -> StateRule:
    """The "Custom / my own rules" preset: the basics, and wording the user types."""
    return StateRule(id=CUSTOM_ID, name=CUSTOM_NAME, sales_allowed=None, verified=False,
                     statements=[], required=["product_name", "net_quantity", "ingredients",
                                              "allergens", "business_name", "address"],
                     optional=["phone", "email", "permit_number", "date_made", "sell_by",
                               "storage"],
                     notes="Type the wording your state or county asks for under "
                           "“My own statements”, and tick what has to be on the label.")


# ---------------------------------------------------------------------------
# effective rules (layers + user edits)
# ---------------------------------------------------------------------------

@dataclass
class Statement:
    """One statement as it will print, with its edit markers."""
    id: str
    text: str
    min_pt: float | None
    default: str = ""             # the state's current suggested wording ("" for your own)
    edited: bool = False          # the user changed it ("edited by you")
    own: bool = False             # added by the user, not part of the preset
    default_changed: bool = False  # the preset changed since the user edited it


@dataclass
class Effective:
    """A state's rules with the user's edits applied: what the label uses."""
    rule: StateRule               # the layered default (bundled or update)
    statements: list              # [Statement]
    required: list
    optional: list
    required_edited: bool = False
    required_default_changed: bool = False

    @property
    def id(self):
        return self.rule.id

    @property
    def name(self):
        return self.rule.name

    def min_pt(self, st: Statement) -> float | None:
        """The smallest size this statement may print at (points), if the state sets one."""
        return st.min_pt if st.min_pt is not None else self.rule.min_statement_pt

    def to_ctx(self) -> dict:
        """Plain dict for templates (no dataclasses cross into rendering)."""
        return {"id": self.id, "name": self.name, "required": list(self.required),
                "metric_required": self.rule.metric_required,
                "sales_allowed": self.rule.sales_allowed,
                "statements": [{"id": s.id, "text": s.text, "min_pt": self.min_pt(s)}
                               for s in self.statements if s.text.strip()]}


def fill_placeholders(text: str, profile: dict) -> tuple[str, list[str]]:
    """Fill {business_name}, {permit_number}, {county} from My bakery.
    Returns (text, names of blanks still empty); empty blanks stay as "____"."""
    empty = []

    def sub(m):
        key = PLACEHOLDERS.get(m.group(1))
        val = str((profile or {}).get(key, "") or "").strip() if key else ""
        if not val:
            empty.append(m.group(1))
            return "____"
        return val
    return re.sub(r"\{([a-z_]+)\}", sub, str(text)), empty


class Overrides:
    """The user's own edits, kept in <data dir>/cottage_overrides.json.

    Layout per state id::

        {"statements": {"main": {"text": "...", "based_on": "<default when edited>"}},
         "own": [{"id": "own1", "text": "...", "min_pt": null}],
         "required": {"value": [...], "based_on": [...]}}

    A broken file is never overwritten: it is renamed to ``.broken`` first
    and the app carries on without the edits (and logs it).
    """

    def __init__(self, path: Path | None):
        self.path = path
        self.data: dict = {}
        self.extra: dict = {}
        self.load()

    def load(self):
        self.data, self.extra = {}, {}
        if not self.path or not self.path.is_file():
            return
        try:
            from .model import MAX_BACKUP_BYTES, read_text_limited
            got = json.loads(read_text_limited(self.path, MAX_BACKUP_BYTES).lstrip("﻿"))
            if not isinstance(got, dict) or got.get("format") != OVERRIDES_FORMAT:
                raise ValueError("not an overrides file")
            if int(got.get("version", 0)) > OVERRIDES_VERSION:
                # Written by a newer version: use what we understand, never write it back.
                self.read_only = True
            states = got.get("states") or {}
            if isinstance(states, dict):
                self.data = {k: v for k, v in states.items() if isinstance(v, dict)}
            self.extra = {k: v for k, v in got.items() if k not in ("format", "version", "states")}
        except (OSError, ValueError, TypeError, RecursionError):
            log.exception("cottage overrides unreadable; keeping a copy and carrying on")
            try:
                self.path.replace(self.path.with_suffix(".json.broken"))
            except OSError:
                pass
            self.data = {}

    read_only = False

    def save(self):
        if not self.path or self.read_only:
            return
        from .model import atomic_write_text
        payload = dict(self.extra)
        payload.update({"format": OVERRIDES_FORMAT, "version": OVERRIDES_VERSION,
                        "states": self.data})
        atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def state(self, sid: str) -> dict:
        return self.data.get(sid, {})

    def _st(self, sid: str) -> dict:
        return self.data.setdefault(sid, {})

    def _tidy(self, sid):
        s = self.data.get(sid)
        if s is not None and not any(s.get(k) for k in ("statements", "own", "required")):
            self.data.pop(sid, None)


class CottageRules:
    """The bundled rules + an optional imported update + the user's own edits."""

    def __init__(self, user_dir: Path | None = None, builtin: Path = BUILTIN):
        self.builtin_path = Path(builtin)
        self.user_dir = Path(user_dir) if user_dir else None
        self.update_path = self.user_dir / USER_RULES_NAME if self.user_dir else None
        self.overrides = Overrides(self.user_dir / OVERRIDES_NAME if self.user_dir else None)
        self.reload()

    # -- loading -------------------------------------------------------------
    def reload(self):
        self.bundled: dict[str, StateRule] = {}
        self.updates: dict[str, StateRule] = {}
        self.bundled_date = ""
        try:
            head, rules = parse_rules_text(_read_update(self.builtin_path))
            self.bundled_date = head["updated"]
            self.bundled = {r.id: r for r in rules}
        except (OSError, RulesError):
            log.exception("built-in cottage rules unreadable")
        if self.update_path and self.update_path.is_file():
            try:
                _, rules = parse_rules_text(_read_update(self.update_path))
                self.updates = {r.id: r for r in rules}
            except (OSError, UnicodeDecodeError, RulesError):
                log.exception("cottage rules update unreadable; ignoring it")
        self.overrides.load()

    def base(self, sid: str) -> StateRule:
        """The layered default for a state (before user edits)."""
        b, u = self.bundled.get(sid), self.updates.get(sid)
        if u is not None and (b is None or u.checked_on >= b.checked_on):
            return u
        if b is not None:
            return b
        if sid == CUSTOM_ID:
            return custom_rule()
        return StateRule(id=sid, name=sid, sales_allowed=None, verified=False,
                         required=list(BASELINE),
                         notes="Unverified — check with your state.")

    def states(self) -> list[StateRule]:
        """Every preset: states alphabetically by name, then Custom."""
        ids = (set(self.bundled) | set(self.updates)) - {CUSTOM_ID}
        out = sorted((self.base(i) for i in ids), key=lambda r: r.name)
        return out + [self.base(CUSTOM_ID)]

    # -- effective -----------------------------------------------------------
    @staticmethod
    def label_statements(rule: StateRule) -> list:
        return [s for s in rule.statements if s.get("kind", "label") == "label"]

    @staticmethod
    def other_statements(rule: StateRule, kind: str) -> list:
        """Alternative wordings ("alternative") or sign wording ("sign")."""
        return [s for s in rule.statements if s.get("kind", "label") == kind]

    def effective(self, sid: str) -> Effective:
        """A state's rules with the user's edits applied (see Overrides)."""
        rule = self.base(sid)
        ov = self.overrides.state(sid)
        sov = ov.get("statements") or {}
        stmts = []
        for s in self.label_statements(rule):
            o = sov.get(s["id"])
            if isinstance(o, dict) and isinstance(o.get("text"), str) and o["text"].strip():
                stmts.append(Statement(s["id"], o["text"], s.get("min_pt"), default=s["text"],
                                       edited=o["text"] != s["text"],
                                       default_changed=o.get("based_on") != s["text"]))
            else:
                stmts.append(Statement(s["id"], s["text"], s.get("min_pt"), default=s["text"]))
        ids = {s["id"] for s in self.label_statements(rule)}
        # an edited statement the state no longer suggests stays (it is yours now)
        for stid, o in sov.items():
            if stid not in ids and isinstance(o, dict) and str(o.get("text", "")).strip():
                stmts.append(Statement(stid, o["text"], None, default="", edited=True,
                                       default_changed=True))
        for o in ov.get("own") or []:
            if isinstance(o, dict) and str(o.get("text", "")).strip():
                mp = o.get("min_pt")
                stmts.append(Statement(str(o.get("id", "own")), o["text"],
                                       mp if isinstance(mp, (int, float)) else None,
                                       edited=True, own=True))
        required = list(rule.required)
        for b in BASELINE:
            if b not in required:
                required.append(b)
        required = [f for f in FIELDS if f in required]
        req_edited = req_changed = False
        rov = ov.get("required")
        if isinstance(rov, dict) and isinstance(rov.get("value"), list):
            mine = [f for f in FIELDS if f in rov["value"]]
            req_edited = mine != required
            req_changed = sorted(rov.get("based_on") or []) != sorted(required)
            required = mine
        optional = [f for f in FIELDS if f in rule.optional and f not in required]
        return Effective(rule, stmts, required, optional, req_edited, req_changed)

    # -- user edits ----------------------------------------------------------
    def set_statement(self, sid: str, stid: str, text: str):
        """Change the wording of a preset statement (or one of your own)."""
        text = str(text).strip()[:MAX_TEXT]
        ov = self.overrides._st(sid)
        for o in ov.get("own") or []:
            if o.get("id") == stid:
                o["text"] = text
                self.overrides.save()
                return
        default = next((s["text"] for s in self.label_statements(self.base(sid))
                        if s["id"] == stid), None)
        stm = ov.setdefault("statements", {})
        if default is not None and (text == default or not text):
            stm.pop(stid, None)               # back to the state's wording
        else:
            stm[stid] = {"text": text, "based_on": default}
        self.overrides._tidy(sid)
        self.overrides.save()

    def reset_statement(self, sid: str, stid: str):
        """"Reset to state default" for one statement (removes your own statement)."""
        ov = self.overrides._st(sid)
        (ov.get("statements") or {}).pop(stid, None)
        if ov.get("own"):
            ov["own"] = [o for o in ov["own"] if o.get("id") != stid]
        self.overrides._tidy(sid)
        self.overrides.save()

    def add_own_statement(self, sid: str, text: str, min_pt: float | None = None) -> str:
        """Add a statement of your own (for Custom, or wording your county asks for)."""
        ov = self.overrides._st(sid)
        own = ov.setdefault("own", [])
        used = {o.get("id") for o in own}
        n = 1
        while f"own{n}" in used:
            n += 1
        own.append({"id": f"own{n}", "text": str(text).strip()[:MAX_TEXT], "min_pt": min_pt})
        self.overrides.save()
        return f"own{n}"

    def set_required(self, sid: str, fields: list):
        """Change which items must be on the label."""
        default = self.effective_default_required(sid)
        mine = [f for f in FIELDS if f in fields]
        ov = self.overrides._st(sid)
        if mine == default:
            ov.pop("required", None)
        else:
            ov["required"] = {"value": mine, "based_on": default}
        self.overrides._tidy(sid)
        self.overrides.save()

    def reset_required(self, sid: str):
        self.overrides._st(sid).pop("required", None)
        self.overrides._tidy(sid)
        self.overrides.save()

    def effective_default_required(self, sid: str) -> list:
        rule = self.base(sid)
        return [f for f in FIELDS if f in rule.required or f in BASELINE]

    # -- defaults that moved under an edit -------------------------------------
    def pending_changes(self, sid: str) -> list[dict]:
        """Edits whose state default changed since the user made them.

        Each item: {"kind": "statement"|"required", "id", "yours", "new"}.
        Shown once; keep_mine()/use_new() settle it so it is not asked again.
        """
        eff = self.effective(sid)
        out = []
        for s in eff.statements:
            if s.default_changed and not s.own:
                out.append({"kind": "statement", "id": s.id, "yours": s.text, "new": s.default})
        if eff.required_default_changed:
            out.append({"kind": "required", "id": "required", "yours": list(eff.required),
                        "new": self.effective_default_required(sid)})
        return out

    def keep_mine(self, sid: str, item: dict):
        """Keep the user's version and stop asking about this change."""
        ov = self.overrides._st(sid)
        if item["kind"] == "statement":
            o = (ov.get("statements") or {}).get(item["id"])
            if o is not None:
                o["based_on"] = item["new"] or None
        else:
            o = ov.get("required")
            if o is not None:
                o["based_on"] = list(item["new"])
        self.overrides.save()

    def use_new(self, sid: str, item: dict):
        """Drop the user's version in favour of the state's new suggestion."""
        if item["kind"] == "statement":
            self.reset_statement(sid, item["id"])
        else:
            self.reset_required(sid)

    # -- importing an update ---------------------------------------------------
    def import_file(self, path) -> list[str]:
        """Validate and store a rules update. Returns plain lines saying what changed.

        Nothing is written if the file is invalid. Entries replace the same
        state in the existing update file; the user's own edits are untouched
        (if a default moved under one of them, the app asks about it).
        """
        from .model import FileTooBigError
        try:
            text = _read_update(path)
        except FileTooBigError:
            raise RulesError("This file is far too big to be a Food Labeler state rules "
                             "file.") from None
        except (OSError, UnicodeDecodeError):
            raise RulesError("That file couldn't be read.") from None
        head, new = parse_rules_text(text)
        if not self.update_path:
            raise RulesError("There is nowhere to keep the update.")
        before = {r.id: self.base(r.id) for r in new}
        known_before = set(self.bundled) | set(self.updates)
        merged = dict(self.updates)
        for r in new:
            merged[r.id] = r
        from .model import atomic_write_text
        atomic_write_text(self.update_path, json.dumps(
            {"format": FORMAT, "version": VERSION, "updated": head["updated"],
             "states": [r.to_json() for r in merged.values()]}, indent=2, ensure_ascii=False))
        self.reload()
        lines = []
        for r in new:
            now = self.base(r.id)
            if now is not r and now.checked_on > r.checked_on:
                lines.append(f"{r.name}: the rules already in Food Labeler are newer; kept those")
                continue
            line = describe_changes(before[r.id] if r.id in known_before else None, now)
            if line:
                lines.append(line)
        return lines or ["Nothing new: the rules were already up to date."]


# ---------------------------------------------------------------------------
# net quantity
# ---------------------------------------------------------------------------

G_PER_OZ = 28.349523125
ML_PER_FLOZ = 29.5735295625
_NUM = r"(\d+(?:[.,]\d+)?|\d+\s+\d/\d|\d/\d)"
_UNIT_WORDS = {
    "oz": "oz", "ounce": "oz", "ounces": "oz", "lb": "lb", "lbs": "lb", "pound": "lb",
    "pounds": "lb", "g": "g", "gram": "g", "grams": "g", "kg": "kg", "kilogram": "kg",
    "kilograms": "kg", "floz": "floz", "fl.oz": "floz", "fl oz": "floz", "fluid ounces": "floz",
    "ml": "ml",
}


def _num(s: str) -> float:
    s = s.strip().replace(",", ".")
    if " " in s:
        whole, frac = s.split(None, 1)
        return float(whole) + _num(frac)
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


def parse_net(text: str):
    """Understand a typed net quantity. Returns ("weight", grams), ("volume", ml) or None.

    Accepts "8 oz", "1 lb 4 oz", "1.5 lb", "1 1/2 lb", "227 g", "1.2 kg",
    "16 fl oz", "500 ml" (any case, with or without "Net Wt."). A count
    like "12 cookies" or anything else is None and prints as typed.
    """
    t = str(text or "").strip().lower()
    t = re.sub(r"^(net\s*(wt\.?|weight|vol\.?|contents)?\s*:?\s*)", "", t)
    t = t.replace("fl. oz", "floz").replace("fl oz", "floz").replace("fluid ounces", "floz")
    t = t.replace("fluid ounce", "floz").replace("fl.oz", "floz")
    parts = re.findall(_NUM + r"\s*([a-z.]+)", t)
    rest = re.sub(_NUM + r"\s*([a-z.]+)", "", t).strip(" ,.()")
    if not parts or rest:
        return None
    grams = ml = 0.0
    for num, unit in parts:
        u = _UNIT_WORDS.get(unit.rstrip("."))
        if u is None:
            return None
        v = _num(num)
        if u == "oz":
            grams += v * G_PER_OZ
        elif u == "lb":
            grams += v * 16 * G_PER_OZ
        elif u == "g":
            grams += v
        elif u == "kg":
            grams += v * 1000
        elif u == "floz":
            ml += v * ML_PER_FLOZ
        elif u == "ml":
            ml += v
    if grams and ml:
        return None
    if grams > 0:
        return ("weight", grams)
    if ml > 0:
        return ("volume", ml)
    return None


def _trim(v: float, places: int = 2) -> str:
    s = f"{v:.{places}f}".rstrip("0").rstrip(".")
    return s or "0"


def metric_text(grams: float) -> str:
    """227 g, 1.13 kg: whole grams under 1 kg, else kg to three significant figures
    (8 oz = 226.8 g prints as 227 g, as US packages show it)."""
    if grams < 999.5:
        return f"{max(1, int(grams + 0.5))} g"
    kg = grams / 1000
    places = 2 if kg < 10 else 1 if kg < 100 else 0
    return f"{_trim(round(kg, places), places)} kg"


def format_net(text: str, metric: bool) -> str:
    """The net quantity line as it prints.

    Weights read "Net Wt. 8 oz" (with "(227 g)" when ``metric``); from 1 lb up
    to 4 lb the ounces come first with pounds in brackets, as US packages
    show them ("Net Wt. 24 oz (1 lb 8 oz) 680 g"); 4 lb and over in pounds.
    Anything the program doesn't understand (a count, "1 dozen") prints as typed.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    got = parse_net(raw)
    if got is None:
        return raw if re.match(r"(?i)^net\b", raw) else f"Net {raw}" if re.match(r"^\d", raw) \
            else raw
    kind, v = got
    if kind == "volume":
        floz = v / ML_PER_FLOZ
        us = f"{_trim(floz, 1)} fl oz"
        return f"Net {us}" + (f" ({max(1, int(v + 0.5))} mL)" if metric else "")
    oz = v / G_PER_OZ
    m = metric_text(v)
    if oz < 16 - 1e-6:
        return f"Net Wt. {_trim(oz, 1)} oz" + (f" ({m})" if metric else "")
    if oz < 64 - 1e-6:
        lb = int(oz // 16)
        rem = oz - lb * 16
        brk = f"{lb} lb" + (f" {_trim(rem, 1)} oz" if rem > 0.05 else "")
        return f"Net Wt. {_trim(oz, 1)} oz ({brk})" + (f" {m}" if metric else "")
    return f"Net Wt. {_trim(oz / 16, 2)} lb" + (f" ({m})" if metric else "")


# ---------------------------------------------------------------------------
# allergens
# ---------------------------------------------------------------------------

def strip_prefix(text: str, word: str) -> str:
    """Remove a leading "Contains:" / "Ingredients:" the user typed (the label adds its own)."""
    return re.sub(rf"(?i)^\s*{word}\s*:?\s*", "", str(text or "")).strip()


def merge_allergens(lists, order) -> list[str]:
    """Union of allergen lists, the major allergens first in ``order``, no duplicates."""
    seen, out = set(), []
    flat = [a.strip() for lst in lists for a in (lst or []) if str(a).strip()]
    for name in order:
        if name.lower() in {a.lower() for a in flat} and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    for a in flat:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# the Label check
# ---------------------------------------------------------------------------

@dataclass
class CheckItem:
    key: str
    label: str
    ok: bool
    hint: str = ""


def pt_to_dots(pt: float, dpi: int = 203) -> int:
    """Font size in printer dots for a size in points (1 pt = 1/72 inch)."""
    return int(math.ceil(pt * dpi / 72.0 - 1e-9))


def check_label(fields: dict, profile: dict, eff: dict) -> list[CheckItem]:
    """Which of the state's required items are on this cottage label.

    ``fields`` are the label's fields, ``profile`` the bakery details
    (bakery.Profile.data) and ``eff`` an Effective.to_ctx() dict.
    """
    p = profile or {}
    f = fields or {}

    def has(v):
        return bool(str(v or "").strip())

    full_addr = all(has(p.get(k)) for k in ("street", "city", "region", "zip"))
    present = {
        "product_name": has(f.get("product")),
        "net_quantity": has(f.get("net")),
        "ingredients": has(strip_prefix(f.get("ingredients"), "ingredients")),
        "allergens": has(strip_prefix(f.get("contains"), "contains")) or bool(f.get("no_allergens")),
        "business_name": has(p.get("business")),
        "address": full_addr,
        "city_state_zip": all(has(p.get(k)) for k in ("city", "region", "zip")),
        "phone": has(p.get("phone")),
        "email": has(p.get("email")),
        "permit_number": has(p.get("permit")),
        "date_made": has(f.get("made_on")),
        "sell_by": has(f.get("best_by")),
        "storage": has(f.get("storage")),
    }
    hints = {
        "allergens": "Tap the allergens that are in it, or “None of these”.",
        "address": "Add your street, city, state and ZIP in My bakery.",
        "city_state_zip": "Add your city, state and ZIP in My bakery.",
        "business_name": "Add it in My bakery.", "phone": "Add it in My bakery.",
        "email": "Add it in My bakery.", "permit_number": "Add it in My bakery.",
    }
    out = []
    for key in (eff or {}).get("required", []):
        out.append(CheckItem(key, FIELDS.get(key, key), present.get(key, False),
                             "" if present.get(key) else hints.get(key, "")))
    blank_names = {"business_name": "business name", "permit_number": "permit number",
                   "county": "county"}
    for s in (eff or {}).get("statements", []):
        text, empty = fill_placeholders(s["text"], p)
        short = text if len(text) <= 48 else text[:45].rstrip() + "…"
        size = f" (at least {_trim(s['min_pt'], 1)} pt)" if s.get("min_pt") else ""
        hint = ("Add your " + " and ".join(blank_names.get(e, e) for e in empty)
                + " in My bakery.") if empty else ""
        out.append(CheckItem("statement:" + s["id"], f"Statement{size}: “{short}”",
                             not empty, hint))
    return out


def missing(items: list[CheckItem]) -> list[CheckItem]:
    return [i for i in items if not i.ok]
