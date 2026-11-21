"""Print settings per printer: plain-word settings mapped to TSPL/ZPL, nudging
and turning the picture, ranges, persistence, and no change when untouched."""
from PIL import Image

from food_labeler import printers, printsettings, settings as settings_mod, stocks, tspl, zpl

LARGE = stocks.get("large")
TSPL = {"kind": "tspl", "method": "device", "target": "/dev/null"}
ZPL = {"kind": "zpl", "method": "device", "target": "/dev/null"}
ADV = {"density": {}, "speed": {}, "gap": {}, "invert": False, "zpl_darkness": None}


def label(stock=LARGE):
    img = Image.new("1", (stock.w, stock.h), 1)
    img.paste(0, (100, 50, 140, 90))
    return img


def header(job: bytes) -> list[str]:
    return job.split(b"BITMAP", 1)[0].decode("ascii").split("\r\n")


def test_untouched_settings_change_nothing():
    img = label()
    for cfg in (TSPL, ZPL):
        for st in (LARGE, stocks.get("round"), stocks.get("small", 300)):
            im = label(st)
            want = printers.build_job(im, st, cfg, ADV, 3)
            assert printers.build_job(im, st, cfg, ADV, 3, print_settings={}) == want
            assert printers.build_job(im, st, cfg, ADV, 3, print_settings=None) == want
            assert printers.build_job(im, st, cfg, ADV, 3,
                                      print_settings={"junk": 1, "after": "x"}) == want
    assert printsettings.adjust_image(img, LARGE, {}) is img
    assert printsettings.clean({"nudge_x": 0, "upside_down": False}) == {}


def test_clean_clamps():
    c = printsettings.clean({"darkness": 99, "zpl_darkness": -99, "speed": 0, "zpl_speed": 9,
                             "nudge_x": 7.3, "nudge_y": -1.26, "gap": {"large": 50, "a4": 3},
                             "media": "mark", "after": "feed", "feed_mm": 40,
                             "upside_down": True})
    assert c == {"darkness": 15, "zpl_darkness": -30, "speed": 1, "zpl_speed": 6,
                 "nudge_x": 5.0, "nudge_y": -1.5, "gap": {"large": 10.0}, "media": "mark",
                 "after": "feed", "feed_mm": 10.0, "upside_down": True}
    assert printsettings.clean({"darkness": True, "media": "foil"}) == {}
    assert printsettings.clean({"after": "feed"})["feed_mm"] == printsettings.DEFAULT_FEED_MM


def test_tspl_mapping():
    img = label()
    h = header(printers.build_job(img, LARGE, TSPL, ADV, 1, print_settings={
        "darkness": 12, "speed": 2, "gap": {"large": 2.5}}))
    assert h[:7] == ["SIZE 101.6 mm,50.8 mm", "GAP 2.5 mm,0 mm", "DIRECTION 1,0",
                     "REFERENCE 0,0", "DENSITY 12", "SPEED 2", "CLS"]
    h = header(printers.build_job(img, LARGE, TSPL, ADV, 1, print_settings={"media": "mark"}))
    assert h[1] == "BLINE 3 mm,0 mm"
    h = header(printers.build_job(img, LARGE, TSPL, ADV, 1,
                                  print_settings={"media": "continuous"}))
    assert h[1] == "GAP 0 mm,0 mm"
    h = header(printers.build_job(img, LARGE, TSPL, ADV, 1, print_settings={"after": "feed"}))
    assert h[2] == "OFFSET 3 mm"
    h = header(printers.build_job(img, LARGE, TSPL, ADV, 1, print_settings={
        "after": "feed", "feed_mm": 6.5}))
    assert h[2] == "OFFSET 6.5 mm"
    h = header(printers.build_job(img, LARGE, TSPL, ADV, 1, print_settings={"after": "tear"}))
    assert h[2] == "OFFSET 0 mm"
    # the printer's settings win over the older Advanced (per size) ones
    adv = dict(ADV, density={"large": 4}, speed={"large": 5})
    h = header(printers.build_job(img, LARGE, TSPL, adv, 1))
    assert "DENSITY 4" in h and "SPEED 5" in h
    h = header(printers.build_job(img, LARGE, TSPL, adv, 1, print_settings={"darkness": 9}))
    assert "DENSITY 9" in h and "SPEED 5" in h


