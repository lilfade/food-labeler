"""Build the app icons from assets/seal.svg (developer tool; needs cairosvg).

Large sizes (64+) use the full High Thyme Kitchen seal on a cream disc.
Small sizes (16/32/48) use a simplified mark: a dark-green disc with the
thyme sprig from the seal in cream, because the seal's thin lines and
script lettering turn to mush below ~64 px.

Run:  .venv/bin/python tools/make_icons.py
"""
import io
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "seal.svg"
OUT = ROOT / "food_labeler" / "assets"
GREEN = (38, 84, 62, 255)
CREAM = (243, 234, 220, 255)


def render_svg(px):
    data = cairosvg.svg2png(url=str(SVG), output_width=px, output_height=px)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def disc_mask(px, ss=4):
    m = Image.new("L", (px * ss, px * ss), 0)
    ImageDraw.Draw(m).ellipse((0, 0, px * ss - 1, px * ss - 1), fill=255)
    return m.resize((px, px), Image.LANCZOS)


def full_seal(px):
    big = render_svg(px * 4)
    big = big.resize((px, px), Image.LANCZOS)
    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.paste(big, (0, 0), disc_mask(px))
    return out


def sprig_mark(px, thick=1):
    # Cut the top sprig out of a large render, use its darkness as a mask.
    S = 2048
    im = render_svg(S)
    # sprig box (seal coords 0..400): approx x 185-215, y 55-105
    box = (int(S * 0.445), int(S * 0.135), int(S * 0.555), int(S * 0.265))
    crop = ImageOps.invert(im.crop(box).convert("L"))
    crop = crop.point(lambda v: 255 if v > 60 else 0)
    bbox = crop.getbbox()
    crop = crop.crop(bbox)
    # thicken strokes so they survive downscaling
    from PIL import ImageFilter
    grow = max(1, int(crop.height / 40)) | 1
    crop = crop.filter(ImageFilter.MaxFilter(grow * thick))
    ss = 8
    W = px * ss
    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.ellipse((0, 0, W - 1, W - 1), fill=GREEN)
    target_h = int(W * 0.70)
    scale = target_h / crop.height
    sprig = crop.resize((max(1, int(crop.width * scale)), target_h), Image.LANCZOS)
    layer = Image.new("RGBA", sprig.size, CREAM)
    canvas.paste(layer, ((W - sprig.width) // 2, (W - sprig.height) // 2), sprig)
    return canvas.resize((px, px), Image.LANCZOS)


def drawn_sprig(px):
    """Hand-drawn geometric sprig for tiny sizes (16/24 px)."""
    ss = 16
    W = px * ss
    c = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    d.ellipse((0, 0, W - 1, W - 1), fill=GREEN)
    u = W / 16.0
    sw = int(1.6 * u)
    d.line((8 * u, 3.2 * u, 8 * u, 13.2 * u), fill=CREAM, width=sw)
    for (y, side) in ((5.2, 1), (7.6, -1), (9.6, 1)):
        leaf = Image.new("RGBA", (int(4.6 * u), int(2.4 * u)), (0, 0, 0, 0))
        ImageDraw.Draw(leaf).ellipse((0, 0, leaf.width - 1, leaf.height - 1), fill=CREAM)
        leaf = leaf.rotate(35 * side, expand=True, resample=Image.BICUBIC)
        x = 8 * u + (0.2 * u if side > 0 else -leaf.width - 0.2 * u)
        c.alpha_composite(leaf, (int(x), int(y * u - leaf.height / 2)))
    return c.resize((px, px), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for px in (16, 24, 32, 48):
        sizes[px] = drawn_sprig(px) if px <= 24 else sprig_mark(px)
    for px in (64, 128, 256):
        sizes[px] = full_seal(px)
    sizes[256].save(OUT / "icon.png")
    sizes[48].save(OUT / "icon-48.png")
    sizes[32].save(OUT / "icon-32.png")
    sizes[16].save(OUT / "icon-16.png")
    full_seal(56).save(OUT / "seal-header.png")
    full_seal(112).save(OUT / "seal-header-2x.png")
    # Multi-resolution .ico with the hand-tuned small sizes.
    order = [256, 128, 64, 48, 32, 24, 16]
    sizes[256].save(OUT / "icon.ico", format="ICO", sizes=[(s, s) for s in order],
                    append_images=[sizes[s] for s in order[1:]])
    # Preview sheet for checking by eye.
    sheet = Image.new("RGBA", (sum(order) + 10 * len(order), 270), (255, 255, 255, 255))
    x = 5
    for s in order:
        sheet.paste(sizes[s], (x, 5), sizes[s])
        x += s + 10
    sheet.save(ROOT / "docs" / "icon-sizes.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
