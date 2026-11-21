"""My bakery: the baker's own details and libraries, kept in the data folder.

- ``my_bakery.json``      business details, state, label options ("My kitchen details")
- ``my_ingredients.json`` ingredients with their sub-ingredients and allergens
- ``my_products.json``    saved products (name, net weight, ingredients, allergens, storage)

These files belong to the user: app updates never replace or reset them.
Each has a ``format`` id and a ``version``; an older file is migrated forward
when read, keys a newer version wrote are kept when saving, and a file that
can't be read is set aside as ``.broken`` (never overwritten) so nothing a
baker typed is silently lost. Nothing here imports Tk.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from pathlib import Path

from . import model

log = logging.getLogger("food_labeler.bakery")

STARTER = Path(__file__).resolve().parent / "starter_ingredients.json"

PROFILE_NAME = "my_bakery.json"
PROFILE_FORMAT = "food-labeler-bakery"
PROFILE_VERSION = 1
INGREDIENTS_NAME = "my_ingredients.json"
INGREDIENTS_FORMAT = "food-labeler-ingredients"
PRODUCTS_NAME = "my_products.json"
PRODUCTS_FORMAT = "food-labeler-products"
LIB_VERSION = 1

PROFILE_DEFAULTS = {
    "state": "",                 # preset id: "NE", "TX", ..., "custom"; "" = not chosen yet
    "business": "",
    "legal_entity": "",
    "street": "",
    "street2": "",
    "city": "",
    "region": "",                # state / province as written in the address
    "zip": "",
    "phone": "",
    "email": "",
    "website": "",               # for a QR code ("A website link"); not printed as text
    "permit": "",
    "permit_label": "Permit #",
    "county": "",
    "show_phone": False,
    "show_email": False,
    "metric": None,              # None: follow the state; True/False: always / never grams
    "cross_contact": "",         # e.g. "Made in a home kitchen that also handles ..."
    "setup_done": False,
}


class LibraryError(Exception):
    """A library file to import isn't valid. Message is friendly."""


def _read_json(path: Path, fmt: str):
    """Read a user file. Returns (data or None, problem). Missing file -> (None, "")."""
    try:
        text = path.read_text(encoding="utf-8").lstrip("﻿")
    except FileNotFoundError:
        return None, ""
    except OSError as e:
        return None, str(e)
    try:
        data = json.loads(text)
    except ValueError as e:
        return None, str(e)
    if not isinstance(data, dict) or data.get("format") != fmt:
        return None, "wrong format"
    return data, ""


def _set_aside(path: Path):
    """Keep an unreadable file for a helper to look at; never write over it."""
    try:
        path.replace(path.with_name(path.name + ".broken"))
        log.warning("set aside unreadable %s", path)
    except OSError:
        log.exception("could not set aside %s", path)


# ---------------------------------------------------------------------------
# profile ("My kitchen details")
# ---------------------------------------------------------------------------

def split_address(text: str) -> dict:
    """Best effort: "123 Garden Lane\\nSpringfield, IL 62704" -> street/city/region/zip."""
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    out = {}
    if not lines:
        return out
    m = re.match(r"^(.*?),\s*([A-Za-z .]+?)\s+(\d{5}(?:-\d{4})?)$", lines[-1])
    if m and len(lines) >= 2:
        out.update(city=m.group(1).strip(), region=m.group(2).strip(), zip=m.group(3))
        out["street"] = lines[0]
        if len(lines) > 2:
            out["street2"] = ", ".join(lines[1:-1])
    else:
        out["street"] = ", ".join(lines)
    return out


