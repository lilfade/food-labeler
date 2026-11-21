"""QR codes on labels: what they hold, whole-dot modules, the quiet zone, too-small
codes refused, the old package-label QR field, and real decoding when a decoder
(zxing-cpp, requirements-dev.txt) is installed."""
import json
import math

import pytest

from food_labeler import model, qrcodes, render, templates

import render_cases


def doc(template="simple", stock="large", **qr):
    d = model.LabelDoc(template, stock, model.default_fields(template, render_cases.TODAY))
    d.fields.update(render_cases.SAMPLE.get(template, {}))
    d.qr = dict(qrcodes.DEFAULTS, **qr)
    return d


def test_payloads():
    p = qrcodes.payload
    assert p({"what": "link", "value": "highthymekitchen.com"}) == "https://highthymekitchen.com"
    assert p({"what": "link", "value": "http://x.org/menu"}) == "http://x.org/menu"
    assert p({"what": "phone", "value": "(555) 010-0199"}) == "tel:5550100199"
    assert p({"what": "phone", "value": "+1 555 010 0199"}) == "tel:+15550100199"
    assert p({"what": "email", "value": "jo@example.com"}) == "mailto:jo@example.com"
    assert p({"what": "email", "value": "not an email"}) == ""
    assert p({"what": "text", "value": "Reheat 2 min\nStir"}) == "Reheat 2 min\nStir"
    assert p({"what": "link", "value": "  "}) == "" and p(None) == ""


def check_code(res, text):
    """Modules are whole dots, match segno's matrix exactly, quiet zone is paper."""
    qx, qy, mod, matrix = res.layout.qr
    assert isinstance(mod, int) and mod >= qrcodes.min_module(res.stock.dpi)
    assert matrix == qrcodes.matrix(text)
    px = res.image.load()
    n = len(matrix)
    for r in range(n):
        for c in range(n):
            x, y = qx + c * mod, qy + r * mod
            want = 0 if matrix[r][c] else 1
            for (dx, dy) in ((0, 0), (mod - 1, 0), (0, mod - 1), (mod - 1, mod - 1)):
                assert (1 if px[x + dx, y + dy] else 0) == want
    q = qrcodes.QUIET * mod
    for x in range(qx - q, qx + n * mod + q):
        for y in (qy - q, qy - 1, qy + n * mod, qy + n * mod + q - 1):
            assert px[x, y] != 0
    for y in range(qy - q, qy + n * mod + q):
        for x in (qx - q, qx - 1, qx + n * mod, qx + n * mod + q - 1):
            assert px[x, y] != 0


@pytest.mark.parametrize("dpi", [203, 300])
@pytest.mark.parametrize("place", qrcodes.PLACES)
def test_geometry_every_place(dpi, place):
    d = doc(value="highthymekitchen.com", caption="Scan for our menu", place=place, size=40)
    res = render.render(d, render_cases.CTX, dpi=dpi)
    assert not res.overflow, res.message
    check_code(res, "https://highthymekitchen.com")
    if dpi == 300:
        assert res.layout.qr[2] >= 4


def test_round_label_code_inside_circle():
    d = doc("simple", "round", value="hi.com", size=45)
    d.fields["food"] = "Jam"
    for dpi in (203, 300):
        res = render.render(d, {}, dpi=dpi)
        assert not res.overflow
        check_code(res, "https://hi.com")
        x0, y0, x1, y1 = res.layout.qr_box
        cx, cy = res.stock.circle_center
        r = res.stock.circle_dia / 2
        for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            assert math.hypot(x - cx, y - cy) <= r


def test_too_much_for_a_small_code():
    d = doc(what="text", value="Ingredients: " + "flour, sugar, butter, " * 30, size=10)
    res = render.render(d, render_cases.CTX)
    assert res.overflow and res.problem_field == "qr"
    assert "too much for a QR code this small" in res.message
    assert qrcodes.module_for(100, 21, 203) == 3 and qrcodes.module_for(80, 21, 203) == 0
    assert qrcodes.min_module(300) == 4


