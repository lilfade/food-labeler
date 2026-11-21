"""Small checks for values read from files and from other programs.

Label files, settings and the baker's backups are JSON, and Python's json
module accepts things no real file has: ``NaN``, ``Infinity``, numbers like
``1e400`` (which become infinity), and lists or objects where a word is
expected. These helpers turn anything unexpected into the default instead
of an error, so a damaged or strange file can never stop the program.

``device_name`` tidies names that come from printers and other devices
(Bluetooth, USB, the system's printer list) before they are shown.

Nothing here imports Tk.
"""
from __future__ import annotations

import math


MAX_INT = 2 ** 53          # bigger whole numbers (JSON allows 400 digits) are never real


def is_number(v) -> bool:
    """True for a real, finite int or float (not True/False, NaN, infinity or a
    whole number too big to be a float)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if isinstance(v, int):
        return -MAX_INT <= v <= MAX_INT
    return math.isfinite(v)


def to_int(v, lo, hi, default):
    """``v`` rounded and kept within lo..hi; ``default`` if it isn't a usable number."""
    if not is_number(v):
        return default
    try:
        return max(lo, min(hi, int(round(v))))
    except (OverflowError, ValueError):
        return default


def choice(v, allowed, default):
    """``v`` if it is a word found in ``allowed`` (a dict, set, list or tuple), else
    ``default``. Lists and objects from a file are never looked up (they can't be
    dict keys)."""
    return v if isinstance(v, str) and v in allowed else default


def text(v, limit: int | None = None) -> str:
    """``v`` (a str) with any half of a character pair (a lone surrogate, which JSON
    allows but no file can be written with) replaced by "?", cut to ``limit``
    characters."""
    s = v if limit is None else v[:limit]
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        s = s.encode("utf-8", "replace").decode("utf-8")
    return s


def utf8_prefix(s: str, limit: int) -> str:
    """The longest start of ``s`` that is at most ``limit`` bytes in UTF-8."""
    b = s.encode("utf-8", "replace")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", "ignore")


MAX_DEVICE_NAME = 80


def device_name(name, limit: int = MAX_DEVICE_NAME) -> str:
    """A device's name as it may be shown: one line, printable characters only,
    single spaces, at most ``limit`` characters ("" for anything that isn't text)."""
    if not isinstance(name, str):
        return ""
    s = "".join(c if c.isprintable() else " " for c in name[:limit * 4])
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[:limit - 1].rstrip() + "…"
    return s
