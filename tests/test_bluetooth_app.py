"""Bluetooth printers in the window and the printer report: the one-time
"not tested over Bluetooth" notice, remembering the channel that worked,
and a report that never has a full Bluetooth address or other devices' names."""
import re

import pytest

from food_labeler import btscan, printers, report
from test_bluetooth import A1, K, WIN_JSON, bt_printer, linux_scan


def test_app_shows_the_bluetooth_notice_once(monkeypatch):
    from food_labeler import app as app_mod
    from test_alpha_driver import FakeCfg
    asked = []
    monkeypatch.setattr(app_mod, "ask", lambda *a, **k: asked.append(a[2]) or True)
    fake = type("FakeApp", (), {"root": None, "cfg": FakeCfg(printers={})})()
    usb = printers.Printer(id="usb:1-1.3", family=K.defs["lp610bt-compatible"])
    assert app_mod.App.alpha_ok(fake, usb) and not asked
    assert app_mod.App.alpha_ok(fake, bt_printer()) and asked == [
        printers.ALPHA_NOTICE_BLUETOOTH]
    assert app_mod.App.alpha_ok(fake, bt_printer()) and len(asked) == 1


def test_app_remembers_the_channel_that_worked():
    from food_labeler import app as app_mod
    from test_alpha_driver import FakeCfg
    p = bt_printer()
    fake = type("FakeApp", (), {"found": [p], "cfg": FakeCfg(printers={})})()
    printers.LEARNED_CHANNELS[A1] = 2
    app_mod.App._remember_bt_channel(fake, {"method": "bluetooth", "target": A1})
    assert fake.cfg["printers"][p.id]["bt_channel_found"] == 2 and fake.cfg.saved == 1
    app_mod.App._remember_bt_channel(fake, {"method": "bluetooth", "target": A1})
    app_mod.App._remember_bt_channel(fake, {"method": "device", "target": "/dev/usb/lp0"})
    app_mod.App._remember_bt_channel(fake, None)
    assert fake.cfg.saved == 1


# -- report ---------------------------------------------------------------------------

FULL_MAC = re.compile(r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}")


def report_for(everything):
    devs, _ = linux_scan()
    found = btscan.to_printers(devs, K, windows=False)
    found += btscan.to_printers(btscan.parse_windows(WIN_JSON, K), K, windows=True)
    return report.build(found, [], {f"bt:{A1}": "White"}, known=K, everything=everything,
                        bt_devices=devs)


@pytest.mark.parametrize("everything", [False, True])
def test_report_never_has_a_full_address_or_other_device_names(everything):
    text = report_for(everything)
    assert not FULL_MAC.search(text), FULL_MAC.search(text)
    assert "898F10113FA2" not in text and "D51F77229C01" not in text
    assert "\u20263F:A2" in text and "\u20269C:01" in text
    assert "Pixel" not in text and "Bryson" not in text and "Angela" not in text
    assert "class 0x040680 (printer)" in text and "SPP yes" in text
    assert "paired yes  connected no" in text and "connected yes" in text
    assert "White" in text and "via bluetooth" in text
    if everything:
        assert "Bluetooth devices (paired):" in text and "class 0x5a020c" in text
        assert text.count("name not shown") == 2
    else:
        assert "(2 other Bluetooth devices paired, not listed)" in text


def test_report_without_bluetooth():
    text = report.build([], [], known=K)
    assert "Bluetooth printers (paired):\n  (none found)" in text
