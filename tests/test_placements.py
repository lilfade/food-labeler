"""Where pictures and QR codes go: above, below, the sides and all four corners,
on every label size. Nothing overlaps (picture, QR code, writing), everything
stays on the label (inside the circle on round labels) and the required
wording keeps its size."""
import math

import pytest
from PIL import Image, ImageDraw

from food_labeler import cottage, extras, model, pictures, qrcodes, render, stocks, templates

import render_cases

RECT = [s for s in stocks.ORDER if not stocks.STOCKS[s].round]


def logo(w=300, h=200):
    im = Image.new("RGB", (w, h), "white")
    ImageDraw.Draw(im).ellipse((10, 10, w - 10, h - 10), fill=(30, 30, 30))
    return pictures.new_picture(im, "logo.png")


LOGO = logo()


def boxes(res):
    """[(kind, (x0, y0, x1, y1))] of everything drawn: picture, QR code (with its
    words), each line of writing."""
    out = []
    for x, y, img in res.layout.images:
        out.append(("picture", (x, y, x + img.width, y + img.height)))
    if res.layout.qr_box:
        x0, y0, x1, y1 = res.layout.qr_box
        caps = [ln for ln in res.layout.lines if ln.key == "qr"]
        if caps:
            y1 = max(y1, max(ln.y + templates.line_height(ln.size) for ln in caps))
        out.append(("qr", (x0, y0, x1, y1)))
    for ln in res.layout.lines:
        if ln.key == "qr":
            continue
        w = templates.text_width(ln.text, ln.size, ln.bold, ln.font)
        h = templates.line_height(ln.size, ln.bold, ln.font)
        out.append((ln.key, (ln.x, ln.y, ln.x + w, ln.y + h)))
    return out


def overlap(a, b) -> bool:
    return a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5


def check(res, label):
    st = res.stock
    bx = boxes(res)
    things = [(k, b) for k, b in bx if k in ("picture", "qr")]
    text = [(k, b) for k, b in bx if k not in ("picture", "qr")]
    for i, (k1, b1) in enumerate(things):
        assert -0.5 <= b1[0] and -0.5 <= b1[1] and b1[2] <= st.w + 0.5 and b1[3] <= st.h + 0.5, \
            (label, k1, b1)
        for k2, b2 in things[i + 1:]:
            assert not overlap(b1, b2), (label, k1, k2, b1, b2)
        for k2, b2 in text:
            assert not overlap(b1, b2), (label, k1, k2, b1, b2)
        if st.round and k1 == "qr":
            region = templates.region_for(st)
            cx, cy, r = region.circle
            for x, y in ((b1[0], b1[1]), (b1[2], b1[1]), (b1[0], b1[3]), (b1[2], b1[3])):
                assert math.hypot(x - cx, y - cy) <= r + 1, (label, "qr outside circle")


def doc_for(stock, pic_place=None, qr_place=None, pic_size=30, qr_size=30):
    d = model.LabelDoc("simple", stock, model.default_fields("simple"))
    d.fields.update(food="Lemon Bars", contains="Milk, Eggs")
    if pic_place:
        d.picture = dict(LOGO, place=pic_place, size=pic_size)
    if qr_place:
        d.qr = dict(qrcodes.DEFAULTS, value="example.com", place=qr_place, size=qr_size)
    return d


PIC_PLACES = pictures.PLACES_FOR_OTHERS
NEW = ["bottom", "corner_bottom_left", "corner_bottom_right"]


def test_new_places_are_offered():
    for p in NEW:
        assert p in pictures.PLACES and p in qrcodes.PLACES and p in pictures.PLACES_FOR_OTHERS
    for p in ("above", "left", "right", "corner", "corner_right"):
        assert p in qrcodes.PLACES                             # the old ones stay
    assert pictures.PLACES["bottom"] and pictures.PLACES["corner_bottom_left"]
    assert pictures.clean(dict(LOGO, place="corner_bottom_right"))["place"] == \
        "corner_bottom_right"


@pytest.mark.parametrize("stock", stocks.ORDER)
@pytest.mark.parametrize("place", PIC_PLACES)
def test_picture_alone_never_overlaps(stock, place):
    res = render.render(doc_for(stock, pic_place=place))
    check(res, (stock, place))


@pytest.mark.parametrize("stock", stocks.ORDER)
@pytest.mark.parametrize("place", qrcodes.PLACES)
def test_qr_alone_never_overlaps(stock, place):
    res = render.render(doc_for(stock, qr_place=place))
    check(res, (stock, place))


