"""Words the main window shows that are worth testing without a window: the
text size choices, the short chips above the form ("Kind: Simple food label",
"Size: 4 × 2 in", "Picture: Our logo"), and the recent labels in Open ▾.

Nothing here imports Tk.
"""
from __future__ import annotations

from pathlib import Path

from . import lettering, qrcodes, stocks, templates

# ---------------------------------------------------------------------------
# text size
# ---------------------------------------------------------------------------

# Every step A− / A+ can reach. 0.9 and 1.1 stay, so a size someone picked
# before is kept exactly.
SCALES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.7]

# The four plain choices in Settings → Text size: (id, words, scale).
# "Large" is the size that was the default before 1.5.0.
TEXT_SIZES = [("small", "Small", 0.7), ("normal", "Normal", 0.8),
              ("large", "Large", 1.0), ("xl", "Extra large", 1.2)]
DEFAULT_SCALE = 0.8          # Normal, for new installs
OLD_DEFAULT_SCALE = 1.0      # what a settings file without a size had


def nearest_scale(scale) -> float:
    """The SCALES step closest to ``scale`` (anything unreadable: Normal)."""
    try:
        s = float(scale)
    except (TypeError, ValueError):
        s = DEFAULT_SCALE
    return min(SCALES, key=lambda x: (abs(x - s), -x))


def step_scale(scale, step: int) -> float:
    """One step smaller (-1) or bigger (+1), stopping at the ends."""
    i = SCALES.index(nearest_scale(scale)) + int(step)
    return SCALES[max(0, min(len(SCALES) - 1, i))]


def text_size_id(scale) -> str:
    """The Settings choice closest to ``scale`` ("small", "normal", "large", "xl")."""
    s = nearest_scale(scale)
    return min(TEXT_SIZES, key=lambda t: (abs(t[2] - s), -t[2]))[0]


def scale_for(size_id: str) -> float:
    """The scale of a Settings choice (unknown: Normal)."""
    return next((s for i, _w, s in TEXT_SIZES if i == size_id), DEFAULT_SCALE)


def text_size_words(scale) -> str:
    """"Normal", or "Normal (a little bigger)" when A+ went between two choices."""
    s = nearest_scale(scale)
    sid = text_size_id(s)
    base = scale_for(sid)
    name = next(w for i, w, _s in TEXT_SIZES if i == sid)
    if abs(s - base) < 1e-6:
        return name
    return f"{name} (a little {'bigger' if s > base else 'smaller'})"


# ---------------------------------------------------------------------------
# chips above the form
# ---------------------------------------------------------------------------

SHORT_SIZES = {"small": "Small sticker", "medium": "3 × 2 in", "large": "4 × 2 in",
               "round": "2 in round", "xl": "4 × 6 in"}


def shorten(text, n: int) -> str:
    """At most ``n`` characters, with … when cut. One line."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: max(1, n - 1)].rstrip() + "…"


def kind_chip(template: str) -> str:
    name = templates.TEMPLATE_INFO.get(template, ("Label", ""))[0]
    return f"Kind: {name}"


def size_words(stock_id: str) -> str:
    """"4 × 2 in": the roll's size, short."""
    if stock_id in SHORT_SIZES:
        return SHORT_SIZES[stock_id]
    return stocks.get(stock_id).size_inches


def size_chip(stock_id: str) -> str:
    return f"Size: {size_words(stock_id)}"


def picture_chip(picture) -> str:
    """"+ Picture" when there is none, else "Picture: Our logo"."""
    if not picture:
        return "+ Picture"
    return "Picture: " + shorten(picture.get("name") or "yes", 18)


QR_SHORT = {"link": "Website", "phone": "Phone", "email": "Email", "text": "Text"}


def qr_chip(qr) -> str:
    """"+ QR code" when there is none, else "QR code: Website" (what it holds)."""
    q = qrcodes.clean(qr)
    if not qrcodes.payload(q):
        return "+ QR code"
    return "QR code: " + QR_SHORT.get(q["what"], "Yes")


def lettering_summary(template: str, value) -> str:
    """"Standard" or "Pacifico · Lato" (a font this computer hasn't got says so)."""
    lt = lettering.clean(value)
    if lettering.is_default(lt):
        return "Standard"
    name = lt.get("name", lettering.DEFAULT)
    other = lt.get("other", lettering.DEFAULT)
    parts = [name] if template in ("free", "picture") or other == name else [name, other]
    missing = set(lettering.missing(lt))
    return " · ".join(p + (" (not on this computer)" if p in missing else "") for p in parts)


def lettering_chip(template: str, value) -> str:
    return "Lettering: " + shorten(lettering_summary(template, value), 30)


# ---------------------------------------------------------------------------
# Open ▾
# ---------------------------------------------------------------------------

MAX_OPEN_MENU = 8


def recent_menu(recent: list[dict], n: int = MAX_OPEN_MENU) -> list[tuple[str, str]]:
    """[(words, path)] for the recent labels in Open ▾, newest first. Two labels
    with the same name say which folder each is in."""
    items = []
    for r in recent[:n]:
        path = str(r.get("path") or "")
        if not path:
            continue
        name = shorten(r.get("name") or Path(path).stem, 40)
        items.append((name, path))
    names = [w for w, _p in items]
    out = []
    for words, path in items:
        if names.count(words) > 1:
            words = f"{words}  (in {Path(path).parent.name})"
        out.append((words, path))
    return out
