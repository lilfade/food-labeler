"""Tested vs alpha printers, and printers that only work through their maker's driver.

Nothing here opens a window or prints: jobs go to the dry-run folder (conftest)."""
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from food_labeler import known, printers

K = known.KnownPrinters()

DRIVER_UPDATE = {"format": "food-labeler-printers", "version": 1, "printers": [
    {"id": "acme-app-only", "name": "Acme app-only printer", "language": "driver",
     "usb": ["abcd:0001"], "windows": ["Acme AP-1"], "max_width_mm": 104,
     "verified_on_paper": False}]}


def driver_known(tmp_path):
    f = tmp_path / "upd.json"
    f.write_text(json.dumps(DRIVER_UPDATE))
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    k.import_file(f)
    return k


# -- tested / alpha --------------------------------------------------------------------

def test_only_our_two_printers_are_tested():
    tested = {d.id for d in K.all() if d.verified_on_paper}
    assert tested == {"lp610bt-compatible", "zebra-zp450"}
    for d in K.all():
        assert d.support == (known.SUPPORT_TESTED if d.id in tested else known.SUPPORT_ALPHA)


def test_tag_only_for_alpha_printers():
    lp = printers.Printer(id="usb:1-1.3", port="USB port 1-1.3",
                          family=K.defs["lp610bt-compatible"])
    zz = printers.Printer(id="win:z|USB001", family=K.defs["zebra-zp450"])
    generic = printers.Printer(id="win:g|USB002", family=K.defs["zebra-zpl"])
    unknown = printers.Printer(id="usb:1-1.9", model="Mystery 9000", kind="tspl")
    assert not lp.alpha and not zz.alpha and generic.alpha and unknown.alpha
    assert printers.ALPHA_TAG not in lp.display("White", tag=True)
    assert printers.ALPHA_TAG not in zz.display(tag=True)
    assert generic.display(tag=True) == f"Zebra label printer {printers.ALPHA_TAG}"
    assert unknown.display("Mine", tag=True) == f"Mine {printers.ALPHA_TAG}"
    assert printers.ALPHA_TAG not in unknown.display("Mine")      # untagged unless asked


def test_alpha_notice_is_due_once_and_never_for_tested():
    tested = printers.Printer(id="a", family=K.defs["zebra-zp450"])
    alpha = printers.Printer(id="b", family=K.defs["zebra-zpl"])
    assert not printers.alpha_notice_due(tested, {})
    assert not printers.alpha_notice_due(None, {})
    assert printers.alpha_notice_due(alpha, {}) and printers.alpha_notice_due(alpha, None)
    assert not printers.alpha_notice_due(alpha, {"alpha_ok": True})


class FakeCfg(dict):
    saved = 0

    def printer_info(self, pid):
        return self["printers"].setdefault(pid, {})

    def save(self):
        self.saved += 1


@pytest.mark.parametrize("answer", [True, False])
def test_app_shows_the_alpha_notice_once_per_printer(monkeypatch, answer):
    from food_labeler import app as app_mod
    asked = []

    def fake_ask(parent, title, message, buttons, icon=""):
        asked.append((message, [b[0] for b in buttons]))
        return answer
    monkeypatch.setattr(app_mod, "ask", fake_ask)
    fake = type("FakeApp", (), {"root": None, "cfg": FakeCfg(printers={})})()
    alpha = printers.Printer(id="usb:1-1.9")
    other = printers.Printer(id="usb:1-1.8")
    tested = printers.Printer(id="usb:1-1.3", family=K.defs["lp610bt-compatible"])
    assert app_mod.App.alpha_ok(fake, tested) is True and not asked
    assert app_mod.App.alpha_ok(fake, alpha) is answer
    assert asked == [(printers.ALPHA_NOTICE, ["OK, print", "Cancel"])]
    assert "Ask for help on GitHub" in printers.ALPHA_NOTICE
    assert app_mod.App.alpha_ok(fake, alpha) is True and len(asked) == 1   # remembered
    assert fake.cfg["printers"]["usb:1-1.9"]["alpha_ok"] is True and fake.cfg.saved == 1
    app_mod.App.alpha_ok(fake, other)                                      # per printer
    assert len(asked) == 2