def test_zpl_mapping():
    img = label()
    z = printers.build_job(img, LARGE, ZPL, ADV, 2, print_settings={
        "zpl_darkness": -10, "zpl_speed": 5, "media": "mark", "after": "feed"}).decode()
    assert "^MD-10\n^PR5\n^MNM\n^TA024\n^FO0,0^GFA" in z          # 3 mm at 203 dpi = 24 dots
    z = printers.build_job(label(stocks.get("large", 300)), stocks.get("large", 300), ZPL, ADV,
                           1, print_settings={"after": "tear", "media": "continuous"}).decode()
    assert "^MNN\n^TA000\n" in z
    z = printers.build_job(img, LARGE, ZPL, dict(ADV, zpl_darkness=12), 1).decode()
    assert "^MD12\n" in z and "^MN" not in z and "^TA" not in z
    assert "^MD30\n^PR6\n" in zpl.build_job(img, LARGE, 1, darkness=99, speed=9).decode()


def test_nudge_and_upside_down():
    st = LARGE
    img = label()
    moved = printsettings.adjust_image(img, st, {"nudge_x": 1.0, "nudge_y": -0.5})
    assert moved.size == img.size
    assert moved.getpixel((108, 46)) == 0 and moved.getpixel((107, 46)) != 0   # +8, -4 dots
    assert moved.getpixel((147, 85)) == 0 and moved.getpixel((148, 85)) != 0
    turned = printsettings.adjust_image(img, st, {"upside_down": True})
    assert turned.getpixel((st.w - 1 - 100, st.h - 1 - 50)) == 0
    both = printsettings.adjust_image(img, st, {"nudge_x": 1.0, "upside_down": True})
    # nudged right on the finished label = left in the turned picture
    assert both.getpixel((st.w - 1 - 108, st.h - 1 - 50)) == 0
    assert both.getpixel((st.w - 1 - 100 + 1, st.h - 1 - 50)) != 0
    big = printsettings.adjust_image(img, stocks.get("large", 300), {"nudge_x": 1.0})
    assert big.getpixel((112, 60)) == 0 and big.getpixel((111, 60)) != 0       # 12 dots at 300


def test_darkness_test_and_feed_jobs():
    job, levels = printers.darkness_test_job(LARGE, TSPL, ADV)
    assert [v for _w, v in levels] == [5, 8, 11]
    assert job.count(b"PRINT 1,1") == 3
    assert [b"DENSITY %d" % v in job for v in (5, 8, 11)] == [True] * 3
    job, levels = printers.darkness_test_job(LARGE, ZPL, ADV, print_settings={
        "zpl_darkness": 25})
    assert [v for _w, v in levels] == [15, 25, 30]
    assert job.count(b"^XA") == 3 and b"^MD15\n" in job and b"^MD30\n" in job
    assert printers.feed_job(LARGE, TSPL, ADV).endswith(b"FORMFEED\r\n")
    assert b"BLINE" in printers.feed_job(LARGE, TSPL, ADV, {"media": "mark"})
    assert printers.feed_job(LARGE, ZPL, ADV) == b"~PH\n"
    assert tspl.feed_job(LARGE).startswith(b"SIZE 101.6 mm,50.8 mm\r\nGAP 3 mm,0 mm\r\n")


def test_effective_values():
    assert printsettings.effective_darkness("tspl", LARGE, {}) == 8
    assert printsettings.effective_darkness("zpl", stocks.get("round"), {}) == 8
    assert printsettings.effective_darkness("zpl", LARGE, {"zpl_darkness": -4}) == -4
    assert printsettings.effective_speed("tspl", stocks.get("small"), {}) == 3
    assert printsettings.effective_speed("zpl", LARGE, {"zpl_speed": 4}) == 4


def test_kept_per_printer(tmp_path):
    cfg = settings_mod.Settings(tmp_path / "settings.json")
    cfg.printer_info("usb:1-1.4")["print"] = printsettings.clean({"darkness": 11,
                                                                  "nudge_x": 1.5})
    cfg.save()
    again = settings_mod.Settings(tmp_path / "settings.json")
    assert printsettings.clean(again["printers"]["usb:1-1.4"]["print"]) == {
        "darkness": 11, "nudge_x": 1.5}
    assert "print" not in again.printer_info("usb:1-1.3")
