"""User settings, recent files, autosave, log file — all in the user data folder.

Data folder (``data_dir``)::

    Windows  %APPDATA%\\FoodLabeler
    macOS    ~/Library/Application Support/FoodLabeler
    Linux    $XDG_DATA_HOME/food-labeler  (default ~/.local/share/food-labeler)

It holds settings.json, autosave.json, food-labeler.log (rotated) and the
optional known_printers.json printer update. Saved labels go to
Documents/My Food Labels instead, where people can find them.
``FOOD_LABELER_DATA`` and ``FOOD_LABELER_LABELS`` override both folders
(the tests use them).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import model

log = logging.getLogger("food_labeler")

DEFAULTS = {
    "ui_scale": 1.0,
    "date_style": "us",
    "kitchen": {
        "business": "",
        "address": "",
        "disclaimer": model.DEFAULT_DISCLAIMER,
        "cross_contact": model.DEFAULT_CROSS_CONTACT,
    },
    # Printers the user has used, keyed by stable identity (see printers.Printer.id):
    # {"nickname": str, "kind": "" | "tspl" | "zpl", "stock": str,
    #  "manual": bool, "method": str, "target": str}   (manual = network, added by hand)
    "printers": {},
    "selected": "",              # id of the printer chosen in the dropdown
    "advanced": {
        "density": {},           # stock id -> TSPL density 0-15
        "speed": {},             # stock id -> TSPL speed
        "gap": {},               # stock id -> gap mm
        "invert": False,         # flip TSPL bitmap polarity
        "zpl_darkness": None,
    },
    "recent": [],                # [{"path": ..., "name": ...}]
    "bakery_offered": False,     # the "Set up my bakery" question was asked once
    "last_folder": "",
    "window": "",
}

MAX_RECENT = 8


def data_dir() -> Path:
    """The per-user data folder (created if missing)."""
    override = os.environ.get("FOOD_LABELER_DATA")
    if override:
        p = Path(override)
    elif sys.platform.startswith("win"):
        p = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "FoodLabeler"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "FoodLabeler"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        p = Path(base) / "food-labeler"
    p.mkdir(parents=True, exist_ok=True)
    return p


def documents_dir() -> Path:
    """The user's real Documents folder (OneDrive-redirected or localised names too)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (Documents, follows OneDrive redirection)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            out = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True,
                                 timeout=3)
            p = out.stdout.strip()
            if out.returncode == 0 and p and Path(p) != Path.home():
                return Path(p)
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Documents"


def labels_dir() -> Path:
    """Where Save puts labels by default: Documents/My Food Labels."""
    override = os.environ.get("FOOD_LABELER_LABELS")
    p = Path(override) if override else documents_dir() / "My Food Labels"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.exception("could not create labels folder %s", p)
    return p


def setup_logging() -> Path:
    """Log INFO and up to a small rotating file in the data folder. Returns its path."""
    path = data_dir() / "food-labeler.log"
    root = logging.getLogger("food_labeler")
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        try:
            h = RotatingFileHandler(path, maxBytes=512_000, backupCount=2, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            root.addHandler(h)
        except OSError:
            pass
        root.setLevel(logging.INFO)
    return path


def _merge(base: dict, got: dict) -> dict:
    """Overlay a loaded settings file on the defaults, key by key.

    Only keys that exist in the defaults survive, and only with the expected
    type (an int is accepted where a float is expected; anything is accepted
    where the default is None or an empty dict). Non-empty default dicts are
    merged recursively, so a settings file from an older version picks up new
    defaults and a hand-edited file with a wrong type can't crash the app.
    """
    out = {}
    for k, v in base.items():
        if isinstance(v, dict) and isinstance(got.get(k), dict) and v:
            out[k] = _merge(v, got[k])
        elif k in got and (type(got[k]) is type(v) or v is None or v == {} or
                           isinstance(v, float) and isinstance(got[k], int)):
            out[k] = got[k]
        else:
            out[k] = json.loads(json.dumps(v))
    return out


class Settings:
    """settings.json as a dict-like object. Every change is saved explicitly."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self):
        """Read the file over the defaults; a missing or broken file means defaults."""
        try:
            got = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                self.data = _merge(DEFAULTS, got)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.exception("settings unreadable; using defaults")

    def save(self):
        """Write atomically; failures are logged, never shown (settings aren't precious)."""
        try:
            model.atomic_write_text(self.path, json.dumps(self.data, indent=2, ensure_ascii=False))
        except OSError:
            log.exception("could not save settings")

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    # ---- recent files ----------------------------------------------------
    def add_recent(self, path, name: str):
        """Put a file at the front of "My saved labels" (max MAX_RECENT, no duplicates)."""
        path = str(Path(path).resolve())
        rec = [r for r in self.data["recent"] if r.get("path") != path]
        rec.insert(0, {"path": path, "name": name or Path(path).stem})
        self.data["recent"] = rec[:MAX_RECENT]
        self.save()

    def recent(self) -> list[dict]:
        """Recent files that still exist."""
        return [r for r in self.data["recent"] if Path(r.get("path", "")).is_file()]

    def remove_recent(self, path):
        path = str(Path(path).resolve())
        self.data["recent"] = [r for r in self.data["recent"] if r.get("path") != path]
        self.save()

    # ---- printers ----------------------------------------------------------
    def printer_info(self, pid: str) -> dict:
        """The (mutable, created on demand) settings entry for printer id ``pid``."""
        return self.data["printers"].setdefault(pid, {}) if pid else {}

    def nickname(self, pid: str) -> str:
        return str(self.data["printers"].get(pid, {}).get("nickname") or "")

    def nicknames(self) -> dict:
        return {k: v.get("nickname", "") for k, v in self.data["printers"].items()
                if v.get("nickname")}

    # ---- context for rendering -------------------------------------------
    def render_ctx(self) -> dict:
        """The settings that change what is printed (see render.render)."""
        return {"date_style": self.data["date_style"],
                "kitchen_name": self.data["kitchen"].get("business", "")}


# ---- autosave ---------------------------------------------------------------
#
# The main window writes autosave.json every few seconds when anything changed
# (and on errors and on close). It stores the document, the file it came from
# and whether it had unsaved changes. On the next start App._restore_session
# brings it back exactly: same label, same file, and still marked "not saved
# yet" if it was — so a power cut or crash never loses what was typed.

def autosave_path() -> Path:
    """<data dir>/autosave.json"""
    return data_dir() / "autosave.json"


def write_autosave(doc: model.LabelDoc, path: str | None, dirty: bool) -> None:
    """Save the session: the document, its file path (or None) and the dirty flag."""
    payload = {"doc": doc.to_dict(), "path": path or "", "dirty": bool(dirty)}
    model.atomic_write_text(autosave_path(), json.dumps(payload, indent=1, ensure_ascii=False))


def read_autosave():
    """Return (doc, path, dirty) or None."""
    try:
        payload = json.loads(autosave_path().read_text(encoding="utf-8"))
        doc = model.LabelDoc.from_dict(payload["doc"])
        return doc, payload.get("path") or None, bool(payload.get("dirty"))
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a broken autosave must never stop the app
        log.exception("autosave unreadable")
        return None