# -- "driver" language ---------------------------------------------------------------

def test_driver_language_is_accepted_and_max_width_mm_converts(tmp_path):
    d = driver_known(tmp_path).defs["acme-app-only"]
    assert d.language == "driver" and d.driver_only and d.support == known.SUPPORT_ALPHA
    assert d.max_width_dots == 831 and round(d.max_width_mm) == 104   # 104 mm at 203 dpi


@pytest.mark.parametrize("bad, msg", [
    ({"verified_on_paper": "yes"}, "verified_on_paper"),
    ({"max_width_mm": 2}, "max_width_mm"),
    ({"max_width_mm": True}, "max_width_mm"),
    ({"language": "escpos"}, "tspl, zpl or driver"),
])
def test_new_fields_are_checked(bad, msg):
    entry = dict(DRIVER_UPDATE["printers"][0], **bad)
    with pytest.raises(known.DefinitionError, match=msg):
        known.validate_entry(entry)


def test_windows_driver_only_printer_prints_through_the_driver(tmp_path):
    k = driver_known(tmp_path)

    class W:
        PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 2, 4

        def EnumPrinters(self, flags, name, level):
            return [{"pPrinterName": "Acme AP-1", "pDriverName": "Acme AP-1 Driver",
                     "pPortName": "USB001"}]
    p = printers.discover_windows(W(), k)[0]
    assert p.family.id == "acme-app-only" and p.driver_only and p.kind == ""
    assert printers.printer_config(p, {})["method"] == "windows_driver"
    # the user chose a Type: then it is treated as that language, sent raw
    cfg = printers.printer_config(p, {"kind": "tspl"})
    assert cfg == {"kind": "tspl", "method": "windows_raw", "target": "Acme AP-1"}


def test_linux_driver_only_printer_says_so_and_sends_nothing(tmp_path):
    k = driver_known(tmp_path)
    p = printers.Printer(id="usb:1-1.5", method="device", target="/dev/usb/lp0",
                         vidpid="abcd:0001")
    printers.classify(p, k, {}, "")
    assert p.family.id == "acme-app-only" and p.driver_only
    cfg = printers.printer_config(p, {})
    assert cfg["method"] == "needs_driver"
    with pytest.raises(printers.PrinterError) as e:
        printers.send(cfg, b"x", image=Image.new("1", (8, 8)))
    assert str(e.value) == printers.MSG_NEEDS_DRIVER and "driver" in str(e.value)
    jobs = Path(os.environ["FOOD_LABELER_DRY_RUN"])
    assert not jobs.exists() or not list(jobs.iterdir())


def test_1284_language_beats_a_driver_entry(tmp_path):
    k = driver_known(tmp_path)
    p = printers.Printer(id="usb:1-1.5", method="device", target="/dev/usb/lp0",
                         vidpid="abcd:0001")
    printers.classify(p, k, {"CMD": "TSPL", "MDL": "AP-1"}, "")
    assert p.family.id == "acme-app-only" and p.kind == "tspl" and not p.driver_only
    assert printers.printer_config(p, {})["method"] == "device"


def test_tested_printers_are_unchanged_by_the_driver_path():
    lp = printers.Printer(id="win:4B|USB001", method="windows_raw", target="4B-LP610BT",
                          vidpid="0483:2025")
    printers.classify(lp, K, None, "4B-LP610BT")
    assert lp.family.id == "lp610bt-compatible" and lp.kind == "tspl" and not lp.driver_only
    assert printers.printer_config(lp, {})["method"] == "windows_raw"
    assert printers.printer_config(lp, {"via_driver": True})["method"] == "windows_driver"


def test_round_trip_keeps_verified_flag(tmp_path):
    upd = {"format": "food-labeler-printers", "version": 1, "printers": [
        dict(DRIVER_UPDATE["printers"][0], id="ok-one", verified_on_paper=True)]}
    f = tmp_path / "u.json"
    f.write_text(json.dumps(upd))
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    k.import_file(f)
    again = known.KnownPrinters(user_dir=tmp_path / "data")
    assert again.defs["ok-one"].verified_on_paper is True
    assert again.defs["ok-one"].max_width_dots == 831
