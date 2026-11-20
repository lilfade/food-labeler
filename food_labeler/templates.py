"""Label layouts and the auto-fit layout engine.

Every template turns the label document into a list of text Blocks. The engine
then finds the biggest font sizes that fit: blocks start at their preferred size
and shrink together, step by step, but never below their minimum. If the text
still doesn't fit we say so (and which field is the culprit) instead of cutting
anything off. Wrapping uses real Pillow measurements of the bundled font.

Sizes are in printer dots (203 dpi), so a 24-dot font is 3 mm tall on paper.
Round labels lay text out inside a circle: every line gets the width of the
circle at its height (Region.span), so lines near the top and bottom are
shorter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from . import dates, stocks

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

TOO_MUCH = ("This is too much writing for this label size — "
            "try a bigger label or shorter words.")

TEMPLATE_INFO = {
    "simple": ("Simple food label", "Food name, dates, allergens"),
    "package": ("Package label", "Ingredients, weight, kitchen details"),
    "sticker": ("Date sticker", "Lot number and dates"),
    "free": ("Free text", "Just type what you want"),
}

# Templates that need room: package label doesn't fit Small or Round.
ALLOWED_STOCKS = {
    "simple": stocks.ORDER,
    "package": ["medium", "large", "xl"],
    "sticker": stocks.ORDER,
    "free": stocks.ORDER,
}

# Friendly names for fields (used in "too much writing" messages).
FIELD_NAMES = {
    "food": "food name", "made_on": "Made on", "use_by": "Use by", "contains": "Contains",
    "note": "note", "made_by": "Made by", "kitchen": "kitchen name",
    "product": "product name", "net": "net weight", "ingredients": "ingredients",
    "cross_contact": "cross-contact notice", "lot": "lot", "best_by": "Best by",
    "business": "business name", "address": "address", "disclaimer": "disclaimer",
    "qr": "QR code", "made": "Made", "count": "count", "text": "writing",
}


@lru_cache(maxsize=512)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """The bundled DejaVu Sans at ``size`` dots (cached; fitting asks for many sizes)."""
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), max(4, int(size)))


@lru_cache(maxsize=512)
def line_height(size: int, bold: bool = False) -> int:
    """Distance between baselines of wrapped lines: ascent + descent."""
    asc, desc = font(size, bold).getmetrics()
    return asc + desc


def text_width(text: str, size: int, bold: bool = False) -> float:
    """Advance width of ``text`` in dots."""
    return font(size, bold).getlength(text)


@dataclass
class Block:
    """One field's text before fitting. pref/min are font sizes in dots."""
    key: str
    text: str
    pref: float
    min: int
    bold: bool = False
    align: str = "center"
    gap: float = 0.28              # space before the block, as a fraction of its size
    fit_word: bool = False         # shrink this block alone so its longest word fits


@dataclass
class Line:
    """One placed line of text: top-left corner in dots, font size, source field."""
    text: str
    x: float
    y: float
    size: int
    bold: bool
    key: str


@dataclass
class Layout:
    """Result of fitting. If overflow is set, lines are a best effort at minimum
    size and message/overflow_key say what is too long."""
    lines: list = field(default_factory=list)
    qr: tuple | None = None        # (x, y, module_px, segno matrix rows)
    overflow: bool = False
    overflow_key: str = ""
    message: str = ""


class Region:
    """Where text may go: a rectangle, optionally a circle, minus exclusions."""

    def __init__(self, left, top, right, bottom, circle=None):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom
        self.circle = circle          # (cx, cy, r) or None
        self.exclusions = []          # list of (x0, y0, x1, y1)

    @property
    def height(self):
        return self.bottom - self.top

    @property
    def full_width(self):
        return self.right - self.left

    def span(self, y0: float, y1: float) -> tuple[float, float]:
        """Usable (left, right) x range for a line occupying y0..y1.

        For a circle we use the half-width at whichever edge of the line is
        further from the centre, so no part of the text pokes outside.
        """
        xl, xr = self.left, self.right
        if self.circle:
            cx, cy, r = self.circle
            dy = max(abs(y0 - cy), abs(y1 - cy))
            if dy >= r:
                return (cx, cx)
            hw = math.sqrt(r * r - dy * dy)
            xl, xr = max(xl, cx - hw), min(xr, cx + hw)
        for (ex0, ey0, ex1, ey1) in self.exclusions:
            if y1 > ey0 and y0 < ey1:
                # exclusion on the right side cuts the right edge, on the left the left edge
                if ex0 > (self.left + self.right) / 2:
                    xr = min(xr, ex0)
                else:
                    xl = max(xl, ex1)
        return (xl, max(xl, xr))


