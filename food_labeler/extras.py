"""Placing a picture and/or a QR code on a label, with the text flowing around them.

Used by templates.layout() when a label has a picture or a QR code, and for
the Picture label (one big picture, optional words under it).

Plain-word placements (pictures.PLACES): *Above the name* takes a band across
the top; *Left side* / *Right side* take a column the height of the text
area; *Top-left corner* / *Top-right corner* take just their own box, so the
text flows beside and then under them. Several things in the same place sit
side by side (above) or one under the other (columns). On round labels
everything goes above the name, kept inside the circle.

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


def arrange(items: list[Item], stock: stocks.Stock, region: Region) -> None:
    """Give items their positions and take their space out of ``region``."""
    gap = stock.d(12)
    slots: dict[str, list[Item]] = {}
    for it in items:
        place = "above" if stock.round or it.place in ("fill", "fit") else it.place
        slots.setdefault(place, []).append(it)
    for place, its in slots.items():
        if place == "above":
            for _ in range(40):
                total = sum(i.w for i in its) + gap * (len(its) - 1)
                band = max(i.h for i in its)
                if total > region.full_width:
                    k = region.full_width / total
                elif band > region.height:
                    k = region.height / band
                elif region.circle is not None and _fit_in_circle(region, total / 2,
                                                                 band) is None:
                    k = 0.95
                else:
                    break
                for i in its:
                    i.scale(k, stock)
            total = sum(i.w for i in its) + gap * (len(its) - 1)
            band = max(i.h for i in its)
            y0 = region.top
            if region.circle is not None:
                y0 = _fit_in_circle(region, total / 2, band) or region.top
            x = (region.left + region.right) / 2 - total / 2
            for i in its:
                i.x, i.y = x, y0
                x += i.w + gap
            region.top = y0 + band + gap
            continue
        # a column on the left or right, or a corner box
        maxw = region.full_width * 0.45
        for _ in range(40):
            colw = max(i.w for i in its)
            total = sum(i.h for i in its) + gap * (len(its) - 1)
            if colw > maxw:
                k = maxw / colw
            elif total > region.height:
                k = region.height / total
            else:
                break
            for i in its:
                i.scale(k, stock)
        colw = max(i.w for i in its)
        total = sum(i.h for i in its) + gap * (len(its) - 1)
        corner = place.startswith("corner")
        y = region.top if corner else region.top + (region.height - total) / 2
        y_end = y + total
        left = place in ("left", "corner")
        for i in its:
            i.x = region.left if left else region.right - i.w
            i.y = y
            y += i.h + gap
        ey0, ey1 = (region.top, y_end + gap) if corner else (region.top, region.bottom)
        if left:
            region.exclusions.append((region.left, ey0, region.left + colw + gap, ey1))
        else:
            region.exclusions.append((region.right - colw - gap, ey0, region.right, ey1))


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
            it.place = {"corner": "left", "corner_right": "right"}.get(it.place, it.place)
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
