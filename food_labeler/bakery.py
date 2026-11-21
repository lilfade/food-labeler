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

# Kinds of label a product can fill (My products in the main window).
PRODUCT_KINDS = ("cottage", "package", "simple")
QUICK_PRODUCTS = 6

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
        text = model.read_text_limited(path, model.MAX_BACKUP_BYTES).lstrip("﻿")
    except FileNotFoundError:
        return None, ""
    except model.FileTooBigError:
        return None, "too big"          # set aside like any other unreadable file
    except OSError as e:
        return None, str(e)
    except UnicodeDecodeError as e:
        return None, str(e)
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as e:
        return None, str(e) or "too deeply nested"
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


def state_for_address(region: str, new_state: str, old_state: str = "") -> str:
    """The address's "State" box after choosing ``new_state`` in Set up my bakery
    or My bakery: the state's postal abbreviation ("NE" for Nebraska) when the
    box is empty or still holds what was filled in for the state before
    (``old_state``'s abbreviation); otherwise exactly what the person typed.
    Custom rules fill in nothing."""
    region = str(region or "")
    new = str(new_state or "").upper()
    if not new or new_state == "custom" or len(new) != 2 or not new.isalpha():
        return region
    if not region.strip() or region.strip().upper() == str(old_state or "").upper():
        return new
    return region


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
    return [str(a).strip()[:60] for a in v[:200]
            if isinstance(a, str) and a.strip()][:20]


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
    kind = e.get("kind") if e.get("kind") in PRODUCT_KINDS else ""
    used = e.get("last_used")
    if not (isinstance(used, str) and re.fullmatch(r"\d{4}-\d\d-\d\d[T ][\d:.]{2,15}", used)):
        used = ""
    return {"id": str(e.get("id") or _new_id())[:40], "name": name,
            "net": str(e.get("net") or "").strip()[:80],
            "ingredients": str(e.get("ingredients") or "").strip()[:3000],
            "ingredient_ids": [str(x)[:40] for x in ids[:200] if isinstance(x, (str, int))
                               and not isinstance(x, bool)] if isinstance(ids, list) else [],
            "contains": str(e.get("contains") or "").strip()[:300],
            "no_allergens": bool(e.get("no_allergens", False)),
            "storage": str(e.get("storage") or "").strip()[:200],
            "best_by_days": days,
            # added in 1.5.0; older files simply don't have them
            "kind": kind,                        # the kind of label it was saved from
            "last_used": used,                   # "2026-11-21T09:30:00" or ""
            "favourite": e.get("favourite") is True}


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
            text = model.read_text_limited(path, model.MAX_BACKUP_BYTES).lstrip("﻿")
        except model.FileTooBigError:
            raise LibraryError(f"This file is far too big to be a Food Labeler {self.what} "
                               "file.") from None
        except (OSError, UnicodeDecodeError):
            raise LibraryError("That file couldn't be read.") from None
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):   # RecursionError: absurdly deep "[[[[…"
            raise LibraryError(f"This isn't a Food Labeler {self.what} file.") from None
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
    except (OSError, ValueError, RecursionError):
        log.exception("starter ingredients unreadable")
        return []


class Products(Library):
    """My products. Each remembers when it was last used and whether it is a
    favourite, so the main window can show the ones a baker reaches for."""

    fmt = PRODUCTS_FORMAT
    key = "products"
    what = "products"
    clean = staticmethod(clean_product)

    def mark_used(self, item_id: str, when: str | None = None) -> None:
        """Remember that a product was just put on a label (or saved)."""
        import datetime as dt
        p = self.get(item_id)
        if p is None:
            return
        p["last_used"] = when or dt.datetime.now().isoformat(timespec="seconds")
        self.save()

    def set_favourite(self, item_id: str, on: bool) -> None:
        p = self.get(item_id)
        if p is None:
            return
        p["favourite"] = bool(on)
        self.save()

    def quick(self, n: int = QUICK_PRODUCTS) -> list[dict]:
        """The products for the one-click buttons: favourites first, then the most
        recently used, then the rest by name."""
        return quick_products(self.items, n)

    def search(self, query: str, n: int = QUICK_PRODUCTS) -> list[dict]:
        """Products whose name has every word typed (see search_products)."""
        return search_products(self.items, query, n)


