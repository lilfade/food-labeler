import math

from food_labeler import model, render, stocks, templates


def doc_with(template, stock, **fields):
    d = model.LabelDoc(template, stock, model.default_fields(template))
    d.fields.update(fields)
    return d


def lines_inside(res):
    st = res.stock
    reg = templates.region_for(st)
    for ln in res.layout.lines:
        w = templates.text_width(ln.text, ln.size, ln.bold)
        lh = templates.line_height(ln.size, ln.bold)
        assert ln.y >= reg.top - 1 and ln.y + lh <= reg.bottom + 1, ln
        if st.round:
            cx, cy, r = reg.circle
            for (x, y) in [(ln.x, ln.y), (ln.x + w, ln.y), (ln.x, ln.y + lh), (ln.x + w, ln.y + lh)]:
                assert math.hypot(x - cx, y - cy) <= r + 2, (ln, x, y)
        else:
            assert ln.x >= reg.left - 1 and ln.x + w <= reg.right + 1, ln


def test_everything_fits_and_stays_inside():
    for t in model.TEMPLATES:
        for sid in templates.ALLOWED_STOCKS[t]:
            key = {"simple": "food", "package": "product", "sticker": "lot", "free": "text",
                   "cottage": "product", "picture": "text"}[t]
            res = render.render(doc_with(t, sid, **{key: "Chicken Noodle Soup"}))
            assert not res.overflow, (t, sid)
            lines_inside(res)
            assert res.image.mode == "1" and res.image.size == (res.stock.w, res.stock.h)


def test_long_word_headline_shrinks_alone():
    short = render.render(doc_with("simple", "large", food="Soup"))
    long = render.render(doc_with("simple", "large", food="Supercalifragilistic"))
    s_size = [ln.size for ln in short.layout.lines if ln.key == "food"][0]
    l_size = [ln.size for ln in long.layout.lines if ln.key == "food"][0]
    assert l_size < s_size
    assert not long.overflow
    # the dates did not shrink because of the long name
    sd = [ln.size for ln in short.layout.lines if ln.key == "use_by"][0]
    ld = [ln.size for ln in long.layout.lines if ln.key == "use_by"][0]
    assert sd == ld


def test_too_much_text_is_reported_not_clipped():
    res = render.render(doc_with("simple", "small", food="Soup", note="word " * 120))
    assert res.overflow
    assert res.problem_field == "note"
    assert "too much writing" in res.message


def test_shrinks_before_giving_up():
    a = render.render(doc_with("simple", "large", food="Soup"))
    b = render.render(doc_with("simple", "large", food="Soup", note="Keep refrigerated please " * 3,
                               contains="Milk, Eggs, Wheat, Soy", made_by="Grandma Jo"))
    assert not b.overflow
    sa = [ln.size for ln in a.layout.lines if ln.key == "made_on"][0]
    sb = [ln.size for ln in b.layout.lines if ln.key == "made_on"][0]
    assert sb < sa


def test_wrap_uses_real_measurement():
    lines, ok = templates.wrap("iiii iiii iiii WWWW", 20, False, lambda i: 120)
    assert ok
    for ln in lines:
        assert templates.text_width(ln, 20, False) <= 120


def test_qr_on_package():
    res = render.render(doc_with("package", "large", product="Jam", qr="https://example.com"))
    assert res.layout.qr is not None
    qx, qy, mod, matrix = res.layout.qr
    assert qx + mod * len(matrix) <= 812 - 24
    for ln in res.layout.lines:
        if ln.y < qy + mod * len(matrix):
            assert ln.x + templates.text_width(ln.text, ln.size, ln.bold) <= qx


def test_kitchen_name_only_when_enabled():
    d = doc_with("simple", "large", food="Soup")
    ctx = {"kitchen_name": "High Thyme Kitchen"}
    assert not any("High Thyme" in ln.text for ln in render.render(d, ctx).layout.lines)
    d.fields["kitchen"] = True
    assert any("High Thyme" in ln.text for ln in render.render(d, ctx).layout.lines)


def test_test_label():
    img = render.render_text_label(["Hello!", "Your printer works."], stocks.get("small"))
    assert img.size == (256, 200) and img.getbbox() is not None