def test_text_wins_over_the_code():
    rules = render_cases.cottage.CottageRules()
    ctx = render_cases._ctx(rules, "NE")
    d = doc("cottage", "xl", value="highthymekitchen.com", size=100, place="above")
    d.fields.update(render_cases.SAMPLE["cottage"])
    res = render.render(d, ctx)
    assert not res.overflow
    n = len(qrcodes.matrix("https://highthymekitchen.com"))
    asked = qrcodes.module_for(templates.region_for(res.stock).height, n, 203)
    assert 0 < res.layout.qr[2] < asked                   # the code gave way
    mins = {"statement:" + s["id"]: s["min_pt"]
            for s in ctx["cottage"]["rule"]["statements"] if s.get("min_pt")}
    for ln in res.layout.lines:
        if ln.key in mins:
            assert ln.size * 72 / 203 >= mins[ln.key] - 1e-9
    check_code(res, "https://highthymekitchen.com")


def test_picture_label_with_qr():
    from test_pictures import colour_logo, pic_of
    d = model.LabelDoc("picture", "large", {"text": "Thank you"})
    d.picture = pic_of(colour_logo(), place="fit", size=100)
    d.qr = dict(qrcodes.DEFAULTS, value="hi.com", place="right", size=60)
    res = render.render(d, {})
    assert not res.overflow and res.layout.images
    check_code(res, "https://hi.com")
    (x, y, img), = res.layout.images
    assert x + img.width <= res.layout.qr_box[0]


def test_old_package_qr_field_is_migrated(tmp_path):
    old = {"app": "easy-labels", "version": 1, "template": "package", "stock": "large",
           "fields": {"product": "Shortbread", "qr": "https://highthymekitchen.com"},
           "copies": 1}
    path = tmp_path / "old.label"
    text = json.dumps(old, indent=2)
    path.write_text(text, encoding="utf-8")
    d = model.load(path)
    assert path.read_text(encoding="utf-8") == text            # nothing written on open
    assert d.fields["qr"] == ""
    assert d.qr["what"] == "link" and d.qr["value"] == "https://highthymekitchen.com"
    assert d.qr["place"] == "corner_right"
    res = render.render(d, {})
    assert not res.overflow
    check_code(res, "https://highthymekitchen.com")
    saved = json.loads(d.dumps())
    assert saved["fields"]["qr"] == "https://highthymekitchen.com"     # earlier versions
    assert saved["qr"]["value"] == "https://highthymekitchen.com"
    again = model.LabelDoc.loads(d.dumps())
    assert again.dumps() == d.dumps()
    plain = {"app": "easy-labels", "version": 1, "template": "package", "stock": "large",
             "fields": {"product": "Shortbread", "qr": ""}, "copies": 1}
    assert "qr" not in model.LabelDoc.from_dict(plain).to_dict()


def test_qr_round_trip(tmp_path):
    d = doc(what="phone", value="555 010 0199", caption="Call us", place="left", size=30)
    back = model.load(model.save(d, tmp_path / "q"))
    assert back.qr == qrcodes.clean(d.qr)


def _decode(img):
    zxingcpp = pytest.importorskip("zxingcpp")
    return [r.text for r in zxingcpp.read_barcodes(img.convert("L"))]


@pytest.mark.parametrize("dpi", [203, 300])
def test_printed_codes_scan(dpi):
    cases = [
        ("link", "highthymekitchen.com/menu", "https://highthymekitchen.com/menu"),
        ("phone", "(555) 010-0199", "tel:5550100199"),
        ("email", "hello@highthymekitchen.com", "mailto:hello@highthymekitchen.com"),
        ("text", "Reheat 2 minutes. Keep refrigerated.", "Reheat 2 minutes. Keep refrigerated."),
    ]
    for what, value, want in cases:
        for stock in ("small", "large", "round"):
            d = doc("simple", stock, what=what, value=value, size=60, place="above")
            d.fields.update(food="Soup", note="", made_by="", contains="", kitchen=False)
            res = render.render(d, {}, dpi=dpi)
            if res.overflow:
                assert res.problem_field == "qr"
                continue
            assert _decode(res.image) == [want], (what, stock, dpi)
