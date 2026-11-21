"""Draw a label as the exact 1-bit picture the printer will print.

``render()`` is the one call the rest of the program uses: document ->
templates.layout() -> a mode "1" image of stock.w x stock.h dots (white = 1).
That same image goes to tspl/zpl for printing and, scaled, to the on-screen
preview, so the preview can never disagree with the printout.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from . import stocks, templates
from .templates import FIELD_NAMES, Layout


@dataclass
class RenderResult:
    """The printable picture plus the layout it came from (for overflow messages)."""

    image: Image.Image          # mode "1", stock.w x stock.h, white background
    layout: Layout
    stock: stocks.Stock

    @property
    def overflow(self) -> bool:
        return self.layout.overflow

    @property
    def problem_field(self) -> str:
        return self.layout.overflow_key

    @property
    def message(self) -> str:
        if not self.layout.overflow:
            return ""
        name = FIELD_NAMES.get(self.layout.overflow_key, "")
        extra = f" (The {name} is the longest part.)" if name else ""
        return self.layout.message + extra


def draw_layout(lay: Layout, w: int, h: int, smooth: bool = False) -> Image.Image:
    """Draw straight into a 1-bit image at final size.

    We compared this with drawing in greyscale and thresholding at 128: at
    12-dot text on 203 dpi, direct 1-bit drawing (FreeType's hinted monochrome
    mode) gave more even strokes and spacing, so that is what we use there.
    At 300 dpi the hinted mode rounds each letter's position on its own and
    can leave a visible gap inside a word ("Prod uced"), so with ``smooth``
    the text is drawn in greyscale and thresholded instead.
    """
    img = Image.new("1", (w, h), 1)
    for (x, y, pic) in lay.images:          # pictures, already black and white
        img.paste(pic, (x, y))
    d = ImageDraw.Draw(img)
    if lay.qr_box:                           # the QR code's quiet zone stays paper
        d.rectangle(lay.qr_box, fill=1)
    if smooth and lay.lines:
        grey = Image.new("L", (w, h), 255)
        gd = ImageDraw.Draw(grey)
        for ln in lay.lines:
            gd.text((ln.x, ln.y), ln.text, font=templates.font(ln.size, ln.bold, ln.font),
                    fill=0, anchor="la")
        img.paste(0, (0, 0), grey.point(lambda v: 255 if v < 128 else 0))
    else:
        for ln in lay.lines:
            d.text((ln.x, ln.y), ln.text, font=templates.font(ln.size, ln.bold, ln.font),
                   fill=0, anchor="la")
    if lay.qr:
        qx, qy, mod, matrix = lay.qr
        for r, row in enumerate(matrix):
            for c, v in enumerate(row):
                if v:
                    x0, y0 = int(qx + c * mod), int(qy + r * mod)
                    d.rectangle((x0, y0, x0 + mod - 1, y0 + mod - 1), fill=0)
    return img


def render(doc, ctx: dict | None = None, dpi: int = stocks.BASE_DPI) -> RenderResult:
    """Lay out and draw a LabelDoc. ctx: settings that affect the label
    (``date_style``, ``kitchen_name``; see Settings.render_ctx). dpi: the
    chosen printer's resolution (203 or 300); the label keeps its physical
    size and only gets more dots. It is never stored in the document."""
    stock = stocks.get(doc.stock, dpi)
    lay = templates.layout(doc, stock, ctx or {})
    return RenderResult(draw_layout(lay, stock.w, stock.h, stock.dpi > stocks.BASE_DPI),
                        lay, stock)


def render_text_label(lines: list[str], stock: stocks.Stock) -> Image.Image:
    """Simple centred text label (used for the printer test)."""
    blocks = [templates.Block("", t, 60 if i == 0 else 40, stock.d(12), i == 0, "center", 0.3,
                              True)
              for i, t in enumerate(lines)]
    region = templates.region_for(stock)
    base = templates._base(region)
    for b in blocks:
        b.pref = base * (0.24 if b.bold else 0.15)
    lay = templates.fit(blocks, region, "center")
    return draw_layout(lay, stock.w, stock.h, stock.dpi > stocks.BASE_DPI)


# ---------------------------------------------------------------------------
# On-screen preview / sample pictures
# ---------------------------------------------------------------------------

PAPER = (255, 255, 255)
INK = (20, 20, 20)
BACK = (226, 222, 214)
EDGE = (150, 145, 135)
SHADOW = (196, 191, 182)
HILITE = (255, 214, 102)


def scaled(img1: Image.Image, scale: float) -> Image.Image:
    """Scale the 1-bit bitmap for display; nearest when enlarging keeps it exact."""
    w, h = max(1, round(img1.width * scale)), max(1, round(img1.height * scale))
    if scale >= 1:
        return img1.convert("L").resize((w, h), Image.NEAREST)
    return img1.convert("L").resize((w, h), Image.LANCZOS)


def preview(res: RenderResult, max_w: int, max_h: int, highlight: bool = True) -> Image.Image:
    """The label drawn on a soft background with its real outline (rounded or round)."""
    st = res.stock
    pad = 18
    scale = min((max_w - 2 * pad) / st.w, (max_h - 2 * pad) / st.h)
    scale = max(scale, 0.05)
    lab = scaled(res.image, scale)
    W, H = max_w, max_h
    out = Image.new("RGB", (W, H), BACK)
    x0, y0 = (W - lab.width) // 2, (H - lab.height) // 2
    d = ImageDraw.Draw(out)
    rad = max(4, int(3 * 8 * st.scale * scale))  # ~3 mm corner radius
    if st.round:
        box = (x0, y0, x0 + lab.width - 1, y0 + lab.height - 1)
        d.ellipse((box[0] + 5, box[1] + 6, box[2] + 5, box[3] + 6), fill=SHADOW)
        mask = Image.new("L", lab.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, lab.width - 1, lab.height - 1), fill=255)
        out.paste(lab.convert("RGB"), (x0, y0), mask)
        d.ellipse(box, outline=EDGE, width=2)
        # printable circle (dotted)
        r = st.circle_dia / 2 * scale
        cx, cy = x0 + lab.width / 2, y0 + lab.height / 2
        _dashed_circle(d, cx, cy, r, (190, 185, 175))
    else:
        box = (x0, y0, x0 + lab.width - 1, y0 + lab.height - 1)
        d.rounded_rectangle((box[0] + 5, box[1] + 6, box[2] + 5, box[3] + 6), rad, fill=SHADOW)
        mask = Image.new("L", lab.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, lab.width - 1, lab.height - 1), rad, fill=255)
        out.paste(lab.convert("RGB"), (x0, y0), mask)
        d.rounded_rectangle(box, rad, outline=EDGE, width=2)
    if highlight and res.overflow:
        for ln in res.layout.lines:
            if ln.key == res.problem_field:
                w = templates.text_width(ln.text, ln.size, ln.bold, ln.font)
                lh = templates.line_height(ln.size, ln.bold, ln.font)
                bx = (x0 + ln.x * scale - 3, y0 + ln.y * scale - 2,
                      x0 + (ln.x + w) * scale + 3, y0 + (ln.y + lh) * scale + 2)
                d.rectangle(bx, outline=(214, 92, 0), width=3)
    return out


def _dashed_circle(d, cx, cy, r, color):
    import math
    n = 72
    for i in range(0, n, 2):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        d.line((cx + r * math.cos(a0), cy + r * math.sin(a0),
                cx + r * math.cos(a1), cy + r * math.sin(a1)), fill=color, width=1)


def export_png(res: RenderResult, path, scale: int = 2) -> None:
    """Save the printable bitmap as a PNG ("Save as picture"), enlarged without blur.

    The picture is the label at the printer's resolution (each printer dot
    becomes scale x scale pixels) and its dpi metadata is the printer's dpi
    times ``scale``, so it prints at the label's real size."""
    img = res.image.convert("L").resize((res.image.width * scale, res.image.height * scale),
                                        Image.NEAREST)
    d = res.stock.dpi * scale
    img.save(path, dpi=(d, d))
