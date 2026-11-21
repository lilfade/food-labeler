"""Known printer models, loaded from known_printers.json (bundled) plus an
optional user file of updates that High Thyme Kitchen can send.

A Definition says how to recognise a model (IEEE 1284 id, USB vid:pid, or
Windows/CUPS name patterns: plain text, never regular expressions, so a file
from anywhere can't make matching slow), which language it speaks (TSPL, ZPL, or
"driver" for printers that only print through their maker's driver) and its
preferred darkness/speed per label size, its print head's resolution (203 or
300 dpi), how wide it can print, how to set up a new roll by hand and whether we have
tested it on paper ("verified_on_paper"; untested models are shown as
"alpha — not tested yet"). Bluetooth has its own flag ("verified_bluetooth"):
a model tested over USB is still alpha when it is reached over Bluetooth,
until someone prints on it that way; likewise "verified_network" for printing
over the network (raw TCP to a print server or bridge). "bt_chunk" and "bt_delay_ms" say how
to pace a Bluetooth job for printers with small buffers. Files are validated strictly:
anything unexpected rejects the whole file, so a bad update can never leave
the program half-configured.

See docs/printer-definitions.md for the file format.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("food_labeler.known")

BUILTIN = Path(__file__).resolve().parent / "known_printers.json"
APP_CONFIG = Path(__file__).resolve().parent / "app_config.json"
FORMAT = "food-labeler-printers"
VERSION = 1
USER_FILE_NAME = "known_printers.json"

ALLOWED_KEYS = {"id", "name", "brands", "language", "dpi", "max_width_dots", "media", "usb",
                "ieee1284", "windows", "density", "speed", "stocks", "notes",
                "calibrate_by_hand", "max_width_mm", "verified_on_paper",
                "verified_bluetooth", "verified_network", "bt_chunk", "bt_delay_ms"}
LANGUAGES = ("tspl", "zpl", "driver")   # "driver": only through the maker's (Windows) driver
SUPPORT_TESTED = "Tested"
SUPPORT_ALPHA = "Alpha — not tested yet"
DPI_VALUES = (203, 300)        # print head resolutions Food Labeler lays out for
MAX_WIDTH_RANGE = (64, 4000)   # sane print head widths, in the printer's own dots
MAX_WIDTH_MM_RANGE = (8, 300)  # the same in mm ("max_width_mm")
BT_CHUNK_RANGE = (64, 65536)   # bytes per Bluetooth write ("bt_chunk")
BT_DELAY_RANGE = (0, 1000)     # pause between Bluetooth writes, ms ("bt_delay_ms")
STOCK_IDS = {"small", "medium", "large", "round", "xl"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VIDPID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
MAX_ENTRIES = 200
MAX_BY_HAND = 600             # "calibrate_by_hand": a few sentences, shown as they are
MAX_PATTERN = 80              # one "ieee1284"/"windows" pattern (all its alternatives)
MAX_SUBJECT = 200             # names longer than this are cut before matching


@lru_cache(maxsize=1024)
def alternatives(pattern: str) -> tuple[str, ...]:
    """A name pattern's alternatives: split on "|", trimmed, case-folded, empties dropped.

    Patterns are plain text. Every character, including ones that would mean
    something in a regular expression (``( ) * ? [ ] . ^ $``), is literal, so
    matching is a few substring searches and can never hang."""
    return tuple(a for a in (x.strip().casefold() for x in pattern.split("|")) if a)


def pattern_found(pattern: str, text: str) -> bool:
    """True if any alternative of ``pattern`` is in ``text`` (case-insensitive)."""
    subject = (text or "")[:MAX_SUBJECT].casefold()
    return any(a in subject for a in alternatives(pattern))


class DefinitionError(Exception):
    """The update file isn't valid. Message is friendly."""


