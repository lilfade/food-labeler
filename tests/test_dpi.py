"""Printer resolution: 203 dpi stays exactly as before, 300 dpi is the same label
with more dots (layout in physical units), per-printer dpi detection and choice."""
import json

import pytest
from PIL import Image

import render_cases
from food_labeler import cottage, known, model, printers, render, stocks, templates, tspl, zpl
from test_printers import FakeWin

K = known.KnownPrinters()


# ---- dot sizes ---------------------------------------------------------------

def test_203_sizes_are_unchanged():
    want = {"small": (256, 200, 0), "medium": (609, 406, 0), "large": (812, 406, 0),
            "round": (406, 405, 382), "xl": (812, 1218, 0)}
    for sid, (w, h, dia) in want.items():
        st = stocks.get(sid)
        assert (st.w, st.h, st.circle_dia, st.dpi) == (w, h, dia, 203)
        assert stocks.get(sid, 203) is st
        assert st.margin == (12 if sid == "small" else 24)


@pytest.mark.parametrize("dpi", [203, 300])
def test_sizes_follow_the_mm(dpi):
    for sid in stocks.ORDER:
        st = stocks.get(sid, dpi)
        assert st.w == stocks.mm_to_dots(st.w_mm, dpi)
        assert st.h == stocks.mm_to_dots(st.h_mm, dpi)
        assert (st.w_mm, st.h_mm, st.gap_mm) == (stocks.get(sid).w_mm, stocks.get(sid).h_mm,
                                                 stocks.get(sid).gap_mm)


def test_300_table():
    got = {sid: (stocks.get(sid, 300).w, stocks.get(sid, 300).h) for sid in stocks.ORDER}
    assert got == {"small": (378, 295), "medium": (900, 600), "large": (1200, 600),
                   "round": (600, 599), "xl": (1200, 1800)}
    rnd = stocks.get("round", 300)
    assert rnd.circle_dia == 565 and rnd.zpl_lt == -4
    assert stocks.get("small", 300).margin == 18 and stocks.get("large", 300).margin == 35


def test_dot_scaling():
    assert [stocks.dots(n) for n in (2, 12, 13, 14, 16, 20, 22, 24, 200)] == \
        [2, 12, 13, 14, 16, 20, 22, 24, 200]
    assert [stocks.dots(n, 300) for n in (2, 12, 13, 14, 16, 20, 22, 24, 200, -3)] == \
        [3, 18, 19, 21, 24, 30, 33, 35, 296, -4]
    for n in range(0, 400):
        assert abs(stocks.dots(n, 300) - n * 300 / 203) <= 0.5
    with pytest.raises(ValueError):
        stocks.get("large", 600)


# ---- 203 dpi output is byte for byte what it was ---------------------------

def test_203_renders_are_byte_identical_to_before():
    base = json.loads(render_cases.BASELINE.read_text(encoding="utf-8"))
    now = render_cases.compute(203)
    assert set(now) == set(base)
    changed = [k for k in base if base[k] != now[k]]
    assert not changed, changed


# ---- 300 dpi ---------------------------------------------------------------

def _docs():
    return render_cases.docs()


def test_300_renders_same_label_more_dots():
    for name, doc, ctx in _docs():
        a = render.render(doc, ctx)
        b = render.render(doc, ctx, dpi=300)
        assert b.stock.dpi == 300 and b.image.size == (b.stock.w, b.stock.h), name
        assert b.image.mode == "1"
        # no new overflow: anything that fits at 203 dpi fits at 300 dpi
        if not a.overflow:
            assert not b.overflow, name
        # each part prints about as big on paper (sizes in dots scale by 300/203)
        if not a.overflow and not b.overflow:
            sa = {ln.key: ln.size for ln in a.layout.lines}
            sb = {ln.key: ln.size for ln in b.layout.lines}
            assert set(sa) == set(sb), name
            for k in sa:
                assert sb[k] / sa[k] >= 0.9 * 300 / 203, (name, k, sa[k], sb[k])


def test_300_lines_stay_inside():
    for name, doc, ctx in _docs():
        res = render.render(doc, ctx, dpi=300)
        if res.overflow:
            continue
        reg = templates.region_for(res.stock)
        for ln in res.layout.lines:
            w = templates.text_width(ln.text, ln.size, ln.bold, ln.font)
            lh = templates.line_height(ln.size, ln.bold, ln.font)
            assert ln.y >= reg.top - 1 and ln.y + lh <= reg.bottom + 1, (name, ln)
            if not res.stock.round:
                assert ln.x >= reg.left - 1 and ln.x + w <= reg.right + 1, (name, ln)


