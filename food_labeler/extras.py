"""Placing a picture and/or a QR code on a label, with the text flowing around them.

Used by templates.layout() when a label has a picture or a QR code, and for
the Picture label (one big picture, optional words under it).

Plain-word placements (pictures.PLACES): *Above the name* takes a band across
the top and *Below the writing* one across the bottom; *Left side* / *Right
side* take a column the height of the text area; the four corners take just
their own box, so the text flows beside and then under (or over) them.
Several things in the same place sit side by side (bands) or one under the
other (sides); a corner and a column on the same side share one column, so
nothing overlaps. On round labels things go across the top or the bottom of
the circle, kept inside it.

The wording wins: templates.fit() first shrinks the text as usual (never
below each block's minimum, so the state's required wording keeps its size);
only if that is not enough are the picture and QR code made smaller, 15 % at
a time, down to a readable minimum (a picture 6 mm tall, QR squares of 3 dots
at 203 dpi). If it still doesn't fit, the label says so and names the
picture (or QR code) as the thing to make smaller.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from . import pictures, qrcodes, stocks
from .templates import Layout, Line, Region, fit, line_height, region_for, wrap

ROOM = ("There isn't room for the {thing} and all the writing. Make the {thing} smaller, "
        "use fewer words, or pick a bigger label.")
MIN_PICTURE_203 = 48            # smallest picture height, 203 dpi dots (6 mm)
SHRINK = 0.85


def has_extras(doc) -> bool:
    """Does this label have a usable picture or QR code?"""
    if pictures.clean(getattr(doc, "picture", None)):
        return True
    return bool(qrcodes.payload(qrcodes.clean(getattr(doc, "qr", None))))


@dataclass
class Item:
    """Something placed on the label (picture or QR code), sizes in dots."""
    kind: str                     # "picture" | "qr"
    place: str
    w: float
    h: float
    x: float = 0.0
    y: float = 0.0
    module: int = 0               # QR only
    n: int = 0                    # QR modules per side (no quiet zone)
    caption: list = field(default_factory=list)   # QR caption lines
    cap_size: int = 0
    too_small: bool = False

    def scale(self, k: float, stock: stocks.Stock) -> None:
        """Make it k times as big (QR codes: whole-dot squares, never below the minimum)."""
        if self.kind == "qr":
            m = int(self.module * k)
            if m < qrcodes.min_module(stock.dpi):
                self.too_small = True
                m = qrcodes.min_module(stock.dpi)
            self.module = m
            side = qrcodes.box_side(self.n, m)
            self.w = side
            self.h = side + self.caption_height()
        else:
            self.w *= k
            self.h *= k

    def caption_height(self) -> int:
        if not self.caption:
            return 0
        return len(self.caption) * line_height(self.cap_size)


def _picture_item(pic: dict, stock, region: Region, k: float) -> Item:
    h = region.height * pic["size"] / 100.0 * k
    return Item("picture", pic["place"], h * pictures.aspect(pic), h)


def _qr_item(qr: dict, text: str, stock, module: int) -> Item:
    n = len(qrcodes.matrix(text))
    side = qrcodes.box_side(n, module)
    it = Item("qr", qr["place"], side, side, module=module, n=n)
    cap = str(qr.get("caption") or "").strip()
    if cap:
        it.cap_size = max(stock.d(12), min(stock.d(18), int(side * 0.09)))
        it.caption, _ok = wrap(cap, it.cap_size, False, lambda i: side, allow_break=True)
        it.caption = it.caption[:3]
        it.h = side + it.caption_height()
    return it


def _fit_in_circle(region: Region, half_w: float, h: float):
    """Top y for a band half_w wide (each side of the centre) and h tall at the top of
    the circle, or None if it can't fit."""
    cx, cy, r = region.circle
    if half_w >= r:
        return None
    y0 = cy - math.sqrt(r * r - half_w * half_w)
    yb = y0 + h
    if abs(yb - cy) >= r or math.hypot(half_w, yb - cy) > r:
        return None
    return y0