def _recent_first(items: list[dict]) -> list[dict]:
    used = sorted((p for p in items if p.get("last_used")), key=lambda p: p["last_used"],
                  reverse=True)
    rest = sorted((p for p in items if not p.get("last_used")), key=lambda p: p["name"].lower())
    return used + rest


def quick_products(items: list[dict], n: int = QUICK_PRODUCTS) -> list[dict]:
    """Favourites (most recently used first), then the others the same way."""
    fav = [p for p in items if p.get("favourite")]
    other = [p for p in items if not p.get("favourite")]
    return (_recent_first(fav) + _recent_first(other))[: max(0, n)]


def search_products(items: list[dict], query: str, n: int = QUICK_PRODUCTS) -> list[dict]:
    """Every product whose name contains each word of ``query`` (any case).
    Names starting with what was typed come first, then a word starting with it,
    then the rest; favourites and recently used ones before others. An empty
    query gives quick_products."""
    words = str(query or "").lower().split()
    if not words:
        return quick_products(items, n)
    q = " ".join(words)
    hits = [p for p in items if all(w in p["name"].lower() for w in words)]

    def rank(p):
        name = p["name"].lower()
        if name.startswith(q):
            return 0
        if any(part.startswith(words[0]) for part in re.split(r"[\s\-/(),]+", name)):
            return 1
        return 2
    order = {id(p): i for i, p in enumerate(quick_products(hits, len(hits)))}
    return sorted(hits, key=lambda p: (rank(p), order[id(p)]))[: max(0, n)]


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


def product_kind(product: dict) -> str:
    """The kind of label a product fills when the label in the window can't
    take one (saved before 1.5.0: cottage food)."""
    k = product.get("kind")
    return k if k in PRODUCT_KINDS else "cottage"


def apply_to_label(template: str, fields: dict, product: dict, today=None) -> dict:
    """Fill a cottage, package or simple label from a saved product.

    Cottage labels get everything (apply_product). A package label gets the
    name, weight, ingredients and allergens and a best-by date counted from
    today. A simple label gets the name as the food, the allergens, the
    storage words as its note, made today and used by the product's days."""
    from . import dates
    import datetime as dt
    if template == "cottage":
        return apply_product(fields, product, today)
    t = today or dates.today()
    days = product.get("best_by_days")
    out = dict(fields)
    if template == "package":
        out.update(product=product.get("name", ""), net=product.get("net", ""),
                   ingredients=product.get("ingredients", ""),
                   contains=product.get("contains", ""))
        if days:
            out["best_by"] = (t + dt.timedelta(days=int(days))).isoformat()
    elif template == "simple":
        out.update(food=product.get("name", ""), contains=product.get("contains", ""),
                   note=product.get("storage", ""), made_on=t.isoformat())
        if days:
            out["use_by"] = (t + dt.timedelta(days=int(days))).isoformat()
    return out


def product_from_label(template: str, fields: dict, name: str,
                       existing: dict | None = None, today=None) -> dict:
    """A My products entry from the label in the window. Saving over an existing
    product keeps what this kind of label doesn't show (a simple label has no
    ingredients, so saving one never empties a product's ingredients)."""
    from . import dates
    if template == "cottage":
        new = product_from_fields(fields, name)
    else:
        new = {"name": name}
        if template == "package":
            new.update(net=fields.get("net", ""), ingredients=fields.get("ingredients", ""),
                       contains=fields.get("contains", ""))
            t, best = today or dates.today(), dates.parse(fields.get("best_by"))
            if best and best > t:
                new["best_by_days"] = (best - t).days
        elif template == "simple":
            new.update(contains=fields.get("contains", ""), storage=fields.get("note", ""))
            made, use = dates.parse(fields.get("made_on")), dates.parse(fields.get("use_by"))
            if made and use and use > made:
                new["best_by_days"] = (use - made).days
    for k in ("id", "kind", "last_used", "favourite"):
        new.pop(k, None)                         # these stay as they were
    out = dict(existing or {})
    out.update(new)
    out["kind"] = template if template in PRODUCT_KINDS else out.get("kind", "")
    return clean_product(out) or {}
