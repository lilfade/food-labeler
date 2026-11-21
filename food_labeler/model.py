"""The label document: which template, which size, what the user typed.

A ``.label`` file is UTF-8 JSON::

    {"app": "easy-labels", "version": 1, "template": "simple",
     "stock": "large", "fields": {...}, "copies": 1}

Dates inside ``fields`` are ISO strings. Unknown fields are dropped on load
and missing ones get defaults, so files survive template changes. Files from
a newer format version are refused with a friendly message rather than
half-read.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import dates, stocks

APP_KEY = "easy-labels"   # file format id (the project's original name; never change it,
                          # or existing .label files stop opening)
VERSION = 1
EXT = ".label"

ALLERGENS = ["Milk", "Eggs", "Fish", "Shellfish", "Tree nuts",
             "Peanuts", "Wheat", "Soy", "Sesame"]

NOTE_CHIPS = ["Keep refrigerated", "Keep frozen", "Reheat before eating", "Shelf stable"]

DEFAULT_CROSS_CONTACT = ("Made in a home kitchen that also handles wheat, eggs, milk, "
                         "soy, peanuts, and tree nuts. Cross-contact is possible.")
DEFAULT_DISCLAIMER = ("This food was prepared in a kitchen that is not subject to "
                      "regulation and inspection by the regulatory authority and may "
                      "contain allergens.")

# Which date field is the "made" date and which is the "use by" date, per template.
DATE_PAIRS = {
    "simple": ("made_on", "use_by"),
    "package": (None, "best_by"),
    "sticker": ("made", "best_by"),
    "free": (None, None),
    "cottage": ("made_on", "best_by"),
}

STORAGE_CHIPS = ["Store at room temperature", "Keep refrigerated", "Keep frozen",
                 "Store in a cool, dry place"]


class LabelFileError(Exception):
    """A label file could not be read. Message is friendly."""


def default_lot(d: dt.date | None = None) -> str:
    """Default lot number: the date as YYMMDD."""
    d = d or dates.today()
    return d.strftime("%y%m%d")


def default_fields(template: str, today: dt.date | None = None) -> dict:
    """A fresh set of fields for a template, with dates counted from today."""
    t = today or dates.today()
    iso = t.isoformat()
    if template == "package":
        return {
            "product": "", "net": "", "ingredients": "", "contains": "",
            "cross_contact": DEFAULT_CROSS_CONTACT, "lot": default_lot(t),
            "best_by": (t + dt.timedelta(days=14)).isoformat(),
            "business": "", "address": "", "disclaimer": DEFAULT_DISCLAIMER, "qr": "",
        }
    if template == "sticker":
        return {"lot": default_lot(t), "made": iso,
                "best_by": (t + dt.timedelta(days=7)).isoformat(), "count": ""}
    if template == "free":
        return {"text": ""}
    if template == "cottage":
        # Business details and the state's statements are not stored here: they
        # come from My bakery (bakery.Profile) and the state rules when drawn.
        return {"product": "", "net": "", "ingredients": "", "contains": "",
                "no_allergens": False, "storage": "", "made_on": iso,
                "best_by": (t + dt.timedelta(days=7)).isoformat(),
                "show_made": True, "show_best_by": True}
    return {"food": "", "made_on": iso,
            "use_by": (t + dt.timedelta(days=5)).isoformat(),
            "contains": "", "note": "", "made_by": "", "kitchen": False}


TEMPLATES = ["simple", "package", "sticker", "free", "cottage"]


@dataclass
class LabelDoc:
    """One label as edited in the main window; also what autosave stores."""
    template: str = "simple"
    stock: str = stocks.DEFAULT_STOCK
    fields: dict = field(default_factory=lambda: default_fields("simple"))
    copies: int = 1

    # ---- convenience -------------------------------------------------
    def copy(self) -> "LabelDoc":
        """Deep copy (fields are nested dicts)."""
        return LabelDoc(self.template, self.stock, copy.deepcopy(self.fields), self.copies)

    def title(self) -> str:
        """Short name for window titles and file names: first line of the main field."""
        f = self.fields
        for key in ("food", "product", "text", "lot"):
            v = str(f.get(key, "") or "").strip()
            if v:
                v = v.splitlines()[0].strip()
                return f"Lot {v}" if key == "lot" else v
        return ""

    def set_template(self, template: str) -> None:
        """Switch template, carrying over what we can (name, dates, allergens)."""
        if template == self.template or template not in TEMPLATES:
            return
        old = self.fields
        new = default_fields(template)
        name = str(old.get("food") or old.get("product") or old.get("text") or "")
        if template == "simple":
            new["food"] = name
        elif template in ("package", "cottage"):
            new["product"] = name
        elif template == "free":
            new["text"] = name
        if old.get("contains") and "contains" in new:
            new["contains"] = old["contains"]
        om, ou = DATE_PAIRS[self.template]
        nm, nu = DATE_PAIRS[template]
        if om and nm and old.get(om):
            new[nm] = old[om]
        if ou and nu and old.get(ou):
            new[nu] = old[ou]
        if old.get("lot") and "lot" in new:
            new["lot"] = old["lot"]
        for k in ("net", "ingredients"):
            if old.get(k) and k in new:
                new[k] = old[k]
        self.template = template
        self.fields = new

    def clamp_copies(self) -> None:
        """Force copies into 1..200 (it comes from typing and from files)."""
        try:
            n = int(self.copies)
        except (TypeError, ValueError):
            n = 1
        self.copies = max(1, min(200, n))

    # ---- dates ---------------------------------------------------------
    def made_date(self) -> dt.date | None:
        """The "made on" date of this template, if it has one."""
        key = DATE_PAIRS.get(self.template, (None, None))[0]
        return dates.parse(self.fields.get(key)) if key else None

    def refresh_dates(self, today: dt.date | None = None) -> None:
        """Made-on becomes today; use-by keeps the same number of days after it."""
        today = today or dates.today()
        mk, uk = DATE_PAIRS.get(self.template, (None, None))
        made = dates.parse(self.fields.get(mk)) if mk else None
        use = dates.parse(self.fields.get(uk)) if uk else None
        if mk and made:
            self.fields[mk] = today.isoformat()
            if uk and use:
                self.fields[uk] = (today + (use - made)).isoformat()
        if "lot" in self.fields and made:
            if self.fields["lot"] == default_lot(made):
                self.fields["lot"] = default_lot(today)

    # ---- JSON ----------------------------------------------------------
    def to_dict(self) -> dict:
        """The JSON-ready file contents."""
        self.clamp_copies()
        return {"app": APP_KEY, "version": VERSION, "template": self.template,
                "stock": self.stock, "fields": copy.deepcopy(self.fields),
                "copies": self.copies}

    @classmethod
    def from_dict(cls, data: dict) -> "LabelDoc":
        """Validate and load file contents. Raises LabelFileError with a friendly message."""
        if not isinstance(data, dict) or data.get("app") != APP_KEY:
            raise LabelFileError("This file isn't a Food Labeler label.")
        try:
            ver = int(data.get("version", 0))
        except (TypeError, ValueError):
            ver = 0
        if ver < 1 or ver > VERSION:
            raise LabelFileError("This label was made with a newer version of Food Labeler. "
                                 "Please update the program to open it.")
        template = data.get("template")
        if template not in TEMPLATES:
            template = "simple"
        fields = default_fields(template)
        got = data.get("fields") or {}
        if isinstance(got, dict):
            for k, v in got.items():
                if k in fields:
                    fields[k] = v
        stock = data.get("stock") if data.get("stock") in stocks.STOCKS else stocks.DEFAULT_STOCK
        doc = cls(template, stock, fields, data.get("copies", 1))
        doc.clamp_copies()
        return doc

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def loads(cls, text: str) -> "LabelDoc":
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            raise LabelFileError("This label file is damaged and can't be opened.") from None
        return cls.from_dict(data)


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same folder + fsync + rename.

    Used for labels, settings, autosave and printer updates, so a crash or
    power cut leaves either the old file or the new one — never half a file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=path.suffix, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(doc: LabelDoc, path) -> Path:
    """Save a label, adding the .label extension if missing. Returns the real path."""
    path = Path(path)
    if path.suffix.lower() != EXT:
        path = path.with_name(path.name + EXT)
    atomic_write_text(path, doc.dumps())
    return path


def load(path) -> LabelDoc:
    """Open a .label file. Raises LabelFileError (friendly message) on any problem."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LabelFileError("That label file isn't there any more. "
                             "It may have been moved or deleted.") from None
    except OSError:
        raise LabelFileError("That label file couldn't be opened.") from None
    return LabelDoc.loads(text)


def safe_filename(name: str) -> str:
    """Turn a label title into a file name that works on Windows, macOS and Linux."""
    bad = '<>:"/\\|?*\n\r\t'
    out = "".join("-" if c in bad else c for c in name).strip(" .")
    out = out[:60].strip(" .") or "My label"
    # Windows refuses these device names even with an extension ("con.label").
    if out.split(".")[0].upper() in _WINDOWS_RESERVED:
        out += " label"
    return out


_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                     *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