# Where each placement goes: a band across the top or the bottom, or a side
# ("left"/"right") at the top, in the middle (a column) or at the bottom.
SIDES = {"corner": ("left", "top"), "left": ("left", "column"),
         "corner_bottom_left": ("left", "bottom"),
         "corner_right": ("right", "top"), "right": ("right", "column"),
         "corner_bottom_right": ("right", "bottom")}
BOTTOM_PLACES = ("bottom", "corner_bottom_left", "corner_bottom_right")


def where(place: str, stock: stocks.Stock) -> str:
    """The placement actually used on this label: on round labels only across the
    top ("above") or the bottom of the circle; the Picture label's own "fill"/"fit"
    count as above."""
    if place in ("fill", "fit"):
        return "above"
    if stock.round:
        return "bottom" if place in BOTTOM_PLACES else "above"
    return place if place in SIDES or place in ("above", "bottom") else "above"


def _band(its: list[Item], stock: stocks.Stock, region: Region, gap: float,
          at_bottom: bool) -> None:
    """Items side by side across the top (or the bottom) of the text area."""
    for _ in range(40):
        total = sum(i.w for i in its) + gap * (len(its) - 1)
        band = max(i.h for i in its)
        if total > region.full_width:
            k = region.full_width / total
        elif band > region.height:
            k = region.height / band
        elif region.circle is not None and _fit_in_circle(region, total / 2, band) is None:
            k = 0.95
        else:
            break
        for i in its:
            i.scale(k, stock)
    total = sum(i.w for i in its) + gap * (len(its) - 1)
    band = max(i.h for i in its)
    if at_bottom:
        y0 = region.bottom - band
        if region.circle is not None:
            top = _fit_in_circle(region, total / 2, band)
            if top is not None:            # the top band's mirror image
                y0 = 2 * region.circle[1] - (top + band)
    else:
        y0 = region.top
        if region.circle is not None:
            y0 = _fit_in_circle(region, total / 2, band) or region.top
    x = (region.left + region.right) / 2 - total / 2
    for i in its:
        i.x = x
        i.y = y0 + (band - i.h if at_bottom else 0)
        x += i.w + gap
    if at_bottom:
        region.bottom = y0 - gap
    else:
        region.top = y0 + band + gap


def _side(its: list[tuple[str, Item]], side: str, stock: stocks.Stock, region: Region,
          gap: float) -> None:
    """Items down one side: corners at the top or bottom, columns in the middle.

    With only corners, the text flows beside a corner and then under (or over)
    it. As soon as there is a column, the whole side is one column of the text
    area's height, so a corner and a column on the same side never overlap."""
    items = [i for _r, i in its]
    maxw = region.full_width * 0.45
    for _ in range(40):
        colw = max(i.w for i in items)
        total = sum(i.h for i in items) + gap * (len(items) - 1)
        if colw > maxw:
            k = maxw / colw
        elif total > region.height:
            k = region.height / total
        else:
            break
        for i in items:
            i.scale(k, stock)
    colw = max(i.w for i in items)
    tops = [i for r, i in its if r == "top"]
    cols = [i for r, i in its if r == "column"]
    bots = [i for r, i in its if r == "bottom"]
    y = region.top
    for i in tops:
        i.y = y
        y += i.h + gap
    top_limit = y                          # under the top corner (and its gap)
    y = region.bottom
    for i in reversed(bots):
        y -= i.h
        i.y = y
        y -= gap
    bottom_limit = y                       # over the bottom corner (and its gap)
    if cols:
        total = sum(i.h for i in cols) + gap * (len(cols) - 1)
        y = top_limit + (bottom_limit - top_limit - total) / 2
        for i in cols:
            i.y = y
            y += i.h + gap
    for i in items:
        i.x = region.left if side == "left" else region.right - i.w
    if cols:
        spans = [(region.top, region.bottom)]
    else:
        spans = ([(region.top, top_limit)] if tops else []) + \
                ([(bottom_limit, region.bottom)] if bots else [])
    for ey0, ey1 in spans:
        if side == "left":
            region.exclusions.append((region.left, ey0, region.left + colw + gap, ey1))
        else:
            region.exclusions.append((region.right - colw - gap, ey0, region.right, ey1))