def region_for(stock: stocks.Stock) -> Region:
    """The text area of a label: inside the margins, or inside the printable circle."""
    m = stock.margin
    if stock.round:
        cx, cy = stock.circle_center
        r = stock.circle_dia / 2.0 - 14       # stay well inside the printable circle
        return Region(cx - r, cy - r, cx + r, cy + r, circle=(cx, cy, r))
    return Region(m, m, stock.w - m, stock.h - m)


# --------------------------------------------------------------------------
# wrapping
# --------------------------------------------------------------------------

def _break_word(word: str, size: int, bold: bool, width: float) -> list[str]:
    parts, cur = [], ""
    for ch in word:
        if cur and text_width(cur + ch, size, bold) > width:
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts


def wrap(text: str, size: int, bold: bool, width_for_line, allow_break=False):
    """Greedy wrap. width_for_line(i) gives the allowed width of line i.

    Returns (lines, ok). ok is False if a single word is wider than its line
    (and allow_break is False) — then the caller should shrink the text.
    """
    out: list[str] = []
    ok = True
    for para in str(text).split("\n"):
        words = [w for w in para.split(" ") if w.strip()]
        if not words:
            continue
        cur = ""
        for w in words:
            trial = f"{cur} {w}" if cur else w
            width = width_for_line(len(out))
            if text_width(trial, size, bold) <= width:
                cur = trial
                continue
            if cur:
                out.append(cur)
                cur = ""
                width = width_for_line(len(out))
            if text_width(w, size, bold) <= width:
                cur = w
            else:
                ok = False
                if not allow_break:
                    cur = w
                    continue
                pieces = _break_word(w, size, bold, max(1.0, width))
                out.extend(pieces[:-1])
                cur = pieces[-1]
        if cur:
            out.append(cur)
    return out, ok


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------

def _try(blocks, sizes, region: Region, valign: str, allow_break=False):
    """Lay out blocks at the given sizes. Returns (lines, ok, heights per block)."""
    shaped = region.circle is not None or bool(region.exclusions)
    mid = (region.top + region.bottom) / 2
    top = None                      # unknown on the first pass: assume the middle
    # On a shaped region the width of each line depends on where it ends up,
    # which depends on the total height (vertical centring), which depends on
    # how the text wrapped. Iterate until the top edge stops moving; for a
    # plain rectangle one pass is exact.
    for _ in range(6):
        placed, heights, ok, y = [], [], True, 0.0
        for bi, (b, size) in enumerate(zip(blocks, sizes)):
            lh = line_height(size, b.bold)
            if placed:
                y += b.gap * size
            start = y

            def wf(i, start=start, lh=lh):
                if top is None:
                    xl, xr = region.span(mid - lh / 2, mid + lh / 2)
                else:
                    yy = top + start + i * lh
                    xl, xr = region.span(yy, yy + lh)
                return xr - xl

            wrapped, wok = wrap(b.text, size, b.bold, wf, allow_break)
            ok = ok and wok
            for i, t in enumerate(wrapped):
                placed.append((bi, t, start + i * lh, size, lh))
            y = start + len(wrapped) * lh
            heights.append(len(wrapped) * lh)
        total = y
        new_top = region.top + (region.height - total) / 2 if valign == "center" else region.top
        new_top = max(region.top, new_top)
        done = (not shaped) or (top is not None and abs(new_top - top) < 0.5)
        top = new_top
        if done:
            break
    fits = total <= region.height + 0.5
    out = []
    for (bi, t, ly, size, lh) in placed:
        b = blocks[bi]
        yy = top + ly
        xl, xr = region.span(yy, yy + lh)
        w = text_width(t, size, b.bold)
        if w > xr - xl + 0.5:
            ok = False
        x = xl if b.align == "left" else xl + (xr - xl - w) / 2
        out.append(Line(t, round(x), round(yy), size, b.bold, b.key))
    return out, ok and fits, heights