class Profile:
    """my_bakery.json. ``data`` always has every PROFILE_DEFAULTS key.

    First run: if the file doesn't exist, the business name and address
    already typed for package labels (settings.json "kitchen") are copied in,
    so nobody has to type them twice.
    """

    def __init__(self, path: Path | None = None, kitchen: dict | None = None):
        self.path = Path(path) if path else None
        self.data = copy.deepcopy(PROFILE_DEFAULTS)
        self.extra: dict = {}
        self.exists = False
        self.read_only = False
        self.load(kitchen or {})

    def load(self, kitchen: dict | None = None):
        self.data = copy.deepcopy(PROFILE_DEFAULTS)
        if not self.path:
            return
        got, problem = _read_json(self.path, PROFILE_FORMAT)
        if got is None:
            if problem:
                _set_aside(self.path)
            if kitchen:
                self.data["business"] = str(kitchen.get("business") or "")
                self.data.update(split_address(kitchen.get("address", "")))
                cc = kitchen.get("cross_contact")
                # only a notice the baker wrote themselves; the built-in example
                # describes one particular kitchen
                if isinstance(cc, str) and cc.strip() and cc != model.DEFAULT_CROSS_CONTACT:
                    self.data["cross_contact"] = cc
            return
        self.exists = True
        ver = got.get("version", 0)
        if not isinstance(ver, int) or ver > PROFILE_VERSION:
            self.read_only = True        # newer app wrote it: read what we can, never write
        self.data.update(self.migrate(got))
        self.extra = {k: v for k, v in got.items()
                      if k not in PROFILE_DEFAULTS and k not in ("format", "version")}

    @staticmethod
    def migrate(got: dict) -> dict:
        """Older file layouts -> current keys. Wrong types fall back to defaults
        key by key; nothing else is lost."""
        got = dict(got)
        # version 0 (pre-release test builds) kept the address as one text block
        if "address" in got and not got.get("street"):
            got.update(split_address(got.pop("address")))
        out = {}
        for k, default in PROFILE_DEFAULTS.items():
            if k not in got:
                continue
            v = got[k]
            if k == "metric":
                if v in (None, True, False):
                    out[k] = v
            elif isinstance(default, bool):
                if isinstance(v, bool):
                    out[k] = v
            elif isinstance(v, str):
                out[k] = v[:400]
        return out

    def save(self):
        if not self.path or self.read_only:
            return
        payload = dict(self.extra)
        payload.update(self.data)
        payload.update({"format": PROFILE_FORMAT, "version": PROFILE_VERSION})
        model.atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))
        self.exists = True

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def address_lines(self) -> list[str]:
        """The complete mailing address as label lines, or [] if any part is missing
        (a label never shows half an address; the Label check asks for the rest)."""
        d = self.data
        return address_lines(d)

    def metric_for(self, metric_required: bool) -> bool:
        """Grams on the label: always when the state requires it, else the user's choice."""
        if metric_required:
            return True
        return bool(self.data.get("metric")) if self.data.get("metric") is not None else False


def address_lines(d: dict) -> list[str]:
    """Street / (line 2) / "City, ST ZIP" — or [] unless street, city, state and ZIP are all set."""
    parts = [str(d.get(k) or "").strip() for k in ("street", "city", "region", "zip")]
    if not all(parts):
        return []
    street, city, region, zip_ = parts
    lines = [street]
    if str(d.get("street2") or "").strip():
        lines.append(str(d["street2"]).strip())
    lines.append(f"{city}, {region} {zip_}")
    return lines


# ---------------------------------------------------------------------------
# libraries (ingredients, products)
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _clean_allergens(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(a).strip()[:60] for a in v if str(a).strip()][:20]


def clean_ingredient(e) -> dict | None:
    """One ingredient entry, tidied; None if it has no name."""
    if not isinstance(e, dict):
        return None
    name = str(e.get("name") or "").strip()[:120]
    if not name:
        return None
    return {"id": str(e.get("id") or _new_id())[:40], "name": name,
            "sub": str(e.get("sub") or "").strip()[:600],
            "allergens": _clean_allergens(e.get("allergens")),
            "check": bool(e.get("check", False))}


