"""The label document: which template, which size, what the user typed.

A ``.label`` file is UTF-8 JSON::

    {"app": "easy-labels", "version": 1, "template": "simple",
     "stock": "large", "fields": {...}, "copies": 1}

plus, only when it isn't the standard look, the optional
``"lettering": {"name": "Pacifico", "other": "Lato"}`` (font family names, see
lettering.py). Older versions ignore it, and files without it open in the
standard lettering, so the format version is still 1.

Likewise optional (1.2.0): ``"picture"`` (the label's picture, embedded as a
base64 PNG with its placement and black-and-white settings, see pictures.py)
and ``"qr"`` (what a QR code holds and where it goes, see qrcodes.py). They
are only written when the label has them, so other labels save exactly as
before. Package labels from earlier versions kept a web address in
``fields["qr"]``; on open it becomes a ``"qr"`` object (the file itself is
only changed when saved), and saving still writes the code's text into
``fields["qr"]`` so earlier versions show the code too.

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
    "picture": (None, None),
}

STORAGE_CHIPS = ["Store at room temperature", "Keep refrigerated", "Keep frozen",
                 "Store in a cool, dry place"]


class LabelFileError(Exception):
    """A label file could not be read. Message is friendly."""


# Largest file of each kind that is read at all. Real files are far smaller;
# the limits only stop a wrong or harmful file from filling the memory.
MB = 1024 * 1024
MAX_LABEL_BYTES = 64 * MB       # .label files (and the autosave, which holds one)
MAX_UPDATE_BYTES = 2 * MB       # printer and state rules update files
MAX_BACKUP_BYTES = 16 * MB      # My products / My ingredients backups, the baker's own files
MAX_SETTINGS_BYTES = 16 * MB    # settings.json and other small files in the data folder


class FileTooBigError(OSError):
    """A file is bigger than any real file of its kind (see read_text_limited)."""


def read_text_limited(path, limit: int) -> str:
    """Read a UTF-8 text file of at most ``limit`` bytes.

    The size is checked before anything is read, and no more than the limit
    is ever read (a file that grows, or a device, can't get past it either).
    Raises FileTooBigError (an OSError, so callers that treat any OSError as
    "couldn't be read" stay safe), other OSErrors, or UnicodeDecodeError."""
    with open(path, "rb") as f:
        if os.fstat(f.fileno()).st_size > limit:
            raise FileTooBigError(f"{path} is bigger than {limit} bytes")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise FileTooBigError(f"{path} is bigger than {limit} bytes")
    return data.decode("utf-8")


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
    if template in ("free", "picture"):
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


TEMPLATES = ["simple", "package", "sticker", "free", "cottage", "picture"]


@dataclass
class LabelDoc:
    """One label as edited in the main window; also what autosave stores."""
    template: str = "simple"
    stock: str = stocks.DEFAULT_STOCK
    fields: dict = field(default_factory=lambda: default_fields("simple"))
    copies: int = 1
    lettering: dict = field(default_factory=dict)   # {} = standard look (DejaVu Sans)
    picture: dict | None = None    # see pictures.py; None = no picture
    qr: dict | None = None         # see qrcodes.py; None = no QR code

    # ---- convenience -------------------------------------------------
    def copy(self) -> "LabelDoc":
        """Deep copy (fields are nested dicts; the picture data string is shared)."""
        return LabelDoc(self.template, self.stock, copy.deepcopy(self.fields), self.copies,
                        dict(self.lettering), dict(self.picture) if self.picture else None,
                        dict(self.qr) if self.qr else None)

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
        elif template in ("free", "picture"):
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
        # a picture keeps going, placed the way the new kind of label places it
        if self.picture:
            pic = dict(self.picture)
            if template == "picture" and pic.get("place") not in ("fit", "fill"):
                pic.update(place="fit", size=100)
            elif template != "picture" and pic.get("place") in ("fit", "fill"):
                pic.update(place="above", size=35)
            self.picture = pic
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
        out = {"app": APP_KEY, "version": VERSION, "template": self.template,
               "stock": self.stock, "fields": copy.deepcopy(self.fields),
               "copies": self.copies}
        # Only written when it isn't the standard look, so a label in the
        # standard lettering is byte-for-byte what earlier versions wrote.
        lt = clean_lettering(self.lettering)
        if lt:
            out["lettering"] = lt
        from . import pictures, qrcodes
        pic = pictures.clean(self.picture)
        if pic:
            out["picture"] = pic
        qr = qrcodes.clean(self.qr)
        if qr:
            out["qr"] = qr
            if self.template == "package" and "qr" in out["fields"]:
                # earlier versions read the code from here
                out["fields"]["qr"] = qrcodes.payload(qr)
        return out

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
        from . import pictures, qrcodes
        qr = qrcodes.clean(data.get("qr"))
        if template == "package" and str(fields.get("qr") or "").strip():
            if qr is None:
                qr = legacy_qr(fields["qr"])
            fields["qr"] = ""
        doc = cls(template, stock, fields, data.get("copies", 1),
                  clean_lettering(data.get("lettering")),
                  pictures.compact(pictures.clean(data.get("picture"))), qr)
        doc.clamp_copies()
        return doc

    def snapshot(self) -> str:
        """Like dumps(), but a picture is replaced by a short reference, so the undo
        history doesn't keep a copy of a big picture for every change."""
        d = self.to_dict()
        if "picture" in d:
            from . import pictures
            key = pictures.digest(d["picture"])
            _BLOBS[key] = d["picture"]["png"]
            d["picture"] = dict(d["picture"], png="@" + key)
        return json.dumps(d, indent=2, ensure_ascii=False)

    @classmethod
    def from_snapshot(cls, text: str) -> "LabelDoc":
        """Undo: the document a snapshot() was made from."""
        data = json.loads(text)
        pic = data.get("picture")
        if isinstance(pic, dict) and str(pic.get("png", "")).startswith("@"):
            pic["png"] = _BLOBS.get(pic["png"][1:], "")
        return cls.from_dict(data)

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def loads(cls, text: str) -> "LabelDoc":
        try:
            data = json.loads(text)
        except (ValueError, TypeError, RecursionError):
            # RecursionError: absurdly deep nesting ("[[[[…"), never a real label
            raise LabelFileError("This label file is damaged and can't be opened.") from None
        return cls.from_dict(data)


_BLOBS: dict[str, str] = {}       # picture data by digest, for undo snapshots


def legacy_qr(text: str) -> dict:
    """The QR object for a package label's old ``fields["qr"]`` text (top-right corner,
    about the size it used to be)."""
    import re
    t = str(text).strip()
    looks_like_link = bool(re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I)) or (
        " " not in t and "." in t)
    return {"what": "link" if looks_like_link else "text", "value": t, "caption": "",
            "place": "corner_right", "size": 42}


def clean_lettering(value) -> dict:
    """The lettering choice as stored: {} for the standard look."""
    from . import lettering
    return {} if lettering.is_default(value) else lettering.clean(value)


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
        text = read_text_limited(path, MAX_LABEL_BYTES)
    except FileNotFoundError:
        raise LabelFileError("That label file isn't there any more. "
                             "It may have been moved or deleted.") from None
    except FileTooBigError:
        raise LabelFileError("This file is far too big to be a Food Labeler label, "
                             "so it wasn't opened.") from None
    except UnicodeDecodeError:
        raise LabelFileError("This label file is damaged and can't be opened.") from None
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
