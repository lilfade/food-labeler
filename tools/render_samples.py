"""Render every template x stock into docs/samples/ (exact printer bitmaps)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from food_labeler import model, render, stocks, templates  # noqa: E402

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
}
CTX = {"date_style": "us", "kitchen_name": "High Thyme Kitchen"}


def main():
    out = ROOT / "docs" / "samples"
    out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for t in model.TEMPLATES:
        for sid in stocks.ORDER:
            if sid not in templates.ALLOWED_STOCKS[t]:
                continue
            doc = model.LabelDoc(t, sid, model.default_fields(t))
            doc.fields.update(SAMPLE[t])
            res = render.render(doc, CTX)
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


if __name__ == "__main__":
    main()