def fit(blocks: list[Block], region: Region, valign: str = "center") -> Layout:
    """Find the biggest common scale at which all non-empty blocks fit ``region``.

    1. Headline blocks (fit_word) first shrink alone until their longest word
       fits on one line, so a long food name never gets broken mid-word.
    2. Then every block is scaled by the same factor, 6% at a time, each one
       clamped at its own minimum size, until everything fits.
    3. A short binary search between the last failing and the first fitting
       scale recovers the size lost to the coarse 6% steps.
    4. If it still doesn't fit with every block at its minimum, return an
       overflow Layout naming the tallest block, so the UI can point at it.
    """
    blocks = [b for b in blocks if str(b.text).strip()]
    if not blocks:
        return Layout()
    # Headline blocks first shrink on their own so their longest word fits a line.
    prefs = []
    mid = (region.top + region.bottom) / 2
    for b in blocks:
        p = float(b.pref)
        if b.fit_word:
            longest = max(str(b.text).split(), key=lambda w: text_width(w, int(p), b.bold))
            for _ in range(60):
                xl, xr = region.span(mid - p * 0.6, mid + p * 0.6)
                if p <= b.min or text_width(longest, int(p), b.bold) <= (xr - xl):
                    break
                p *= 0.95
        prefs.append(max(b.min, p))

    def attempt(scale):
        sizes = [max(b.min, int(round(p * scale))) for b, p in zip(blocks, prefs)]
        lines, ok, _ = _try(blocks, sizes, region, valign)
        return lines, ok, all(s <= b.min for s, b in zip(sizes, blocks))

    scale = 1.0
    while True:
        lines, ok, at_min = attempt(scale)
        if ok:
            if scale < 1.0:
                # refine: biggest scale between this step and the previous one that fits
                lo, hi = scale, min(1.0, scale / 0.94)
                for _ in range(5):
                    m = (lo + hi) / 2
                    l2, ok2, _ = attempt(m)
                    if ok2:
                        lo, lines = m, l2
                    else:
                        hi = m
            return Layout(lines=lines)
        if at_min:
            break
        scale *= 0.94

    # Still too much at the smallest sizes: report it, and say which field.
    sizes = [b.min for b in blocks]
    lines, _, heights = _try(blocks, sizes, region, "top", allow_break=True)
    worst = max(range(len(blocks)), key=lambda i: heights[i] if blocks[i].key else -1)
    return Layout(lines=lines, overflow=True, overflow_key=blocks[worst].key, message=TOO_MUCH)


# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------

def _base(region: Region) -> float:
    return min(region.height, region.full_width * 0.9)


def _s(v) -> str:
    return str(v or "").strip()


