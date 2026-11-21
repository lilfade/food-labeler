"""QR codes on labels: what the code holds, and how big each square is.

A label's QR code is a plain dict (``LabelDoc.qr``)::

    {"what": "link" | "phone" | "email" | "text", "value": "...",
     "caption": "Scan for our menu",       # optional line under the code
     "place": "above" | "bottom" | "left" | "right" | "corner" | "corner_right"
              | "corner_bottom_left" | "corner_bottom_right",
     "size": 30}                           # % of the label's height (10..100)

Codes are made with segno at error correction level M (segno may raise it
when that costs no extra size). Every module is a whole number of printer
dots, at least MIN_MODULE_203 dots at 203 dpi (scaled for 300 dpi), with the
4-module quiet zone always left white, so codes are never blurred, dithered
or too small to scan. If the requested size can't give that, the label says
so instead of printing a code that won't scan.

Nothing here imports Tk.
"""
from __future__ import annotations

import re
from functools import lru_cache

from . import stocks, values

WHAT = {"link": "A website link", "phone": "My phone number", "email": "My email",
        "text": "Some text"}
PLACES = ["above", "bottom", "left", "right", "corner", "corner_right",
          "corner_bottom_left", "corner_bottom_right"]
SIZE_RANGE = (10, 100)
DEFAULTS = {"what": "link", "value": "", "caption": "", "place": "right", "size": 35}
MIN_MODULE_203 = 3            # smallest square, in 203 dpi dots (0.375 mm)
QUIET = 4                     # quiet zone around the code, in modules
MAX_VALUE = 1200              # characters, and at most this many bytes (UTF-8): any
                              # code this long fits a QR code (2331 bytes at level M)
TOO_SMALL = ("This is too much for a QR code this small — make it bigger or shorten "
             "the link.")


_int = values.to_int


def _text(v, limit: int) -> str:
    if v is None or v is False or isinstance(v, (dict, list)):
        return ""
    return values.text(str(v), limit)


def clean(value) -> dict | None:
    """A valid QR dict, or None. Never raises."""
    if not isinstance(value, dict):
        return None
    out = {"what": values.choice(value.get("what"), WHAT, "link"),
           "value": values.utf8_prefix(_text(value.get("value"), MAX_VALUE), MAX_VALUE),
           "caption": _text(value.get("caption"), 120),
           "place": values.choice(value.get("place"), PLACES, DEFAULTS["place"]),
           "size": _int(value.get("size"), *SIZE_RANGE, DEFAULTS["size"])}
    return out


def payload(qr: dict | None) -> str:
    """The text inside the code ("" = nothing to show)."""
    if not qr:
        return ""
    v = str(qr.get("value") or "").strip()
    if not v:
        return ""
    what = qr.get("what")
    if what == "phone":
        digits = re.sub(r"[^0-9+]", "", v)
        return f"tel:{digits}" if digits else ""
    if what == "email":
        v = v.removeprefix("mailto:")
        return f"mailto:{v}" if "@" in v else ""
    if what == "link":
        if re.match(r"^[a-z][a-z0-9+.-]*:", v, re.I):
            return v
        return "https://" + v.lstrip("/")
    return str(qr.get("value") or "").strip("\n")


@lru_cache(maxsize=64)
def _matrix(text: str) -> tuple:
    import segno
    q = segno.make(text, error="m", micro=False)
    return tuple(tuple(bool(x) for x in row) for row in q.matrix)


def matrix(text: str) -> list[list[bool]]:
    """The code's modules (no quiet zone) as rows of booleans."""
    return [list(r) for r in _matrix(text)]


def min_module(dpi: int) -> int:
    """Smallest allowed module in dots at this resolution."""
    return stocks.dots(MIN_MODULE_203, dpi)


def module_for(side: float, n: int, dpi: int) -> int:
    """Whole-dot module so a code of n modules plus the quiet zone fits ``side`` dots;
    0 if that would be smaller than the minimum."""
    m = int(side // (n + 2 * QUIET))
    return m if m >= min_module(dpi) else 0


def box_side(n: int, module: int) -> int:
    """Width (= height) of the code including its quiet zone, in dots."""
    return (n + 2 * QUIET) * module