def test_legal_minimum_in_points_holds_at_300():
    rules = cottage.CottageRules()
    checked = 0
    for sid in ("NE", "TX", "CA", "MI"):
        rule = rules.effective(sid).to_ctx()
        mins = {"statement:" + st["id"]: st["min_pt"] for st in rule["statements"]
                if st.get("min_pt")}
        for stock_id in templates.ALLOWED_STOCKS["cottage"]:
            doc = model.LabelDoc("cottage", stock_id, model.default_fields("cottage"))
            doc.fields.update(render_cases.SAMPLE["cottage"])
            res = render.render(doc, render_cases._ctx(rules, sid), dpi=300)
            for ln in res.layout.lines:
                if ln.key in mins:
                    assert ln.size * 72 / 300 >= mins[ln.key] - 1e-9, (sid, stock_id, ln)
                    checked += 1
    assert checked
    assert templates.statement_min_dots({"min_pt": 11}, 300) == 46     # 11 pt at 300 dpi
    assert templates.statement_min_dots({"min_pt": 11}) == 32
    assert templates.statement_min_dots({}, 300) == 18


def test_tspl_and_zpl_at_300():
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"))
    doc.fields["food"] = "Soup"
    res = render.render(doc, {}, dpi=300)
    st = res.stock
    job = tspl.build_job(res.image, st, 1)
    assert job.startswith(b"SIZE 101.6 mm,50.8 mm\r\nGAP 3 mm,0 mm\r\n")
    assert b"BITMAP 0,0,150,600,0," in job
    assert len(job.split(b"BITMAP 0,0,150,600,0,", 1)[1]) == 150 * 600 + len(b"\r\nPRINT 1,1\r\n")
    z = zpl.build_job(res.image, st, 1)
    assert b"^PW1200\n^LL600\n" in z and b"^GFA,90000,90000,150," in z
    assert zpl.decode_gfa(z).crop((0, 0, 1200, 600)).tobytes() == res.image.tobytes()
    rnd = render.render(model.LabelDoc("simple", "round", {"food": "Soup"}), {}, dpi=300)
    z = zpl.build_job(rnd.image, rnd.stock, 1)
    assert b"^PW600\n^LL599\n^LH0,0\n^LT-4\n" in z


def test_head_width_refusal():
    lp = K.defs["lp610bt-compatible"]
    zp = K.defs["zebra-zp450"]
    assert lp.max_width_dots == 812 and zp.max_width_dots == 832
    assert K.defs["zebra-zpl"].max_width_dots == 0
    for sid in stocks.ORDER:
        for dpi in (203, 300):
            assert lp.fits(stocks.get(sid, dpi)) and zp.fits(stocks.get(sid, dpi))
    narrow = known.validate_entry({"id": "two-inch", "name": "Two inch printer",
                                   "language": "tspl", "dpi": 300, "max_width_dots": 600})
    assert narrow.fits(stocks.get("medium", 203)) is False
    assert narrow.fits(stocks.get("round", 300)) and not narrow.fits(stocks.get("large", 300))
    msg = printers.too_wide_message(stocks.get("large"), narrow)
    assert "wider than this printer can print" in msg and "51 mm" in msg
    img = Image.new("1", (812, 406), 1)
    cfg = {"kind": "tspl", "method": "device", "target": "/dev/null"}
    with pytest.raises(printers.PrinterError, match="narrower label"):
        printers.build_job(img, stocks.get("large"), cfg, {}, 1, family=narrow)
    assert printers.too_wide_message(stocks.get("large"), None) == ""


def test_png_export_keeps_the_dpi(tmp_path):
    doc = model.LabelDoc("simple", "medium", {"food": "Soup"})
    for dpi in (203, 300):
        res = render.render(doc, {}, dpi=dpi)
        path = tmp_path / f"label-{dpi}.png"
        render.export_png(res, path)
        with Image.open(path) as im:
            assert im.size == (res.stock.w * 2, res.stock.h * 2)
            got = im.info["dpi"]
            assert round(got[0]) == round(got[1]) == dpi * 2
            # prints at the label's real size: 3 inches wide
            assert abs(im.size[0] / got[0] - 3.0) < 0.01


# ---- per-printer resolution ----------------------------------------------------

def test_definitions_have_dpi():
    assert K.defs["lp610bt-compatible"].dpi == 203
    assert K.defs["zebra-zp450"].dpi == 203


