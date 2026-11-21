"""Setting up a new roll: the job for each printer language and kind of roll,
the OK question before anything is sent, the line-up label, the "New roll?"
notice and what is remembered per printer, and that nothing is ever sent
without a click."""
import ast
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from food_labeler import calibrate, known, printers, printsettings, settings as settings_mod
from food_labeler import stocks, tspl, zpl

ROOT = Path(__file__).resolve().parents[1]
LARGE = stocks.get("large")
TSPL = {"kind": "tspl", "method": "device", "target": "/dev/null"}
ZPL = {"kind": "zpl", "method": "device", "target": "/dev/null"}
ADV = {"density": {}, "speed": {}, "gap": {}, "invert": False, "zpl_darkness": None}


def jobs_written(tmp_path):
    d = tmp_path / "jobs"
    return sorted(d.iterdir()) if d.is_dir() else []


# ---------------------------------------------------------------- job bytes

def test_tspl_gap_job_is_unchanged():
    want = b"SIZE 101.6 mm,50.8 mm\r\nGAP 3 mm,0 mm\r\nGAPDETECT\r\n"
    assert tspl.calibrate_job(LARGE) == want                     # as in 1.2.0
    assert calibrate.setup_job("tspl", LARGE, "gap") == want
    assert calibrate.setup_job("", LARGE, "gap") == want         # unknown type: TSPL
    assert calibrate.setup_job("tspl", stocks.get("medium"), "gap", 2.5) == (
        b"SIZE 76.2 mm,50.8 mm\r\nGAP 2.5 mm,0 mm\r\nGAPDETECT\r\n")


def test_tspl_mark_and_continuous_jobs():
    assert calibrate.setup_job("tspl", LARGE, "mark") == (
        b"SIZE 101.6 mm,50.8 mm\r\nBLINE 3 mm,0 mm\r\nBLINEDETECT\r\n")
    assert calibrate.setup_job("tspl", LARGE, "continuous") == (
        b"SIZE 101.6 mm,50.8 mm\r\nGAP 0 mm,0 mm\r\n")
    assert b"DETECT" not in calibrate.setup_job("tspl", stocks.get("small"), "continuous")
    assert calibrate.setup_job("tspl", LARGE, "foil") == calibrate.setup_job("tspl", LARGE)


def test_zpl_jobs():
    assert calibrate.setup_job("zpl", LARGE, "gap") == b"^XA^MNW^XZ\n~JC\n"
    assert calibrate.setup_job("zpl", LARGE, "mark") == b"^XA^MNM^XZ\n~JC\n"
    assert calibrate.setup_job("zpl", LARGE, "continuous") == b"^XA^MNN^PW812^LL400^XZ\n"
    assert calibrate.setup_job("zpl", stocks.get("large", 300), "continuous") == (
        b"^XA^MNN^PW1200^LL591^XZ\n")
    for m in ("gap", "mark", "continuous"):
        assert b"^JUS" not in calibrate.setup_job("zpl", LARGE, m)   # never saved for good


def test_setup_job_uses_this_printers_gap_and_media():
    ps = {"gap": {"large": 2.0}, "media": "mark"}
    assert calibrate.setup_job_for(LARGE, TSPL, ADV, None, ps) == (
        b"SIZE 101.6 mm,50.8 mm\r\nBLINE 2 mm,0 mm\r\nBLINEDETECT\r\n")
    adv = dict(ADV, gap={"large": 4.0})
    assert b"GAP 4 mm,0 mm\r\nGAPDETECT" in calibrate.setup_job_for(LARGE, TSPL, adv, "gap")
    assert calibrate.setup_job_for(LARGE, ZPL, ADV, None, ps) == b"^XA^MNM^XZ\n~JC\n"


# ---------------------------------------------------------------- confirmation

def test_nothing_sent_without_ok(tmp_path):
    sent = []
    data = calibrate.setup_job("tspl", LARGE)
    for answer in (False, None, "yes", 1):
        assert calibrate.send_setup(TSPL, data, lambda a=answer: a,
                                    send=lambda c, d: sent.append(d)) is False
    assert sent == []
    assert calibrate.send_setup(TSPL, data, lambda: True,
                                send=lambda c, d: sent.append(d)) is True
    assert sent == [data]