def clean_product(e) -> dict | None:
    """One product entry, tidied; None if it has no name."""
    if not isinstance(e, dict):
        return None
    name = str(e.get("name") or "").strip()[:120]
    if not name:
        return None
    days = e.get("best_by_days")
    if not (isinstance(days, int) and not isinstance(days, bool) and 0 < days <= 3650):
        days = None
    ids = e.get("ingredient_ids")
    return {"id": str(e.get("id") or _new_id())[:40], "name": name,
            "net": str(e.get("net") or "").strip()[:80],
            "ingredients": str(e.get("ingredients") or "").strip()[:3000],
            "ingredient_ids": [str(x) for x in ids][:200] if isinstance(ids, list) else [],
            "contains": str(e.get("contains") or "").strip()[:300],
            "no_allergens": bool(e.get("no_allergens", False)),
            "storage": str(e.get("storage") or "").strip()[:200],
            "best_by_days": days}


class Library:
    """A list of entries in one JSON file: {"format", "version", "<key>": [...]}"""

    fmt = ""
    key = "items"
    clean = staticmethod(clean_ingredient)

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.items: list[dict] = []
        self.extra: dict = {}
        self.read_only = False
        self.exists = False
        self.load()

    def load(self):
        self.items, self.extra = [], {}
        if not self.path:
            return
        got, problem = _read_json(self.path, self.fmt)
        if got is None:
            if problem:
                _set_aside(self.path)
            return
        self.exists = True
        ver = got.get("version", 0)
        if not isinstance(ver, int) or ver > LIB_VERSION:
            self.read_only = True
        self.items = self._clean_all(got.get(self.key))
        self.extra = {k: v for k, v in got.items() if k not in ("format", "version", self.key)}

    def _clean_all(self, entries) -> list[dict]:
        out, ids = [], set()
        for e in entries if isinstance(entries, list) else []:
            c = self.clean(e)
            if c is None:
                continue
            while c["id"] in ids:
                c["id"] = _new_id()
            ids.add(c["id"])
            out.append(c)
        return out

    def to_json(self) -> dict:
        payload = dict(self.extra)
        payload.update({"format": self.fmt, "version": LIB_VERSION, self.key: self.items})
        return payload

    def save(self):
        if not self.path or self.read_only:
            return
        model.atomic_write_text(self.path, json.dumps(self.to_json(), indent=2,
                                                      ensure_ascii=False))
        self.exists = True

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def find(self, name: str) -> dict | None:
        low = str(name).strip().lower()
        return next((i for i in self.items if i["name"].lower() == low), None)

    def put(self, entry: dict) -> dict:
        """Add or replace (same id) an entry and save. Returns the stored entry."""
        c = self.clean(entry)
        if c is None:
            raise LibraryError("Please give it a name.")
        for i, cur in enumerate(self.items):
            if cur["id"] == c["id"]:
                self.items[i] = c
                break
        else:
            self.items.append(c)
        self.save()
        return c

    def remove(self, item_id: str):
        self.items = [i for i in self.items if i["id"] != item_id]
        self.save()

    def sorted(self) -> list[dict]:
        return sorted(self.items, key=lambda i: i["name"].lower())

    # -- backup ------------------------------------------------------------------
    def export_file(self, path) -> Path:
        path = Path(path)
        model.atomic_write_text(path, json.dumps(self.to_json(), indent=2, ensure_ascii=False))
        return path

    def import_file(self, path) -> tuple[list[str], list[str]]:
        """Merge a backup file in. Same name (or id) replaces, others are added.
        Returns (added names, updated names). Nothing is written if invalid."""
        try:
            text = Path(path).read_text(encoding="utf-8").lstrip("﻿")
            data = json.loads(text)
        except (OSError, UnicodeDecodeError, ValueError):
            raise LibraryError("That file couldn't be read.") from None
        if not isinstance(data, dict) or data.get("format") != self.fmt:
            raise LibraryError(f"This isn't a Food Labeler {self.what} file.")
        ver = data.get("version")
        if not isinstance(ver, int) or ver > LIB_VERSION:
            raise LibraryError(f"This {self.what} file was made by a newer Food Labeler. "
                               "Please update the program first.")
        new = self._clean_all(data.get(self.key))
        if not new:
            raise LibraryError(f"This {self.what} file is empty.")
        added, updated = [], []
        for e in new:
            cur = self.get(e["id"]) or self.find(e["name"])
            if cur is not None:
                e["id"] = cur["id"]
                self.items[self.items.index(cur)] = e
                updated.append(e["name"])
            else:
                self.items.append(e)
                added.append(e["name"])
        self.save()
        return added, updated

    what = "list"