@pytest.mark.parametrize("stock", stocks.ORDER)
def test_picture_and_qr_in_every_combination(stock):
    for pp in PIC_PLACES:
        for qp in qrcodes.PLACES:
            res = render.render(doc_for(stock, pic_place=pp, qr_place=qp, pic_size=25,
                                        qr_size=25))
            check(res, (stock, pp, qp))


@pytest.mark.parametrize("dpi", [203, 300])
def test_combinations_at_300_dpi_too(dpi):
    for pp, qp in [("left", "corner"), ("corner_bottom_left", "left"), ("bottom", "above"),
                   ("corner_bottom_right", "corner_right"), ("right", "corner_bottom_right")]:
        res = render.render(doc_for("large", pic_place=pp, qr_place=qp, pic_size=25,
                                    qr_size=25), dpi=dpi)
        check(res, (dpi, pp, qp))


@pytest.mark.parametrize("stock", RECT)
def test_bottom_goes_below_the_writing(stock):
    res = render.render(doc_for(stock, pic_place="bottom", pic_size=25))
    (x, y, img), = res.layout.images
    text = [b for k, b in boxes(res) if k not in ("picture", "qr")]
    assert y >= max(b[3] for b in text) - 0.5
    region = templates.region_for(res.stock)
    assert abs((y + img.height) - region.bottom) <= 1
    assert abs((x + img.width / 2) - (region.left + region.right) / 2) <= 1      # centred


@pytest.mark.parametrize("stock", RECT)
@pytest.mark.parametrize("place,side", [("corner_bottom_left", "left"),
                                        ("corner_bottom_right", "right")])
def test_bottom_corners(stock, place, side):
    res = render.render(doc_for(stock, pic_place=place, pic_size=25))
    (x, y, img), = res.layout.images
    region = templates.region_for(res.stock)
    assert abs((y + img.height) - region.bottom) <= 1
    if side == "left":
        assert abs(x - region.left) <= 1
    else:
        assert abs(x + img.width - region.right) <= 1
    # the writing flows over the corner box, so it starts at the top of the label
    text = [b for k, b in boxes(res) if k not in ("picture", "qr")]
    assert min(b[1] for b in text) < y


def test_round_labels_use_top_and_bottom_of_the_circle():
    st = stocks.get("round")
    for p in ("above", "left", "right", "corner", "corner_right"):
        assert extras.where(p, st) == "above"
    for p in NEW:
        assert extras.where(p, st) == "bottom"
    assert pictures.PLACES_ON_ROUND == ["above", "bottom"]
    res = render.render(doc_for("round", pic_place="bottom", qr_place="above", pic_size=25,
                                qr_size=30))
    check(res, "round")
    (x, y, img), = res.layout.images
    qx0, qy0, qx1, qy1 = res.layout.qr_box
    assert y > qy1                                             # picture under, code over


def test_old_placements_lay_out_as_before():
    """Placements that existed before keep their exact layout (one thing on the label)."""
    for place in ("above", "left", "right", "corner"):
        res = render.render(doc_for("large", pic_place=place))
        (x, y, img), = res.layout.images
        region = templates.region_for(res.stock)
        if place == "above":
            assert y == region.top
        elif place == "corner":
            assert (x, y) == (region.left, region.top)
        elif place == "right":
            assert x + img.width == pytest.approx(region.right, abs=1)


@pytest.mark.parametrize("place", NEW + ["left", "corner"])
def test_required_wording_keeps_its_size(place):
    rules = cottage.CottageRules()
    ctx = render_cases._ctx(rules, "NE")
    rule = ctx["cottage"]["rule"]
    mins = {"statement:" + s["id"]: s["min_pt"] for s in rule["statements"] if s.get("min_pt")}
    d = model.LabelDoc("cottage", "large", model.default_fields("cottage"))
    d.fields.update(render_cases.SAMPLE["cottage"])
    d.picture = dict(LOGO, place=place, size=100)
    res = render.render(d, ctx)
    assert not res.overflow
    for ln in res.layout.lines:
        if ln.key in mins:
            assert ln.size * 72 / 203 >= mins[ln.key] - 1e-9
    check(res, place)


@pytest.mark.parametrize("place", NEW)
def test_picture_label_qr_places(place):
    d = model.LabelDoc("picture", "large", {"text": "Thank you"})
    d.picture = dict(LOGO, place="fit", size=100)
    d.qr = dict(qrcodes.DEFAULTS, value="example.com", place=place, size=40)
    res = render.render(d)
    assert not res.overflow
    check(res, place)