@dataclass
class Definition:
    """One printer model (a validated entry of a printer definition file)."""
    id: str
    name: str
    language: str
    brands: list = field(default_factory=list)
    dpi: int = 203
    max_width_dots: int = 0      # widest print in this model's own dots; 0 = not known
    media: str = "gap"
    usb: list = field(default_factory=list)
    ieee1284: dict = field(default_factory=dict)
    windows: list = field(default_factory=list)
    density: dict = field(default_factory=dict)
    speed: dict = field(default_factory=dict)
    stocks: list = field(default_factory=list)
    notes: str = ""
    calibrate_by_hand: str = ""  # how to set up a new roll with the printer's own button
    verified_on_paper: bool = False  # we printed real labels on one; else "alpha"
    verified_bluetooth: bool = False  # ...and also over Bluetooth; else alpha on Bluetooth
    verified_network: bool = False    # ...and also over the network; else alpha that way
    bt_chunk: int = 0                # bytes per Bluetooth write; 0 = the program's default
    bt_delay_ms: int | None = None   # pause between Bluetooth writes; None = default

    @property
    def support(self) -> str:
        """What we can promise, in plain words: "Tested" or "Alpha — not tested yet"."""
        return SUPPORT_TESTED if self.verified_on_paper else SUPPORT_ALPHA

    @property
    def driver_only(self) -> bool:
        """Only prints through the maker's own driver (no TSPL/ZPL straight to it)."""
        return self.language == "driver"

    @property
    def display_name(self) -> str:
        """Clones share USB ids, so never claim a single brand."""
        if len(self.brands) > 1:
            return f"{self.name} ({' / '.join(self.brands)}…)"
        return self.name

    @property
    def max_width_mm(self) -> float:
        """Widest print in mm (0 = not known)."""
        return self.max_width_dots * 25.4 / self.dpi if self.max_width_dots else 0.0

    def fits(self, stock) -> bool:
        """True if a label of this size (a stocks.Stock at any dpi) fits the print head.

        The head width is converted to the stock's resolution, so a 203 dpi
        model overridden to 300 dpi keeps the same physical width."""
        if not self.max_width_dots:
            return True
        allowed = int(self.max_width_dots * stock.dpi / self.dpi + 0.5)
        return stock.w <= allowed

    def density_for(self, stock_id: str):
        """TSPL DENSITY for this size, the model's default, or None."""
        return self.density.get(stock_id, self.density.get("default"))

    def speed_for(self, stock_id: str):
        """TSPL SPEED for this size, the model's default, or None."""
        return self.speed.get(stock_id, self.speed.get("default"))

    # -- matching ------------------------------------------------------------
    def match_1284(self, info: dict) -> bool:
        """True if every ieee1284 pattern is found in the device id (keys upper-case)."""
        if not self.ieee1284 or not info:
            return False
        for k, pattern in self.ieee1284.items():
            if not pattern_found(pattern, info.get(k.upper(), "")):
                return False
        return True

    def match_usb(self, vidpid: str) -> bool:
        """True if vidpid ("vvvv:pppp") is one of this model's USB ids."""
        return bool(vidpid) and vidpid.lower() in self.usb

    def match_text(self, text: str) -> bool:
        """True if any ``windows`` pattern is found in a printer/driver/queue name."""
        return any(pattern_found(p, text) for p in self.windows)

    def text_match_length(self, text: str) -> int:
        """Length of the longest ``windows`` alternative found in ``text`` (0 = none)."""
        subject = (text or "")[:MAX_SUBJECT].casefold()
        return max((len(a) for p in self.windows for a in alternatives(p) if a in subject),
                   default=0)


def _int_map(v, name):
    """density/speed: a bare number becomes {"default": n}; maps are checked."""
    if v is None:
        return {}
    if isinstance(v, int) and not isinstance(v, bool):
        return {"default": v}
    if isinstance(v, dict) and all(isinstance(k, str) and isinstance(x, int)
                                   and not isinstance(x, bool) for k, x in v.items()):
        bad = set(v) - STOCK_IDS - {"default"}
        if bad:
            raise DefinitionError(f"“{name}” mentions an unknown label size.")
        return dict(v)
    raise DefinitionError(f"“{name}” should be a number or a list of numbers.")


