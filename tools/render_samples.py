"""Render every template x stock into docs/samples/ (exact printer bitmaps).

``--fonts`` only redraws docs/samples/fonts-contact-sheet.png: every bundled
font as the name of the food on a simple label (with the matching body font
where the font may be used for everything else), plus a cottage label to show
the required wording staying in a readable sans. ``--dpi`` only redraws
docs/samples/dpi-203-vs-300.png: the same label for a 203 dpi and a 300 dpi
printer, whole and as a zoomed crop of the same spot on paper. ``--pictures``
only redraws docs/samples/picture-*.png and qr-*.png.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from food_labeler import bakery, cottage, lettering, model, render, stocks, templates  # noqa: E402

SAMPLE = {
    "simple": {"food": "Chicken Noodle Soup", "made_on": "2026-11-20", "use_by": "2026-11-25",
               "contains": "Wheat, Eggs", "note": "Keep refrigerated", "made_by": "Grandma Jo",
               "kitchen": True},
    "package": {"product": "Lemon Thyme Shortbread", "net": "8 oz (227 g)",
                "ingredients": "Butter (cream, salt), wheat flour, sugar, lemon zest, "
                               "fresh thyme, vanilla extract, sea salt.",
                "contains": "Milk, Wheat", "lot": "261120", "best_by": "2026-12-04",
                "business": "High Thyme Kitchen", "address": "123 Garden Lane\nSpringfield, IL 62704",
                "qr": "https://highthymekitchen.com"},
    "sticker": {"lot": "261120", "made": "2026-11-20", "best_by": "2026-11-27", "count": "12"},
    "free": {"text": "Happy Birthday\nLove, Grandma"},
    "cottage": {"product": "Lemon Thyme Shortbread", "net": "8 oz",
                "ingredients": "Butter (cream, salt), all-purpose flour (wheat flour, niacin, "
                               "reduced iron, thiamine mononitrate, riboflavin, folic acid), "
                               "sugar, lemon zest, fresh thyme, sea salt",
                "contains": "Milk, Wheat", "storage": "Store in a cool, dry place",
                "made_on": "2026-11-20", "best_by": "2026-12-04"},
}
CTX = {"date_style": "us", "kitchen_name": "High Thyme Kitchen"}
# A made-up bakery for the cottage samples (not a real address).
BAKERY = dict(bakery.PROFILE_DEFAULTS, business="High Thyme Kitchen",
              legal_entity="Example Bakes LLC", street="123 Garden Lane", city="Springfield",
              region="NE", zip="68000", phone="(555) 010-0199", permit="CF-0000",
              cross_contact=model.DEFAULT_CROSS_CONTACT)
COTTAGE_STATES = ["NE", "TX", "CA", "MI"]


def cottage_ctx(rules, sid):
    prof = dict(BAKERY, region=sid)
    return dict(CTX, cottage={"rule": rules.effective(sid).to_ctx(), "profile": prof})


def main():
    out = ROOT / "docs" / "samples"
    out.mkdir(parents=True, exist_ok=True)
    tiles = []
    rules = cottage.CottageRules()
    for t in [x for x in model.TEMPLATES if x in SAMPLE]:
        for sid in stocks.ORDER:
            if sid not in templates.ALLOWED_STOCKS[t]:
                continue
            doc = model.LabelDoc(t, sid, model.default_fields(t))
            doc.fields.update(SAMPLE[t])
            res = render.render(doc, cottage_ctx(rules, "NE") if t == "cottage" else CTX)
            res.image.save(out / f"{t}_{sid}.png")
            pv = render.preview(res, 460, 360)
            ImageDraw.Draw(pv).text((8, 4), f"{t} / {sid}" + ("  OVERFLOW" if res.overflow else ""),
                                    fill=(0, 0, 0))
            tiles.append(pv)
            print(f"{t:8s} {sid:7s} overflow={res.overflow} {res.message}")
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 460, rows * 360), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 460, (i // cols) * 360))
    sheet.save(out / "contact-sheet.png")

    # cottage food labels for a few states x Medium / Large / 4 x 6 in
    tiles = []
    for state in COTTAGE_STATES:
        for sid in templates.ALLOWED_STOCKS["cottage"]:
            doc = model.LabelDoc("cottage", sid, model.default_fields("cottage"))
            doc.fields.update(SAMPLE["cottage"])
            res = render.render(doc, cottage_ctx(rules, state))
            res.image.save(out / f"cottage_{state}_{sid}.png")
            pv = render.preview(res, 460, 360 if sid != "xl" else 640)
            ImageDraw.Draw(pv).text((8, 4), f"cottage {state} / {sid}"
                                    + ("  DOES NOT FIT: refused" if res.overflow else ""),
                                    fill=(0, 0, 0))
            tiles.append(pv)
            print(f"cottage {state} {sid:7s} overflow={res.overflow} {res.message}")
    cols = len(templates.ALLOWED_STOCKS["cottage"])
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 460, rows * 640), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 460, (i // cols) * 640))
    sheet.save(out / "cottage-contact-sheet.png")


def fonts_sheet():
    """docs/samples/fonts-contact-sheet.png: each bundled font on a sample label."""
    out = ROOT / "docs" / "samples"
    rules = cottage.CottageRules()
    tiles = []
    for face in lettering.BUNDLED:
        other = face.name if face.readable else lettering.DEFAULT
        doc = model.LabelDoc("simple", "large", model.default_fields("simple"),
                             lettering={"name": face.name, "other": other})
        doc.fields.update(SAMPLE["simple"])
        res = render.render(doc, CTX)
        pv = render.preview(res, 460, 300)
        ImageDraw.Draw(pv).text((8, 4), f"{face.name}  (min x{face.min_scale})"
                                + ("  OVERFLOW" if res.overflow else ""), fill=(0, 0, 0))
        tiles.append(pv)
        print(f"{face.name:22s} overflow={res.overflow}")
    for name in ("Pacifico", "Caveat"):
        doc = model.LabelDoc("cottage", "large", model.default_fields("cottage"),
                             lettering={"name": name, "other": name})
        doc.fields.update(SAMPLE["cottage"])
        res = render.render(doc, cottage_ctx(rules, "NE"))
        pv = render.preview(res, 460, 300)
        ImageDraw.Draw(pv).text((8, 4), f"cottage: {name} name, required wording stays sans",
                                fill=(0, 0, 0))
        tiles.append(pv)
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 460, rows * 300), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 460, (i // cols) * 300))
    sheet.save(out / "fonts-contact-sheet.png")


def dpi_sheet():
    """docs/samples/dpi-203-vs-300.png: one label at 203 and at 300 dpi."""
    out = ROOT / "docs" / "samples"
    rules = cottage.CottageRules()
    doc = model.LabelDoc("cottage", "large", model.default_fields("cottage"))
    doc.fields.update(SAMPLE["cottage"])
    zoom_w, zoom_h = 640, 320            # on-screen size of the zoomed crop
    crop_mm = (2.5, 25.5, 26.5, 37.5)    # left, top, right, bottom on the paper (mm)
    cols = []
    for dpi in (203, 300):
        res = render.render(doc, cottage_ctx(rules, "NE"), dpi=dpi)
        whole = render.preview(res, zoom_w, 340, highlight=False)
        k = dpi / 25.4
        box = tuple(int(round(v * k)) for v in crop_mm)
        # whole-number zoom (3x and 2x: about the same size on screen) so every
        # printer dot stays a sharp square of equal size
        z = {203: 3, 300: 2}[dpi]
        crop = res.image.crop(box).convert("L")
        crop = crop.resize((crop.width * z, crop.height * z), Image.NEAREST)
        col = Image.new("RGB", (zoom_w, 340 + 30 + zoom_h + 10), "white")
        col.paste(whole, (0, 0))
        col.paste(crop.convert("RGB"), (0, 370))
        d = ImageDraw.Draw(col)
        d.text((8, 4), f"{dpi} dpi: {res.stock.w} x {res.stock.h} dots (4 x 2 in)",
               fill=(0, 0, 0))
        d.text((8, 348), f"{dpi} dpi, zoomed: {crop_mm[2] - crop_mm[0]:g} x "
               f"{crop_mm[3] - crop_mm[1]:g} mm of the label = {box[2] - box[0]} x "
               f"{box[3] - box[1]} dots, each dot shown {z} x {z}", fill=(0, 0, 0))
        cols.append(col)
        print(f"dpi {dpi}: overflow={res.overflow}")
    sheet = Image.new("RGB", (2 * zoom_w + 20, cols[0].height), "white")
    sheet.paste(cols[0], (0, 0))
    sheet.paste(cols[1], (zoom_w + 20, 0))
    sheet.save(out / "dpi-203-vs-300.png")


def synthetic_photo(w=600, h=400):
    """A made-up "photo" (a shaded loaf on a gradient), so no real photo is needed."""
    import math
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            bg = int(150 + 90 * x / w)
            dx, dy = (x - w * 0.5) / (w * 0.36), (y - h * 0.55) / (h * 0.32)
            d = dx * dx + dy * dy
            if d < 1:
                shade = 1 - 0.75 * math.sqrt(max(0.0, (dx + 0.4) ** 2 + (dy + 0.5) ** 2)) / 1.6
                v = max(0, min(255, int(40 + 190 * shade)))
                px[x, y] = (v, int(v * 0.75), int(v * 0.45))
            else:
                px[x, y] = (bg, bg, int(bg * 0.95))
    return im


def picture_samples():
    """docs/samples/picture-*.png: colour logo -> solid black, photo -> tiny dots,
    and a round seal (Picture label)."""
    from food_labeler import pictures
    out = ROOT / "docs" / "samples"
    logo = pictures.normalise(Image.open(ROOT / "food_labeler" / "assets" / "icon.png"))
    photo = pictures.normalise(synthetic_photo())
    jobs = []
    d = model.LabelDoc("simple", "large", model.default_fields("simple"))
    d.fields.update(SAMPLE["simple"])
    d.picture = pictures.new_picture(logo, "logo", place="left", size=70)
    jobs.append(("picture-logo-solid", d, CTX, logo))
    d = model.LabelDoc("picture", "large", {"text": "Fresh from the oven"})
    d.picture = pictures.new_picture(photo, "photo", place="fit", size=100, mode="photo")
    jobs.append(("picture-photo-dither", d, {}, photo))
    d = model.LabelDoc("picture", "round", {"text": ""})
    d.picture = pictures.new_picture(logo, "seal", place="fill", size=100)
    jobs.append(("picture-round-seal", d, {}, logo))
    for name, doc, ctx, original in jobs:
        tiles = []
        for dpi in (203, 300):
            res = render.render(doc, ctx, dpi=dpi)
            pv = render.preview(res, 520, 300, highlight=False)
            ImageDraw.Draw(pv).text((8, 4), f"{dpi} dpi" + ("  OVERFLOW" if res.overflow
                                                             else ""), fill=(0, 0, 0))
            tiles.append(pv)
            print(f"{name} {dpi} overflow={res.overflow} {res.message}")
            if dpi == 203:
                res.image.save(out / f"{name}-203.png")
        src = original.convert("RGBA")
        src.thumbnail((300, 300))
        sheet = Image.new("RGB", (300 + 2 * 520, 300), "white")
        sheet.paste(src, ((300 - src.width) // 2, (300 - src.height) // 2), src)
        ImageDraw.Draw(sheet).text((8, 4), "original", fill=(0, 0, 0))
        sheet.paste(tiles[0], (300, 0))
        sheet.paste(tiles[1], (820, 0))
        sheet.save(out / f"{name}.png")


def qr_samples():
    """docs/samples/qr-*.png: QR codes in each place, at 203 and 300 dpi."""
    from food_labeler import qrcodes
    out = ROOT / "docs" / "samples"
    jobs = []
    d = model.LabelDoc("simple", "large", model.default_fields("simple"))
    d.fields.update(SAMPLE["simple"])
    d.qr = dict(qrcodes.DEFAULTS, value="highthymekitchen.com/menu",
                caption="Scan for our menu", place="right", size=45)
    jobs.append(("qr-simple-right", d, CTX))
    rules = cottage.CottageRules()
    d = model.LabelDoc("cottage", "xl", model.default_fields("cottage"))
    d.fields.update(SAMPLE["cottage"])
    d.qr = dict(qrcodes.DEFAULTS, what="text", value="Reheat 5 minutes at 350 F. "
                "Best eaten within 3 days.", caption="Scan for reheating", place="corner",
                size=25)
    jobs.append(("qr-cottage-text", d, cottage_ctx(rules, "NE")))
    d = model.LabelDoc("simple", "round", model.default_fields("simple"))
    d.fields.update(food="Plum Jam", made_on="2026-11-20", use_by="2027-05-20")
    d.qr = dict(qrcodes.DEFAULTS, what="phone", value="(555) 010-0199", place="above",
                size=40)
    jobs.append(("qr-round-phone", d, CTX))
    for name, doc, ctx in jobs:
        tiles = []
        for dpi in (203, 300):
            res = render.render(doc, ctx, dpi=dpi)
            h = 640 if doc.stock == "xl" else 320
            pv = render.preview(res, 520, h, highlight=False)
            ImageDraw.Draw(pv).text((8, 4), f"{dpi} dpi, holds: "
                                    f"{qrcodes.payload(doc.qr)}"
                                    + ("  OVERFLOW" if res.overflow else ""), fill=(0, 0, 0))
            tiles.append(pv)
            print(f"{name} {dpi} overflow={res.overflow} {res.message}")
        sheet = Image.new("RGB", (1040, tiles[0].height), "white")
        sheet.paste(tiles[0], (0, 0))
        sheet.paste(tiles[1], (520, 0))
        sheet.save(out / f"{name}.png")


if __name__ == "__main__":
    if "--fonts" in sys.argv[1:]:
        fonts_sheet()
    elif "--dpi" in sys.argv[1:]:
        dpi_sheet()
    elif "--pictures" in sys.argv[1:]:
        picture_samples()
        qr_samples()
    else:
        main()
        fonts_sheet()
        dpi_sheet()
        picture_samples()
        qr_samples()
