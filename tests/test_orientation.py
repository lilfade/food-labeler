"""Which way round: a label laid out wide (landscape) or tall (portrait) on any
roll. A turned label is drawn upright and turned a quarter turn to print, so the
printer always gets its roll's size."""
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from food_labeler import (model, pictures, printers, printsettings, qrcodes, render, stocks,
                          templates, tspl, zpl)

import render_cases
from test_placements import LOGO, check

RECT = [s for s in stocks.ORDER if not stocks.STOCKS[s].round]


def doc(stock="large", way="", template="simple"):
    d = model.LabelDoc(template, stock, model.default_fields(template))
    d.fields.update(food="Lemon Bars", contains="Milk, Eggs", note="Keep refrigerated")
    if way:
        d.set_orientation(way)
    return d


def other(stock_id):
    return "tall" if stocks.natural(stocks.STOCKS[stock_id]) == "wide" else "wide"


def ink_box(img):
    return img.convert("L").point(lambda v: 255 - v).getbbox()


def test_the_rolls_own_way_is_the_default():
    assert [stocks.natural(stocks.STOCKS[s]) for s in stocks.ORDER] == \
        ["wide", "wide", "wide", "", "tall"]
    for sid in RECT:
        d = doc(sid)
        assert d.orientation == "" and d.effective_orientation() == stocks.natural(
            stocks.STOCKS[sid])
        d.set_orientation(stocks.natural(stocks.STOCKS[sid]))
        assert d.orientation == ""                         # the roll's way: nothing stored
        plain = render.render(doc(sid))
        same = render.render(d)
        assert not same.turned and same.image.tobytes() == plain.image.tobytes()


def test_round_labels_have_no_way_round():
    d = doc("round", "tall")
    assert d.effective_orientation() == ""
    d.orientation = "tall"                                  # even if a file says so
    res = render.render(d)
    assert not res.turned and res.image.size == (406, 405)


@pytest.mark.parametrize("dpi", [203, 300])
@pytest.mark.parametrize("sid", RECT)
def test_turned_bitmap_is_the_rolls_size(sid, dpi):
    d = doc(sid, other(sid))
    res = render.render(d, dpi=dpi)
    st = stocks.get(sid, dpi)
    assert res.turned and res.stock is st
    assert res.image.size == (st.w, st.h) and res.image.mode == "1"
    assert res.upright.size == (st.h, st.w)
    assert res.layout_stock.w == st.h and res.layout_stock.h == st.w
    assert res.image.tobytes() == res.upright.transpose(Image.Transpose.ROTATE_270).tobytes()
    assert not res.overflow


def test_text_is_upright_in_the_preview_and_sideways_on_the_roll():
    d = model.LabelDoc("free", "large", {"text": "MMMMMMMM"})
    d.set_orientation("tall")
    res = render.render(d)
    x0, y0, x1, y1 = ink_box(res.upright)
    assert x1 - x0 > y1 - y0                       # reads left to right when upright
    x0, y0, x1, y1 = ink_box(res.image)
    assert y1 - y0 > x1 - x0                       # runs down the roll when printed
    pv = render.preview(res, 600, 600, highlight=False)
    # the label in the preview is tall (paper-white area)
    paper = pv.convert("L").point(lambda v: 255 if v == 255 else 0).getbbox()
    assert paper[3] - paper[1] > paper[2] - paper[0]
    assert "left side" in render.out_edge_words(res)
    assert "right side" in render.out_edge_words(res, upside_down=True)
    assert render.out_edge_words(render.render(doc())) == ""


def test_save_as_picture_is_upright(tmp_path):
    res = render.render(doc("large", "tall"))
    render.export_png(res, tmp_path / "x.png")
    assert Image.open(tmp_path / "x.png").size == (800, 1624)


@pytest.mark.parametrize("dpi", [203, 300])
def test_print_jobs_of_a_turned_label(dpi):
    res = render.render(doc("large", "tall"), dpi=dpi)
    st = res.stock
    job = tspl.build_job(res.image, st, 1)
    assert f"SIZE {tspl.mm(st.w_mm)} mm,{tspl.mm(st.h_mm)} mm".encode() in job
    assert f"BITMAP 0,0,{(st.w + 7) // 8},{st.h},0,".encode() in job
    zjob = zpl.build_job(res.image, st, 1)
    assert f"^PW{st.w}\n^LL{st.h}".encode() in zjob
    back = zpl.decode_gfa(zjob).crop((0, 0, st.w, st.h))
    assert back.tobytes() == res.image.tobytes()


