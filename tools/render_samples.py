"""Render every template x stock into docs/samples/ (exact printer bitmaps).

``--fonts`` only redraws docs/samples/fonts-contact-sheet.png: every bundled
font as the name of the food on a simple label (with the matching body font
where the font may be used for everything else), plus a cottage label to show
the required wording staying in a readable sans.
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
    for t in model.TEMPLATES:
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


if __name__ == "__main__":
    if "--fonts" in sys.argv[1:]:
        fonts_sheet()
    else:
        main()
        fonts_sheet()