def arrange(items: list[Item], stock: stocks.Stock, region: Region) -> None:
    """Give items their positions and take their space out of ``region``.

    The bands across the top and the bottom come first, then the sides inside
    what is left, so nothing is ever placed on top of anything else."""
    gap = stock.d(12)
    above = [i for i in items if where(i.place, stock) == "above"]
    below = [i for i in items if where(i.place, stock) == "bottom"]
    if above:
        _band(above, stock, region, gap, at_bottom=False)
    if below:
        _band(below, stock, region, gap, at_bottom=True)
    for side in ("left", "right"):
        its = [(SIDES[where(i.place, stock)][1], i) for i in items
               if SIDES.get(where(i.place, stock), ("",))[0] == side]
        if its:
            _side(its, side, stock, region, gap)


def _circle_mask(img: Image.Image, x: int, y: int, region: Region) -> Image.Image:
    """Keep a picture inside the round label's circle (outside it = paper)."""
    cx, cy, r = region.circle
    mask = Image.new("1", img.size, 0)
    ImageDraw.Draw(mask).ellipse((cx - r - x, cy - r - y, cx + r - x, cy + r - y), fill=1)
    out = Image.new("1", img.size, 1)
    out.paste(img, (0, 0), mask)
    return out


def _attach(out: Layout, items: list[Item], pic: dict | None, qr_text: str,
            circle_region: Region | None) -> None:
    """Put the placed items into the Layout (pictures, QR code, caption lines)."""
    for it in items:
        x, y = int(round(it.x)), int(round(it.y))
        if it.kind == "picture":
            w, h = max(1, int(round(it.w))), max(1, int(round(it.h)))
            img = pictures.to_print(pic, w, h)
            if circle_region is not None and circle_region.circle is not None:
                img = _circle_mask(img, x, y, circle_region)
            out.images.append((x, y, img))
        else:
            q = qrcodes.QUIET * it.module
            side = qrcodes.box_side(it.n, it.module)
            out.qr = (x + q, y + q, it.module, qrcodes.matrix(qr_text))
            out.qr_box = (x, y, x + side, y + side)
            ly = y + side
            for t in it.caption:
                from .templates import text_width
                tw = text_width(t, it.cap_size)
                out.lines.append(Line(t, int(round(x + (side - tw) / 2)), ly, it.cap_size,
                                      False, "qr"))
                ly += line_height(it.cap_size)


def _usable(doc):
    pic = pictures.clean(getattr(doc, "picture", None))
    if pic and pictures.decode(pic) is None:
        pic = None
    qr = qrcodes.clean(getattr(doc, "qr", None))
    text = qrcodes.payload(qr)
    return pic, qr, text


def _qr_start(qr, text, stock, region) -> int:
    """Requested QR module size in dots (0 = can't be made big enough to scan)."""
    n = len(qrcodes.matrix(text))
    return qrcodes.module_for(region.height * qr["size"] / 100.0, n, stock.dpi)


def layout_with_extras(doc, stock: stocks.Stock, blocks, valign) -> Layout:
    """templates.layout() for labels with a picture and/or a QR code."""
    pic, qr, text = _usable(doc)
    if doc.template == "picture":
        return _picture_label(doc, stock, blocks, pic, qr, text)
    base = region_for(stock)
    module0 = _qr_start(qr, text, stock, base) if text else 0
    if text and not module0:
        lay = fit(blocks, region_for(stock), valign)
        return Layout(lines=lay.lines, overflow=True, overflow_key="qr",
                      message=qrcodes.TOO_SMALL)
    min_pic = stock.d(MIN_PICTURE_203)
    k = 1.0
    while True:
        items = []
        if pic:
            items.append(_picture_item(pic, stock, base, k))
        if text:
            items.append(_qr_item(qr, text, stock, max(qrcodes.min_module(stock.dpi),
                                                        int(module0 * k))))
        region = region_for(stock)
        arrange(items, stock, region)
        out = fit(blocks, region, valign)
        if not out.overflow:
            break
        pic_room = pic is not None and items[0].h * SHRINK >= min_pic
        qr_room = bool(text) and items[-1].module > qrcodes.min_module(stock.dpi)
        if not (pic_room or qr_room) or k < 0.02:
            break
        k *= SHRINK
    if any(it.kind == "qr" and it.too_small for it in items):
        out.overflow, out.overflow_key, out.message = True, "qr", qrcodes.TOO_SMALL
    elif out.overflow and not fit(blocks, region_for(stock), valign).overflow:
        thing = "picture" if pic else "QR code"
        out.overflow_key = "picture" if pic else "qr"
        out.message = ROOM.format(thing=thing)
    _attach(out, items, pic, text, region_for(stock) if stock.round else None)
    return out


