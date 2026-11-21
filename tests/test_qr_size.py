"""The QR code's "How big?" slider: it starts at the smallest size that still scans
and stops before the code takes over the label."""
import pytest

from food_labeler import extras, model, qrcodes, render, stocks, templates

SHORT = "example.com"
LONG = "https://example.com/our/menu/today?with=a&few=more&words=in&it=to&make=it&long=1"


def doc(stock="large", value=SHORT, place="right", template="simple", text=True):
    d = model.LabelDoc(template, stock, model.default_fields(template))
    if text and template == "simple":
        d.fields.update(food="Lemon Bars", contains="Milk, Eggs")
    d.qr = dict(qrcodes.DEFAULTS, value=value, place=place)
    return d


def at(d, size, dpi=203):
    d = d.copy()
    d.qr = dict(d.qr, size=size)
    return render.render(d, dpi=dpi)


@pytest.mark.parametrize("dpi", [203, 300])
@pytest.mark.parametrize("stock", stocks.ORDER)
@pytest.mark.parametrize("value", [SHORT, LONG])
@pytest.mark.parametrize("place", ["right", "above", "corner_bottom_left"])
def test_slider_ends_always_print(stock, dpi, value, place):
    d = doc(stock, value, place)
    st = stocks.get(stock, dpi)
    rng = extras.qr_size_range(d, st)
    if rng is None:                     # too much for the little sticker: said plainly
        assert stock == "small" and value == LONG
        return
    lo, hi = rng
    assert qrcodes.SIZE_RANGE[0] <= lo <= hi <= qrcodes.SIZE_RANGE[1]
    n = len(qrcodes.matrix(qrcodes.payload(d.qr)))
    h = templates.region_for(st).height
    for size in {lo, hi, (lo + hi) // 2}:
        res = at(d, size, dpi)
        assert res.message != qrcodes.TOO_SMALL
        if lo == hi and res.overflow:
            # the writing already fills this little label: the code can't be any
            # size, and the label says the QR code is what to make room for
            assert stock == "small" and res.problem_field == "qr"
            continue
        assert not res.overflow, (size, res.message)
        assert res.layout.qr is not None
        assert res.layout.qr[2] >= qrcodes.min_module(dpi)          # readable squares
        assert res.layout.qr[2] == qrcodes.module_for(h * size / 100, n, dpi)  # as asked
    if lo > qrcodes.SIZE_RANGE[0]:
        # one smaller would not scan: the slider can't go there
        assert not qrcodes.module_for(h * (lo - 1) / 100, n, dpi) or \
            at(d, lo - 1, dpi).message == qrcodes.TOO_SMALL
    assert hi <= max(lo, extras.MAX_QR_WITH_WORDS)                  # room for the writing


def test_longer_content_needs_a_bigger_code():
    st = stocks.get("large")
    lo_short = extras.qr_size_range(doc(value=SHORT), st)[0]
    lo_long = extras.qr_size_range(doc(value=LONG), st)[0]
    assert lo_long > lo_short


def test_sharper_printer_allows_smaller_codes():
    d = doc(value=LONG)
    assert extras.qr_size_range(d, stocks.get("large", 300))[0] < \
        extras.qr_size_range(d, stocks.get("large", 203))[0]


def test_too_much_for_this_label():
    d = doc("small", value="x" * 600)
    assert extras.qr_size_range(d, stocks.get("small")) is None


def test_qr_alone_may_be_bigger():
    d = model.LabelDoc("free", "large", {"text": ""})
    d.qr = dict(qrcodes.DEFAULTS, value=SHORT, place="above")
    lo, hi = extras.qr_size_range(d, stocks.get("large"))
    assert hi > extras.MAX_QR_WITH_WORDS
    res = at(d, hi)
    side = res.layout.qr_box[2] - res.layout.qr_box[0]
    st = res.stock
    assert side <= st.h - 2 * st.margin and not res.overflow        # inside the margins


def test_picture_label_may_have_a_bigger_code():
    d = model.LabelDoc("picture", "xl", {"text": "Thank you"})
    d.qr = dict(qrcodes.DEFAULTS, value=SHORT, place="above")
    lo, hi = extras.qr_size_range(d, stocks.get("xl"))
    assert hi > extras.MAX_QR_WITH_WORDS
    assert not at(d, hi).overflow


def test_size_in_plain_words():
    d = doc()
    words = extras.qr_size_words(d, stocks.get("large"), 40)
    assert words.startswith("About ") and "cm" in words and "inch" in words