def validate_entry(e) -> Definition:
    """Check one "printers" entry and build its Definition. Raises DefinitionError."""
    if not isinstance(e, dict):
        raise DefinitionError("The file has something in it that isn't a printer.")
    extra = set(e) - ALLOWED_KEYS
    if extra:
        raise DefinitionError("The file has things in it this version doesn't understand: "
                              + ", ".join(sorted(extra)))
    pid, name, lang = e.get("id"), e.get("name"), e.get("language")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise DefinitionError("A printer in the file has a missing or bad “id”.")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise DefinitionError(f"Printer “{pid}” has a missing or bad name.")
    if lang not in LANGUAGES:
        raise DefinitionError(f"Printer “{name}” must say language tspl, zpl or driver.")

    def str_list(key, check=None):
        v = e.get(key, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and len(x) <= 200 for x in v):
            raise DefinitionError(f"Printer “{name}” has a bad “{key}” list.")
        if check:
            for x in v:
                check(x)
        return list(v)

    def check_vidpid(x):
        if not VIDPID_RE.match(x.lower()):
            raise DefinitionError(f"“{x}” isn't a USB id like 0483:2025.")

    def check_pattern(x):
        # Plain text (see alternatives()); only its size and content are checked.
        if len(x) > MAX_PATTERN or "\x00" in x or not alternatives(x):
            raise DefinitionError(f"Printer “{name}” has a name pattern that is empty or too "
                                  f"long (at most {MAX_PATTERN} letters).")

    i1284 = e.get("ieee1284", {})
    if not isinstance(i1284, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                              for k, v in i1284.items()):
        raise DefinitionError(f"Printer “{name}” has a bad “ieee1284” section.")
    for v in i1284.values():
        check_pattern(v)
    stocks_ = str_list("stocks")
    if set(stocks_) - STOCK_IDS:
        raise DefinitionError(f"Printer “{name}” mentions an unknown label size.")
    dpi = e.get("dpi", 203)
    if isinstance(dpi, bool) or dpi not in DPI_VALUES:
        raise DefinitionError(f"Printer “{name}” must be 203 or 300 dpi; this version only "
                              "supports 203 dpi and 300 dpi printers.")
    width = e.get("max_width_dots", 0)
    if (isinstance(width, bool) or not isinstance(width, int)
            or not (width == 0 or MAX_WIDTH_RANGE[0] <= width <= MAX_WIDTH_RANGE[1])):
        raise DefinitionError(f"Printer “{name}” has a bad “max_width_dots” (it should be "
                              "the print width in dots, like 832).")
    width_mm = e.get("max_width_mm")
    if width_mm is not None:
        if (isinstance(width_mm, bool) or not isinstance(width_mm, (int, float))
                or not MAX_WIDTH_MM_RANGE[0] <= width_mm <= MAX_WIDTH_MM_RANGE[1]):
            raise DefinitionError(f"Printer “{name}” has a bad “max_width_mm” (it should "
                                  "be the print width in mm, like 104).")
        if not width:                    # dots win when both are given
            width = int(width_mm * int(dpi) / 25.4)
    verified = e.get("verified_on_paper", False)
    if not isinstance(verified, bool):
        raise DefinitionError(f"Printer “{name}” has a bad “verified_on_paper” "
                              "(true or false).")
    verified_bt = e.get("verified_bluetooth", False)
    if not isinstance(verified_bt, bool):
        raise DefinitionError(f"Printer “{name}” has a bad “verified_bluetooth” "
                              "(true or false).")
    verified_net = e.get("verified_network", False)
    if not isinstance(verified_net, bool):
        raise DefinitionError(f"Printer “{name}” has a bad “verified_network” "
                              "(true or false).")
    bt_chunk = e.get("bt_chunk", 0)
    if (isinstance(bt_chunk, bool) or not isinstance(bt_chunk, int)
            or not (bt_chunk == 0 or BT_CHUNK_RANGE[0] <= bt_chunk <= BT_CHUNK_RANGE[1])):
        raise DefinitionError(f"Printer “{name}” has a bad “bt_chunk” (it should be a number "
                              f"of bytes from {BT_CHUNK_RANGE[0]} to {BT_CHUNK_RANGE[1]}).")
    bt_delay = e.get("bt_delay_ms")
    if bt_delay is not None and (isinstance(bt_delay, bool) or not isinstance(bt_delay, int)
                                 or not BT_DELAY_RANGE[0] <= bt_delay <= BT_DELAY_RANGE[1]):
        raise DefinitionError(f"Printer “{name}” has a bad “bt_delay_ms” (it should be a "
                              f"number of milliseconds from {BT_DELAY_RANGE[0]} to "
                              f"{BT_DELAY_RANGE[1]}).")
    media = e.get("media", "gap")
    if media not in ("gap", "continuous", "black-mark"):
        raise DefinitionError(f"Printer “{name}” has an unknown media type.")
    notes = e.get("notes", "")
    if not isinstance(notes, str):
        raise DefinitionError(f"Printer “{name}” has bad notes.")
    by_hand = e.get("calibrate_by_hand", "")
    if not isinstance(by_hand, str) or len(by_hand) > MAX_BY_HAND or "\x00" in by_hand:
        raise DefinitionError(f"Printer “{name}” has a bad “calibrate_by_hand” (it should be "
                              f"a few plain sentences, at most {MAX_BY_HAND} letters).")
    return Definition(
        id=pid, name=name.strip(), language=lang,
        brands=str_list("brands"), dpi=int(dpi), max_width_dots=width, media=media,
        usb=[x.lower() for x in str_list("usb", check_vidpid)],
        ieee1284={k.upper(): v for k, v in i1284.items()},
        windows=str_list("windows", check_pattern),
        density=_int_map(e.get("density"), "density"), speed=_int_map(e.get("speed"), "speed"),
        stocks=stocks_ or sorted(STOCK_IDS), notes=notes,
        calibrate_by_hand=by_hand.strip(), verified_on_paper=verified,
        verified_bluetooth=verified_bt, verified_network=verified_net, bt_chunk=bt_chunk,
        bt_delay_ms=bt_delay,
    )