@pytest.mark.parametrize("text,want", [
    ("ZDesigner ZD421-300dpi ZPL", 300), ("ZDesigner ZT230-300dpi ZPL", 300),
    ("Zebra ZD620 300 dpi", 300), ("TSC TE310-300", 300), ("ZTC ZP 450-200dpi", 203),
    ("ZDesigner GK420d", None), ("4B-LP610BT", None), ("Zebra ZT-3000", None), ("", None)])
def test_dpi_from_text(text, want):
    assert printers.dpi_from_text(text) == want


def test_detect_from_windows_names():
    found = printers.discover_windows(FakeWin([
        {"pPrinterName": "ZDesigner ZD421-300dpi ZPL", "pDriverName": "ZDesigner ZD421-300dpi ZPL",
         "pPortName": "USB001"},
        {"pPrinterName": "Kitchen labels", "pDriverName": "ZDesigner ZT230-300dpi ZPL",
         "pPortName": "USB002"},
        {"pPrinterName": "ZDesigner ZP 450-200dpi", "pDriverName": "ZDesigner ZP 450-200dpi",
         "pPortName": "USB003"},
        {"pPrinterName": "4B-LP610BT", "pDriverName": "4BARCODE 4B-LP610BT", "pPortName": "USB004"},
        {"pPrinterName": "Mystery", "pDriverName": "Generic / Text Only", "pPortName": "USB005"},
    ]), known=K)
    by = {p.target: p.dpi for p in found}
    assert by == {"ZDesigner ZD421-300dpi ZPL": 300, "Kitchen labels": 300,
                  "ZDesigner ZP 450-200dpi": 203, "4B-LP610BT": 203, "Mystery": 203}


def test_detect_from_1284_model():
    info = printers.parse_1284("MANUFACTURER:Zebra Technologies;COMMAND SET:ZPL;"
                               "MODEL:ZTC ZD421-300dpi ZPL;")
    p = printers.Printer(id="usb:1-1", model=printers.model_from_1284(info), vidpid="0a5f:0000")
    printers.classify(p, K, info, p.model)
    assert p.kind == "zpl" and p.family.id == "zebra-zpl" and p.dpi == 300
    info = printers.parse_1284("MANUFACTURER:Zebra Technologies;COMMAND SET:ZPL;"
                               "MODEL:ZTC ZP 450-200dpi;")
    p = printers.Printer(id="usb:1-2", model=printers.model_from_1284(info))
    printers.classify(p, K, info, p.model)
    assert p.family.id == "zebra-zp450" and p.dpi == 203


def test_definition_dpi_is_the_default(tmp_path):
    upd = {"format": "food-labeler-printers", "version": 1, "printers": [
        {"id": "sharp-one", "name": "Sharp label printer", "language": "tspl", "dpi": 300,
         "max_width_dots": 1248, "usb": ["1234:5678"]}]}
    f = tmp_path / "upd.json"
    f.write_text(json.dumps(upd), encoding="utf-8")
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    (tmp_path / "data").mkdir()
    k.import_file(f)
    saved = json.loads((tmp_path / "data" / "known_printers.json").read_text(encoding="utf-8"))
    assert saved["printers"][0]["dpi"] == 300 and saved["printers"][0]["max_width_dots"] == 1248
    k2 = known.KnownPrinters(user_dir=tmp_path / "data")
    d = k2.defs["sharp-one"]
    assert d.dpi == 300 and d.max_width_dots == 1248
    p = printers.Printer(id="usb:1-3", model="SL-1", vidpid="1234:5678")
    printers.classify(p, k2, {}, "SL-1")
    assert p.family is d and p.dpi == 300
    # an old-style user file (no max_width_dots) still loads
    assert "max_width_dots" not in known._to_json(K.defs["zebra-zpl"])


def test_user_choice_wins_and_no_printer_is_203():
    p = printers.Printer(id="usb:1-1", kind="tspl")
    assert p.dpi == 203
    assert printers.printer_dpi(None) == 203
    assert printers.printer_dpi(p) == 203
    assert printers.printer_dpi(p, {"dpi": 300}) == 300
    p.dpi = 300
    assert printers.printer_dpi(p) == 300
    assert printers.printer_dpi(p, {"dpi": 203}) == 203
    for junk in (600, "300", True, None, 0):
        assert printers.printer_dpi(p, {"dpi": junk}) == 300


def test_label_files_never_store_dpi(tmp_path):
    doc = model.LabelDoc("simple", "large", {"food": "Soup"})
    before = doc.dumps()
    render.render(doc, {}, dpi=300)
    assert doc.dumps() == before and "dpi" not in before
    assert json.loads(before)["version"] == 1