def test_nudge_and_upside_down_still_work():
    res = render.render(doc("large", "tall"))
    st = res.stock
    up = printsettings.adjust_image(res.image, st, {"upside_down": True})
    assert up.size == res.image.size
    assert up.tobytes() == res.image.transpose(Image.Transpose.ROTATE_180).tobytes()
    moved = printsettings.adjust_image(res.image, st, {"nudge_x": 2.0})
    assert moved.size == res.image.size and moved.tobytes() != res.image.tobytes()
    job = printers.build_job(moved, st, {"kind": "tspl"}, {}, 1)
    assert b"BITMAP 0,0,102,400,0," in job


@pytest.mark.parametrize("sid", RECT)
def test_pictures_and_qr_codes_on_turned_labels(sid):
    for pp, qp in [("above", "bottom"), ("left", "corner_right"),
                   ("corner_bottom_left", "right"), ("bottom", "corner")]:
        d = doc(sid, other(sid))
        d.picture = dict(LOGO, place=pp, size=25)
        d.qr = dict(qrcodes.DEFAULTS, value="example.com", place=qp, size=25)
        res = render.render(d)
        check(SimpleNamespace(layout=res.layout, stock=res.layout_stock), (sid, pp, qp))


@pytest.mark.parametrize("dpi", [203, 300])
def test_qr_code_still_scans_after_turning(dpi):
    zxingcpp = pytest.importorskip("zxingcpp")
    d = doc("large", "tall")
    d.qr = dict(qrcodes.DEFAULTS, value="example.com/menu", place="bottom", size=40)
    res = render.render(d, dpi=dpi)
    assert not res.overflow
    for img in (res.image, res.upright):
        got = [r.text for r in zxingcpp.read_barcodes(img.convert("L"))]
        assert got == ["https://example.com/menu"]


def test_picture_label_turned():
    d = model.LabelDoc("picture", "xl", {"text": "Thank you"})
    d.picture = dict(LOGO, place="fit", size=100)
    d.set_orientation("wide")
    res = render.render(d)
    assert res.turned and res.image.size == (812, 1218) and res.upright.size == (1218, 812)
    assert not res.overflow


def test_cottage_wording_keeps_its_size_turned():
    rules = render_cases.cottage.CottageRules()
    ctx = render_cases._ctx(rules, "NE")
    mins = {"statement:" + s["id"]: s["min_pt"]
            for s in ctx["cottage"]["rule"]["statements"] if s.get("min_pt")}
    for sid, way in (("xl", "wide"), ("large", "tall")):
        d = model.LabelDoc("cottage", sid, model.default_fields("cottage"))
        d.fields.update(render_cases.SAMPLE["cottage"])
        d.set_orientation(way)
        res = render.render(d, ctx)
        assert res.turned
        for ln in res.layout.lines:
            if ln.key in mins:
                assert ln.size * 72 / 203 >= mins[ln.key] - 1e-9
        if res.overflow:                             # never made smaller to fit: said so
            assert "doesn't fit" in res.message


def test_orientation_in_label_files(tmp_path):
    d = doc("large", "tall")
    path = model.save(d, tmp_path / "tall")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["orientation"] == "tall" and data["version"] == 1
    back = model.load(path)
    assert back.orientation == "tall" and back.copy().orientation == "tall"
    assert render.render(back).image.tobytes() == render.render(d).image.tobytes()
    plain = doc("large")
    assert "orientation" not in plain.to_dict()               # old files stay byte for byte
    data = plain.to_dict()
    data["orientation"] = "sideways"
    assert model.LabelDoc.from_dict(data).orientation == ""
    d.set_template("package")
    assert d.orientation == "tall"                            # kept when the kind changes


def test_snapshot_keeps_orientation():
    d = doc("xl", "wide")
    assert model.LabelDoc.from_snapshot(d.snapshot()).orientation == "wide"


def test_new_after_a_restored_session_is_a_clean_label(tmp_path):
    """New: a clean default label of the same kind and size, nothing carried over."""
    from food_labeler import settings as settings_mod
    from food_labeler.app import App
    old = doc("large", "tall", template="simple")
    old.picture = dict(LOGO, place="left", size=50)
    old.qr = dict(qrcodes.DEFAULTS, value="example.com")
    old.lettering = {}
    settings_mod.write_autosave(old, None, True)
    restored, _path, dirty = settings_mod.read_autosave()
    assert restored.picture and restored.qr and restored.orientation == "tall" and dirty
    cfg = settings_mod.Settings()
    fake = SimpleNamespace(cfg=cfg, _fill_kitchen=lambda d: App._fill_kitchen(fake, d))
    new = App._fresh_doc(fake, restored.template, restored.stock)
    assert new.template == "simple" and new.stock == "large"
    assert new.picture is None and new.qr is None and new.orientation == ""
    assert new.fields == model.default_fields("simple")
    assert pictures.clean(new.picture) is None
    assert render.render(new).image.size == (812, 400) and not render.render(new).turned
    assert templates.layout(new, stocks.get("large")).images == []