# ---------------------------------------------------------------------------
# the Picture label
# ---------------------------------------------------------------------------

def _inside(region: Region, x0, y0, x1, y1) -> bool:
    if region.circle is None:
        return True
    cx, cy, r = region.circle
    return all(math.hypot(x - cx, y - cy) <= r + 0.5 for x, y in
               ((x0, y0), (x1, y0), (x0, y1), (x1, y1)))


def _picture_label(doc, stock, blocks, pic, qr, text) -> Layout:
    """One big picture ("Fill the label" or "Fit inside"), words under it, optional QR."""
    region = region_for(stock)
    gap = stock.d(12)
    items = []
    if text:
        module0 = _qr_start(qr, text, stock, region)
        if not module0:
            return Layout(overflow=True, overflow_key="qr", message=qrcodes.TOO_SMALL)
        it = _qr_item(qr, text, stock, module0)
        if not stock.round:          # in a picture label a QR code takes a whole side
            it.place = {"corner": "left", "corner_right": "right", "corner_bottom_left": "left",
                        "corner_bottom_right": "right"}.get(it.place, it.place)
        items.append(it)
        arrange(items, stock, region)
    out = Layout()
    words = [b for b in blocks if str(b.text).strip()]
    bottom = region.bottom
    if words:
        band = region.height * 0.28
        tr = Region(region.left, region.bottom - band, region.right, region.bottom,
                    circle=region.circle)
        tr.exclusions = list(region.exclusions)
        out = fit(words, tr, "center")
        if out.overflow:
            out.message = ("These words don't fit under the picture. Use fewer words or a "
                           "bigger label.")
        bottom = region.bottom - band - gap / 2
    # the area left for the picture
    left, right, top = region.left, region.right, region.top
    for (ex0, _ey0, ex1, _ey1) in region.exclusions:
        if ex0 > (region.left + region.right) / 2:
            right = min(right, ex0)
        else:
            left = max(left, ex1)
    if pic and bottom - top > 4 and right - left > 4:
        aw, ah = right - left, bottom - top
        a = pictures.aspect(pic)
        if pic["place"] == "fill":
            if stock.round:
                cx, cy, r = region.circle
                left, right = max(left, cx - r), min(right, cx + r)
                aw = right - left
            # cover the whole area, cut off what sticks out (centred)
            k = max(aw / a, ah)
            cw, ch = max(1, int(math.ceil(k * a))), max(1, int(math.ceil(k)))
            big = pictures.to_print(pic, cw, ch)
            ox, oy = (cw - int(aw)) // 2, (ch - int(ah)) // 2
            img = big.crop((ox, oy, ox + int(aw), oy + int(ah)))
            x, y = int(round(left)), int(round(top))
        else:
            h = min(ah, aw / a) * pic["size"] / 100.0
            cx, cy = (left + right) / 2, (top + bottom) / 2
            for _ in range(60):          # round labels: shrink until the corners are inside
                w = h * a
                if _inside(region, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2):
                    break
                h *= 0.97
            w = h * a
            x, y = int(round(cx - w / 2)), int(round(cy - h / 2))
            img = pictures.to_print(pic, max(1, int(round(w))), max(1, int(round(h))))
        if stock.round:
            img = _circle_mask(img, x, y, region_for(stock))
        out.images.append((x, y, img))
    if any(it.too_small for it in items):
        out.overflow, out.overflow_key, out.message = True, "qr", qrcodes.TOO_SMALL
    _attach(out, items, None, text, None)
    return out