class Ingredients(Library):
    """My ingredients. On first use the starter list is copied in (and is then the
    user's own: later app updates never change it)."""

    fmt = INGREDIENTS_FORMAT
    key = "ingredients"
    what = "ingredients"
    clean = staticmethod(clean_ingredient)

    def __init__(self, path: Path | None, starter: Path = STARTER):
        self.starter_path = Path(starter)
        super().__init__(path)
        if not self.exists and not self.read_only:
            self.items = self._clean_all(load_starter(self.starter_path))
            for i in self.items:
                i["check"] = True
            if self.path and not self.path.with_name(self.path.name + ".broken").exists():
                self.save()

    def label_text(self, entry: dict) -> str:
        return ingredient_text(entry)


def load_starter(path: Path = STARTER) -> list:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("ingredients", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        log.exception("starter ingredients unreadable")
        return []


class Products(Library):
    fmt = PRODUCTS_FORMAT
    key = "products"
    what = "products"
    clean = staticmethod(clean_product)


# ---------------------------------------------------------------------------
# building the ingredient line
# ---------------------------------------------------------------------------

def ingredient_text(entry: dict) -> str:
    """"Butter (cream, salt)" — the name with its sub-ingredients in brackets."""
    name = str(entry.get("name") or "").strip()
    sub = str(entry.get("sub") or "").strip()
    return f"{name} ({sub})" if sub else name


def build_ingredients(entries: list[dict]) -> str:
    """The ingredient statement from ingredients picked heaviest first."""
    return ", ".join(t for t in (ingredient_text(e) for e in entries) if t)


def allergens_for(entries: list[dict]) -> list[str]:
    """The allergens of the picked ingredients, major allergens first, no repeats."""
    from .cottage import merge_allergens
    return merge_allergens([e.get("allergens") for e in entries], model.ALLERGENS)


def product_from_fields(fields: dict, name: str | None = None, pid: str | None = None,
                        ingredient_ids=None) -> dict:
    """A My products entry from what is on a cottage label right now."""
    days = None
    from . import dates
    made, best = dates.parse(fields.get("made_on")), dates.parse(fields.get("best_by"))
    if made and best and best > made:
        days = (best - made).days
    return clean_product({
        "id": pid, "name": name or fields.get("product", ""), "net": fields.get("net", ""),
        "ingredients": fields.get("ingredients", ""),
        "ingredient_ids": ingredient_ids or [],
        "contains": fields.get("contains", ""), "no_allergens": fields.get("no_allergens", False),
        "storage": fields.get("storage", ""), "best_by_days": days}) or {}


def apply_product(fields: dict, product: dict, today=None) -> dict:
    """Fill a cottage label's fields from a saved product (dates counted from today)."""
    from . import dates
    import datetime as dt
    t = today or dates.today()
    out = dict(fields)
    out.update(product=product.get("name", ""), net=product.get("net", ""),
               ingredients=product.get("ingredients", ""),
               contains=product.get("contains", ""),
               no_allergens=bool(product.get("no_allergens", False)),
               storage=product.get("storage", ""), made_on=t.isoformat())
    if product.get("best_by_days"):
        out["best_by"] = (t + dt.timedelta(days=int(product["best_by_days"]))).isoformat()
    return out