def test_ok_sends_through_the_normal_path(tmp_path):
    asked = []
    data = calibrate.setup_job("zpl", LARGE)
    assert calibrate.send_setup(ZPL, data, lambda: asked.append(1) or False) is False
    assert jobs_written(tmp_path) == [] and asked == [1]
    assert calibrate.send_setup(ZPL, data, lambda: True) is True       # dry run: a file
    files = jobs_written(tmp_path)
    assert len(files) == 1 and files[0].read_bytes() == data


def test_question_says_it_uses_labels():
    assert "2–4 blank labels" in calibrate.confirm_text("gap")
    assert "2–4 blank labels" in calibrate.confirm_text("mark")
    assert "doesn't feed" in calibrate.confirm_text("continuous")


# ---------------------------------------------------------------- line-up label

@pytest.mark.parametrize("dpi", [203, 300])
@pytest.mark.parametrize("sid", stocks.ORDER)
def test_lineup_label(sid, dpi):
    st = stocks.get(sid, dpi)
    img = calibrate.lineup_label_image(st)
    assert img.size == (st.w, st.h) and img.mode == "1"
    one = stocks.mm_to_dots(1.0, dpi)
    assert one == (8 if dpi == 203 else 12)
    if not st.round:
        # the box is drawn 1 mm inside every edge; the edge itself stays paper
        assert img.getpixel((one, st.h // 2)) == 0
        assert img.getpixel((st.w - 1 - one, st.h // 2)) == 0
        assert img.getpixel((st.w // 2, one)) == 0
        assert img.getpixel((st.w // 2, st.h - 1 - one)) == 0
        assert img.getpixel((one - 2, st.h // 2)) != 0
    else:
        cx, cy = st.circle_center
        assert img.getpixel((int(cx), int(cy - st.circle_dia / 2 + one + 1))) == 0
    assert img.getpixel((0, 0)) != 0
    # the arrow: solid near the top middle
    col = [img.getpixel((st.w // 2, y)) for y in range(st.h // 3)]
    assert col.count(0) > st.d(10)


def test_lineup_words():
    assert calibrate.lineup_lines(LARGE)[0] == "Test: Large 4 × 2 inches"
    assert "circle" in calibrate.lineup_lines(stocks.get("round"))[1]


def test_lineup_job_uses_print_settings():
    plain = calibrate.lineup_label_job(LARGE, TSPL, ADV)
    assert plain.startswith(b"SIZE 101.6 mm,50.8 mm\r\nGAP 3 mm,0 mm\r\n")
    assert plain.endswith(b"PRINT 1,1\r\n")
    img = printsettings.adjust_image(calibrate.lineup_label_image(LARGE), LARGE,
                                     {"upside_down": True, "nudge_x": 1})
    turned = calibrate.lineup_label_job(LARGE, TSPL, ADV, None,
                                        {"upside_down": True, "nudge_x": 1, "darkness": 12,
                                         "media": "mark"})
    assert turned == printers.build_job(img, LARGE, TSPL, ADV, 1, None,
                                        {"upside_down": True, "nudge_x": 1, "darkness": 12,
                                         "media": "mark"})
    assert b"DENSITY 12" in turned and b"BLINE" in turned and turned != plain
    st300 = stocks.get("large", 300)
    z = calibrate.lineup_label_job(st300, ZPL, ADV, None, {"media": "continuous"})
    assert b"^PW1200\n^LL591\n" in z and b"^MNN" in z
    back = zpl.decode_gfa(z).crop((0, 0, st300.w, st300.h))
    assert back.tobytes() == calibrate.lineup_label_image(st300).tobytes()


def test_lineup_too_wide_is_refused():
    fam = known.KnownPrinters().defs["lp610bt-compatible"]
    narrow = known.Definition(id="n", name="N", language="tspl", max_width_dots=400)
    calibrate.lineup_label_job(LARGE, TSPL, ADV, fam)
    with pytest.raises(printers.PrinterError):
        calibrate.lineup_label_job(LARGE, TSPL, ADV, narrow)


# ---------------------------------------------------------------- words

def test_by_hand_text_per_family():
    k = known.KnownPrinters()
    lp, zp = k.defs["lp610bt-compatible"], k.defs["zebra-zp450"]
    assert "3 seconds" in calibrate.by_hand(lp) and "4 labels" in calibrate.by_hand(lp)
    assert "twice" in calibrate.by_hand(zp)
    assert calibrate.by_hand(None) == calibrate.GENERIC_BY_HAND
    assert calibrate.by_hand(known.Definition(id="x", name="X", language="tspl")) == \
        calibrate.GENERIC_BY_HAND
    assert calibrate.still_not_right(zp).startswith("If it still isn't right: ")
    h = calibrate.help_text(lp, "tspl", "mark")
    assert "Nudge the print" in h and "Set it up" in h and calibrate.MARK_UNVERIFIED in h
    assert calibrate.by_hand(lp) in h
    assert calibrate.MARK_UNVERIFIED not in calibrate.help_text(zp, "zpl", "mark")
    assert calibrate.GENERIC_BY_HAND in calibrate.help_text(None)


# ---------------------------------------------------------------- remembered per printer

def test_notice_logic():
    info = {}
    assert not calibrate.show_notice(info, "large")         # nothing set up yet: no notice
    calibrate.remember_roll(info, "large", "gap", dt.date(2026, 11, 20))
    assert info["roll"] == {"stock": "large", "media": "gap", "date": "2026-11-20",
                            "same": []}
    assert not calibrate.show_notice(info, "large")         # same as the roll set up
    assert calibrate.show_notice(info, "medium")            # differs: offer to set up
    calibrate.dismiss_notice(info, "medium")                # "No, same roll"
    assert not calibrate.show_notice(info, "medium")
    assert calibrate.show_notice(info, "small")             # remembered per size
    calibrate.dismiss_notice(info, "medium")
    assert info["roll"]["same"] == ["medium"]
    calibrate.remember_roll(info, "small", "mark")          # a new roll forgets "same"
    assert calibrate.show_notice(info, "medium") and not calibrate.show_notice(info, "small")
    assert calibrate.last_roll(info)["media"] == "mark"


def test_notice_survives_bad_settings():
    for bad in ({"roll": "x"}, {"roll": {"stock": "a4"}}, {"roll": None}, None):
        assert calibrate.last_roll(bad) is None
        assert not calibrate.show_notice(bad, "large")
    r = calibrate.last_roll({"roll": {"stock": "large", "media": "foil", "same": "x"}})
    assert r == {"stock": "large", "media": "gap", "date": "", "same": []}
    info = {}
    calibrate.dismiss_notice(info, "large")                 # nothing to dismiss
    assert info == {}


def test_kept_per_printer(tmp_path):
    cfg = settings_mod.Settings(tmp_path / "settings.json")
    calibrate.remember_roll(cfg.printer_info("usb:1-1.4"), "medium", "gap",
                            dt.date(2026, 11, 20))
    calibrate.remember_roll(cfg.printer_info("usb:1-1.2"), "xl", "continuous",
                            dt.date(2026, 11, 19))
    calibrate.dismiss_notice(cfg.printer_info("usb:1-1.4"), "large")
    cfg.save()
    again = settings_mod.Settings(tmp_path / "settings.json")
    white = again["printers"]["usb:1-1.4"]
    zebra = again["printers"]["usb:1-1.2"]
    assert calibrate.last_roll(white) == {"stock": "medium", "media": "gap",
                                          "date": "2026-11-20", "same": ["large"]}
    assert calibrate.last_roll(zebra)["stock"] == "xl"
    assert not calibrate.show_notice(white, "large") and calibrate.show_notice(zebra, "large")
    assert calibrate.last_roll(again.printer_info("usb:1-1.3")) is None


# ---------------------------------------------------------------- known_printers.json

def _entry(**kw):
    e = {"id": "x", "name": "X", "language": "tspl"}
    e.update(kw)
    return {"format": "food-labeler-printers", "version": 1, "printers": [e]}


def test_known_field_valid_and_round_trips(tmp_path):
    p = tmp_path / "u.json"
    p.write_text(json.dumps(_entry(calibrate_by_hand="  Hold the feed button.  ")))
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    k.import_file(p)
    assert k.defs["x"].calibrate_by_hand == "Hold the feed button."
    saved = json.loads((tmp_path / "data" / "known_printers.json").read_text())
    assert saved["printers"][0]["calibrate_by_hand"] == "Hold the feed button."
    assert known.parse_file_text(json.dumps(_entry()))[0].calibrate_by_hand == ""
    for d in known.KnownPrinters().all():                   # every bundled model has one
        assert d.calibrate_by_hand


@pytest.mark.parametrize("bad", [5, ["a"], "x" * (known.MAX_BY_HAND + 1), "a\x00b", None])
def test_known_field_rejected(tmp_path, bad):
    p = tmp_path / "u.json"
    p.write_text(json.dumps(_entry(calibrate_by_hand=bad)))
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    with pytest.raises(known.DefinitionError, match="calibrate_by_hand"):
        k.import_file(p)
    assert not (tmp_path / "data" / "known_printers.json").exists()


# ---------------------------------------------------------------- never by surprise

SENDERS = {"_start_print", "setup_roll", "print_text_label", "print_now"}
AUTOMATIC = ["__init__", "_build", "_restore_session", "set_found", "select_printer",
             "refresh_printer_combo", "refresh_roll_notice", "_sync_ui_from_doc", "pick_stock",
             "rescan_printers", "_poll_scan", "_menu_picked", "set_doc", "open_path",
             "_same_roll", "render_now", "_autosave_tick", "refresh_status"]


def _app_calls():
    tree = ast.parse((ROOT / "food_labeler" / "app.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
    calls = {}
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        names = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                v = n.func.value
                if isinstance(v, ast.Name) and v.id in ("self", "printers", "calibrate"):
                    names.add(n.func.attr if v.id == "self" else f"{v.id}.{n.func.attr}")
        calls[fn.name] = names
    return calls


def test_nothing_sent_on_start_or_printer_change():
    """No method that runs by itself (start-up, discovery, picking a printer or a
    size, the notice) can reach a send; only button handlers can."""
    calls = _app_calls()
    for start in AUTOMATIC:
        assert start in calls, start
        seen, todo = set(), [start]
        while todo:
            f = todo.pop()
            if f in seen:
                continue
            seen.add(f)
            for c in calls.get(f, ()):
                assert c not in SENDERS and c not in ("printers.send", "calibrate.send_setup"), \
                    f"{start} → {f} → {c}"
                if c in calls:
                    todo.append(c)
    # and the set-up window is reached only from a click
    callers = {f for f, cs in calls.items() if "setup_roll" in cs}
    assert callers == {"_roll_notice_clicked"}


def test_notice_widget_logic_sends_nothing(tmp_path, monkeypatch):
    from food_labeler import app as app_mod

    def boom(*a, **k):
        raise AssertionError("nothing may be sent")
    monkeypatch.setattr(printers, "send", boom)

    class W:
        def __init__(self):
            self.shown, self.text = False, ""

        def grid(self, **k):
            self.shown = True

        def grid_remove(self):
            self.shown = False

        def configure(self, **k):
            self.text = k.get("text", self.text)

    cfg = settings_mod.Settings(tmp_path / "s.json")
    p = printers.Printer("usb:1-1.4", kind="tspl", method="device", target="/dev/null")
    cfg["selected"] = p.id
    cfg.printer_info(p.id)["nickname"] = "White label printer"
    fake = SimpleNamespace(cfg=cfg, found=[p], doc=SimpleNamespace(stock="large"),
                           roll_notice=W(), roll_lbl=W())
    fake.current_printer = lambda: app_mod.App.current_printer(fake)
    fake.printer_name = lambda q: app_mod.App.printer_name(fake, q)
    fake.refresh_roll_notice = lambda: app_mod.App.refresh_roll_notice(fake)
    fake.refresh_roll_notice()
    assert not fake.roll_notice.shown                       # never set up: quiet
    calibrate.remember_roll(cfg.printer_info(p.id), "medium", "gap")
    fake.refresh_roll_notice()
    assert fake.roll_notice.shown
    assert fake.roll_lbl.text.startswith("New roll in the White label printer? Set it up")
    app_mod.App._same_roll(fake)                            # "No, same roll"
    assert not fake.roll_notice.shown
    again = settings_mod.Settings(tmp_path / "s.json")
    assert again["printers"][p.id]["roll"]["same"] == ["large"]
    fake.doc.stock = "medium"
    fake.refresh_roll_notice()
    assert not fake.roll_notice.shown
    fake.found = []                                          # unplugged: no notice
    fake.doc.stock = "xl"
    fake.refresh_roll_notice()
    assert not fake.roll_notice.shown
    assert jobs_written(tmp_path) == []