# ---------------------------------------------------------------------------
# how big a QR code may be (the "How big?" slider)
# ---------------------------------------------------------------------------

MAX_QR_WITH_WORDS = 60          # % of the text area's height when there is writing too


def _has_words(doc, stock, ctx) -> bool:
    from . import templates
    blocks, _valign, _qr = templates.build_blocks(doc, stock, ctx or {})
    return any(str(b.text).strip() for b in blocks)


def qr_size_range(doc, stock: stocks.Stock, ctx: dict | None = None):
    """(smallest, biggest) size for the label's QR code, in the slider's % of the
    text area's height, or None when what it holds is too much for this label.

    Smallest: the first size whose squares are at least the readable minimum
    (qrcodes.min_module) for what the code holds, at this label size and
    printer resolution, and that the layout doesn't have to shrink. Biggest:
    the last size at which the code still prints at the size asked for and
    everything else on the label still fits (the wording is never made smaller
    than its minimum to make room). With writing on the label the code also
    stays under MAX_QR_WITH_WORDS %, so it never takes over the label; a QR
    code alone, or on the Picture label, may fill the label inside its margins.
    """
    from . import templates
    qr = qrcodes.clean(getattr(doc, "qr", None))
    text = qrcodes.payload(qr)
    if not text:
        return (qrcodes.SIZE_RANGE[0], qrcodes.SIZE_RANGE[1])
    n = len(qrcodes.matrix(text))
    region = region_for(stock)
    need = qrcodes.box_side(n, qrcodes.min_module(stock.dpi))
    lo = max(qrcodes.SIZE_RANGE[0], math.ceil(100.0 * need / region.height - 1e-9))
    while lo <= 100 and not qrcodes.module_for(region.height * lo / 100.0, n, stock.dpi):
        lo += 1                                     # rounding: the first size that works
    if lo > 100:
        return None

    def works(size, strict=True) -> bool:
        d = doc.copy()
        d.qr = dict(qr, size=size)
        lay = templates.layout(d, stock, ctx or {})
        want = qrcodes.module_for(region.height * size / 100.0, n, stock.dpi)
        if not want or lay.qr is None or lay.qr[2] < want:
            return False                            # shrunk to make room, or refused
        if lay.overflow and lay.message == qrcodes.TOO_SMALL:
            return False                            # had to be shrunk below readable
        return not (strict and lay.overflow)

    if not works(lo, strict=False):
        return None                                 # too big for the room it would get
    hi_cap = 100
    if doc.template != "picture" and _has_words(doc, stock, ctx):
        hi_cap = max(lo, MAX_QR_WITH_WORDS)
    if not works(lo):
        return (lo, lo)                             # the writing needs the room already
    a, b = lo, hi_cap                               # works(a) is True
    if works(b):
        return (lo, b)
    while b - a > 1:
        m = (a + b) // 2
        if works(m):
            a = m
        else:
            b = m
    return (lo, a)


def qr_size_words(doc, stock: stocks.Stock, size: int) -> str:
    """The code's printed size in plain words: "About 2.5 cm (1 inch) across"."""
    qr = qrcodes.clean(getattr(doc, "qr", None))
    text = qrcodes.payload(qr)
    if not text:
        return ""
    n = len(qrcodes.matrix(text))
    m = qrcodes.module_for(region_for(stock).height * size / 100.0, n, stock.dpi)
    if not m:
        return ""
    mm = qrcodes.box_side(n, m) * 25.4 / stock.dpi
    inches = mm / 25.4
    frac = f"{inches:.1f}".rstrip("0").rstrip(".")
    return f"About {mm / 10:.1f} cm ({frac} inch{'es' if inches >= 1.05 else ''}) across"
