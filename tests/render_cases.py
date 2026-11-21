"""Fixed set of labels used by the 203 dpi regression test (test_dpi.py).

``cases(dpi)`` renders every template x allowed size with example text (and a
few extra cases: long text that overflows, QR codes, lettering, cottage
states, the printer test label) and yields (name, image, tspl job, zpl job).
``python tests/render_cases.py --write`` stores sha256 hashes of the 203 dpi
results in tests/data/render_baseline_203.json; only do that on purpose.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from food_labeler import bakery, cottage, model, printers, render, stocks, templates, tspl, zpl  # noqa: E402,E501

BASELINE = Path(__file__).resolve().parent / "data" / "render_baseline_203.json"
TODAY = dt.date(2026, 11, 20)
# the kinds of label the baseline was made with (later kinds have their own tests)
TEMPLATES = ["simple", "package", "sticker", "free", "cottage"]

SAMPLE = {
    "simple": {"food": "Chicken Noodle Soup", "made_on": "2026-11-20", "use_by": "2026-11-25",
               "contains": "Wheat, Eggs", "note": "Keep refrigerated", "made_by": "Grandma Jo",
               "kitchen": True},
    "package": {"product": "Lemon Thyme Shortbread", "net": "8 oz (227 g)",
                "ingredients": "Butter (cream, salt), wheat flour, sugar, lemon zest, "
                               "fresh thyme, vanilla extract, sea salt.",
                "contains": "Milk, Wheat", "lot": "261120", "best_by": "2026-12-04",
                "business": "High Thyme Kitchen",
                "address": "123 Garden Lane\nSpringfield, IL 62704",
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
BAKERY = dict(bakery.PROFILE_DEFAULTS, business="High Thyme Kitchen",
              legal_entity="Example Bakes LLC", street="123 Garden Lane", city="Springfield",
              region="NE", zip="68000", phone="(555) 010-0199", permit="CF-0000",
              cross_contact=model.DEFAULT_CROSS_CONTACT)
STATES = ["NE", "TX", "CA", "MI", "custom"]
LETTERING = [{"name": "Pacifico", "other": "Lato"}, {"name": "Caveat", "other": "Caveat"}]


def _ctx(rules, sid):
    prof = dict(BAKERY, region=sid if sid != "custom" else "NE")
    return dict(CTX, cottage={"rule": rules.effective(sid).to_ctx(), "profile": prof})


def docs():
    """(name, LabelDoc, ctx) for every case."""
    rules = cottage.CottageRules()
    out = []
    for t in TEMPLATES:
        for sid in templates.ALLOWED_STOCKS[t]:
            ctx = _ctx(rules, "NE") if t == "cottage" else CTX
            d = model.LabelDoc(t, sid, model.default_fields(t, TODAY))
            out.append((f"{t}/{sid}/empty", d, ctx))
            d = model.LabelDoc(t, sid, model.default_fields(t, TODAY))
            d.fields.update(SAMPLE[t])
            out.append((f"{t}/{sid}/sample", d, ctx))
            d = d.copy()
            key = {"simple": "note", "package": "ingredients", "sticker": "count",
                   "free": "text", "cottage": "ingredients"}[t]
            d.fields[key] = "word " * 140
            out.append((f"{t}/{sid}/overflow", d, ctx))
            for i, let in enumerate(LETTERING):
                d = model.LabelDoc(t, sid, model.default_fields(t, TODAY), lettering=let)
                d.fields.update(SAMPLE[t])
                out.append((f"{t}/{sid}/lettering{i}", d, ctx))
    for state in STATES:
        for sid in templates.ALLOWED_STOCKS["cottage"]:
            d = model.LabelDoc("cottage", sid, model.default_fields("cottage", TODAY))
            d.fields.update(SAMPLE["cottage"])
            out.append((f"cottage-{state}/{sid}", d, _ctx(rules, state)))
    for sid in templates.ALLOWED_STOCKS["simple"]:
        d = model.LabelDoc("simple", sid, model.default_fields("simple", TODAY))
        d.fields.update(food="Supercalifragilistic Soup", contains="Milk, Eggs, Fish, Shellfish, "
                        "Tree nuts, Peanuts, Wheat, Soy, Sesame")
        out.append((f"simple/{sid}/long", d, CTX))
    return out


def _render(doc, ctx, dpi):
    if "dpi" in inspect.signature(render.render).parameters:
        return render.render(doc, ctx, dpi=dpi)
    assert dpi == 203
    return render.render(doc, ctx)


def _stock(sid, dpi):
    if "dpi" in inspect.signature(stocks.get).parameters:
        return stocks.get(sid, dpi)
    assert dpi == 203
    return stocks.get(sid)


def cases(dpi=203):
    """Yield (name, picture, tspl job, zpl job) for every case at ``dpi``."""
    for name, d, ctx in docs():
        res = _render(d, ctx, dpi)
        img = res.image
        yield (name, img, tspl.build_job(img, res.stock, 2), zpl.build_job(img, res.stock, 2))
    for sid in stocks.ORDER:
        st = _stock(sid, dpi)
        img = render.render_text_label(["Which one is it?", "White label printer",
                                        "USB port 1-1.4"], st)
        cfg = {"kind": "tspl", "method": "device", "target": "/dev/null"}
        job = printers.build_job(img, st, cfg, {"density": {}, "speed": {}, "gap": {}}, 1)
        yield (f"test-label/{sid}", img, job, zpl.build_job(img, st, 1))


def digest(img, tjob, zjob) -> dict:
    return {"size": list(img.size),
            "image": hashlib.sha256(img.tobytes()).hexdigest(),
            "tspl": hashlib.sha256(tjob).hexdigest(),
            "zpl": hashlib.sha256(zjob).hexdigest()}


def compute(dpi=203) -> dict:
    return {name: digest(img, t, z) for name, img, t, z in cases(dpi)}


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        data = compute(203)
        BASELINE.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(data)} cases to {BASELINE}")