def parse_file_text(text: str) -> list[Definition]:
    """Parse and validate a whole definition file. Raises DefinitionError."""
    # Windows Notepad saves "UTF-8" with a byte-order mark, which json rejects.
    text = text.lstrip("﻿")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):   # RecursionError: absurdly deep "[[[[…"
        raise DefinitionError("This isn't a Food Labeler printer update file.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise DefinitionError("This isn't a Food Labeler printer update file.")
    if data.get("version") != VERSION:
        raise DefinitionError("This printer update file is for a different version of "
                              "Food Labeler.")
    entries = data.get("printers")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_ENTRIES:
        raise DefinitionError("This printer update file has no printers in it.")
    defs = [validate_entry(e) for e in entries]
    ids = [d.id for d in defs]
    if len(set(ids)) != len(ids):
        raise DefinitionError("This printer update file lists the same printer twice.")
    return defs


def _to_json(d: Definition) -> dict:
    """Definition back to its file form (for writing the merged user file)."""
    out = {"id": d.id, "name": d.name, "brands": d.brands, "language": d.language,
           "dpi": d.dpi, "media": d.media, "usb": d.usb, "ieee1284": d.ieee1284,
           "windows": d.windows, "density": d.density, "speed": d.speed,
           "stocks": d.stocks, "notes": d.notes}
    if d.max_width_dots:
        out["max_width_dots"] = d.max_width_dots
    if d.calibrate_by_hand:
        out["calibrate_by_hand"] = d.calibrate_by_hand
    if d.verified_on_paper:
        out["verified_on_paper"] = True
    if d.verified_bluetooth:
        out["verified_bluetooth"] = True
    if d.verified_network:
        out["verified_network"] = True
    if d.bt_chunk:
        out["bt_chunk"] = d.bt_chunk
    if d.bt_delay_ms is not None:
        out["bt_delay_ms"] = d.bt_delay_ms
    return out


class KnownPrinters:
    """The bundled printer list with the user's update file merged on top.

    Merge rule: entries are keyed by ``id``. The bundled file is loaded first,
    then the user file (``<data dir>/known_printers.json``); a user entry with
    the same id replaces the built-in one completely (no field-by-field merge),
    new ids are added. A broken user file is logged and ignored, so the
    built-in list always works.
    """

    def __init__(self, user_dir: Path | None = None, builtin: Path = BUILTIN):
        self.builtin_path = builtin
        self.user_path = Path(user_dir) / USER_FILE_NAME if user_dir else None
        self.reload()

    def reload(self):
        """(Re)read both files."""
        self.defs: dict[str, Definition] = {}
        try:
            for d in parse_file_text(_read(self.builtin_path)):
                self.defs[d.id] = d
        except (OSError, DefinitionError):
            log.exception("built-in printer list unreadable")
        self.user_ids: list[str] = []
        if self.user_path and self.user_path.is_file():
            try:
                for d in parse_file_text(_read(self.user_path)):
                    self.defs[d.id] = d          # user updates win over built-in
                    self.user_ids.append(d.id)
            except (OSError, UnicodeDecodeError, DefinitionError):
                log.exception("user printer list unreadable; ignoring it")

    def all(self) -> list[Definition]:
        """Every known model, built-in order first, then user additions."""
        return list(self.defs.values())

    def get(self, pid: str) -> Definition | None:
        """The model with this id (e.g. "lp610bt-compatible"), or None."""
        return self.defs.get(str(pid or ""))

    def match(self, info: dict | None = None, vidpid: str = "", text: str = "") -> Definition | None:
        """Best match: IEEE 1284 id first, then USB id, then names (Windows/CUPS)."""
        ordered = sorted(self.defs.values(), key=lambda d: -len(d.ieee1284))
        if info:
            for d in ordered:
                if d.match_1284(info):
                    return d
        if vidpid:
            for d in self.defs.values():
                if d.match_usb(vidpid):
                    return d
        if text:
            # The most specific name wins: the entry whose longest *matching*
            # alternative is longest ("POLONO PL60" beats a plain "Polono"); on a
            # tie, the entry listed first.
            best, best_len = None, 0
            for d in self.defs.values():
                n = d.text_match_length(text)
                if n > best_len:
                    best, best_len = d, n
            return best
        return None

    def import_file(self, path) -> list[str]:
        """Validate and add an update file. Returns the names added/updated.

        The new file is merged into the user's existing update file (same id
        replaces, new ids added) and written atomically; nothing is written
        if the new file is invalid.
        """
        from .model import FileTooBigError
        try:
            text = _read(path)
        except FileTooBigError:
            raise DefinitionError("This file is far too big to be a Food Labeler printer "
                                  "update file.") from None
        except (OSError, UnicodeDecodeError):
            raise DefinitionError("That file couldn't be read.") from None
        new = parse_file_text(text)
        if not self.user_path:
            raise DefinitionError("There is nowhere to keep the update.")
        existing = {}
        if self.user_path.is_file():
            try:
                existing = {d.id: d for d in parse_file_text(_read(self.user_path))}
            except (OSError, UnicodeDecodeError, DefinitionError):
                existing = {}
        for d in new:
            existing[d.id] = d
        from .model import atomic_write_text
        atomic_write_text(self.user_path, json.dumps(
            {"format": FORMAT, "version": VERSION,
             "printers": [_to_json(d) for d in existing.values()]}, indent=2))
        self.reload()
        return [d.display_name for d in new]


def _read(path) -> str:
    """A printer definition file's text (refused if bigger than any real one)."""
    from .model import MAX_UPDATE_BYTES, read_text_limited
    return read_text_limited(path, MAX_UPDATE_BYTES)


def app_config() -> dict:
    """Bundled app_config.json (help page, support e-mail address and name); {} if unreadable."""
    try:
        data = json.loads(APP_CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