def build_blocks(doc, stock: stocks.Stock, ctx: dict) -> tuple[list[Block], str, str]:
    """Return (blocks, vertical alignment, qr text) for this document.

    Preferred sizes are fractions of the region's size (``base``), so the
    same template scales from a 32 mm sticker up to 4 x 6 in.
    Block args: key, text, pref, min, bold, align, gap, fit_word.
    """
    f = doc.fields
    region = region_for(stock)
    base = _base(region)
    style = ctx.get("date_style", "us")
    small = stock.w < 400
    mn = 12 if small else 13

    if doc.template == "package":
        best = dates.fmt(dates.parse(f.get("best_by")), "dmy")
        lot = _s(f.get("lot"))
        lotline = "\u2002\u2002".join(x for x in [f"Lot {lot}" if lot else "",
                                         f"Best by {best}" if best else ""] if x)
        net = _s(f.get("net"))
        ingr = _s(f.get("ingredients"))
        contains = _s(f.get("contains"))
        blocks = [
            Block("product", _s(f.get("product")), base * 0.2, 20, True, "center", 0, True),
            Block("net", f"Net {net}" if net else "", base * 0.09, mn, False, "center", 0.15),
            Block("ingredients", f"INGREDIENTS: {ingr}" if ingr else "", base * 0.078, mn, False, "left", 0.45),
            Block("contains", f"CONTAINS: {contains}" if contains else "", base * 0.078, mn, True, "left", 0.3),
            Block("cross_contact", _s(f.get("cross_contact")), base * 0.062, 12, False, "left", 0.3),
            Block("lot", lotline, base * 0.075, mn, True, "left", 0.45),
            Block("business", _s(f.get("business")), base * 0.075, mn, True, "left", 0.45),
            Block("address", _s(f.get("address")), base * 0.065, 12, False, "left", 0.1),
            Block("disclaimer", _s(f.get("disclaimer")), base * 0.056, 12, False, "left", 0.4),
        ]
        return blocks, "top", _s(f.get("qr"))

    if doc.template == "sticker":
        made = dates.fmt(dates.parse(f.get("made")), "mdy_short")
        best = dates.fmt(dates.parse(f.get("best_by")), "mdy_short")
        lot, count = _s(f.get("lot")), _s(f.get("count"))
        blocks = [
            Block("lot", f"LOT {lot}" if lot else "", base * 0.21, mn, True, "center", 0, True),
            Block("made", f"MADE {made}" if made else "", base * 0.17, mn, False, "center", 0.25),
            Block("best_by", f"BEST BY {best}" if best else "", base * 0.17, mn, True, "center", 0.25),
            Block("count", f"COUNT {count}" if count else "", base * 0.15, mn, False, "center", 0.25),
        ]
        return blocks, "center", ""

    if doc.template == "free":
        return [Block("text", str(f.get("text") or "").strip("\n"), base * 0.22, 14, True,
                      "center", 0, True)], "center", ""

    # simple food label
    made = dates.fmt(dates.parse(f.get("made_on")), style)
    use = dates.fmt(dates.parse(f.get("use_by")), style)
    contains = _s(f.get("contains"))
    made_by = _s(f.get("made_by"))
    kitchen = _s(ctx.get("kitchen_name")) if f.get("kitchen") else ""
    blocks = [
        Block("food", _s(f.get("food")), base * 0.26, 22, True, "center", 0, True),
        Block("made_on", f"Made on {made}" if made else "", base * 0.115, mn, False, "center", 0.35),
        Block("use_by", f"Use by {use}" if use else "", base * 0.14, mn + 1, True, "center", 0.2),
        Block("contains", f"Contains: {contains}" if contains else "", base * 0.10, mn, True, "center", 0.3),
        Block("note", _s(f.get("note")), base * 0.10, mn, False, "center", 0.25),
        Block("made_by", f"Made by {made_by}" if made_by else "", base * 0.09, mn, False, "center", 0.25),
        Block("kitchen", kitchen, base * 0.085, mn, False, "center", 0.25),
    ]
    return blocks, "center", ""


def qr_matrix(text: str):
    """QR code modules as rows of booleans (segno is imported only when needed)."""
    import segno
    q = segno.make(text, error="m", micro=False)
    return [list(row) for row in q.matrix]


def layout(doc, stock: stocks.Stock, ctx: dict | None = None) -> Layout:
    """Fit a document onto a stock. A QR code (package labels, 3 in and wider)
    goes top-right, and the text flows around it via a region exclusion."""
    ctx = ctx or {}
    blocks, valign, qr_text = build_blocks(doc, stock, ctx)
    region = region_for(stock)
    qr = None
    if qr_text and not stock.round and stock.w >= 600:
        matrix = qr_matrix(qr_text)
        n = len(matrix)
        target = min(region.height * 0.42, 200)
        module = max(2, int(target // n))
        side = module * n
        qx = region.right - side
        qy = region.top
        qr = (qx, qy, module, matrix)
        region.exclusions.append((qx - 16, qy, region.right, qy + side + 8))
    out = fit(blocks, region, valign)
    out.qr = qr
    return out
