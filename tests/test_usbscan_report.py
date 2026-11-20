import json
from urllib.parse import unquote

from food_labeler import __version__, known, model, printers, report, settings, usbscan
from conftest import FakeRun, linux_only, make_fake_sysfs

K = known.KnownPrinters()


@linux_only
def test_scan_linux(tmp_path):
    sysr, devr = make_fake_sysfs(tmp_path)
    devs = usbscan.scan_linux(str(sysr), K)
    by_port = {d.port: d for d in devs}
    assert set(by_port) == {"1-1.1", "1-1.2", "1-1.3", "1-1.4"}      # hub skipped
    assert by_port["1-1.3"].is_printer and by_port["1-1.3"].vidpid == "0483:2025"
    assert by_port["1-1.3"].lp == "lp0" and by_port["1-1.4"].lp == "lp1"
    assert by_port["1-1.4"].ieee1284["MDL"] == "4B-LP610BT"
    assert by_port["1-1.2"].family.id == "zebra-zp450"
    assert not by_port["1-1.1"].is_printer and by_port["1-1.1"].family is None
    assert by_port["1-1.1"].title() == "Logitech USB Keyboard"


def test_parse_windows_pnp():
    data = [
        {"DeviceID": "USB\\VID_0483&PID_2025\\000000000004", "Name": "USB Printing Support",
         "PNPClass": "USB", "Manufacturer": "Microsoft"},
        {"DeviceID": "USB\\VID_0A5F&PID_008C\\41J1234", "Name": "ZDesigner ZP 450-200dpi",
         "PNPClass": "Printer", "Manufacturer": "Zebra"},
        {"DeviceID": "USB\\VID_046D&PID_C31C&MI_00\\7&1", "Name": "HID Keyboard"},
        {"DeviceID": "PCI\\VEN_8086", "Name": "not usb"},
    ]
    devs = usbscan.parse_windows_pnp(json.dumps(data), K)
    assert [d.vidpid for d in devs] == ["0483:2025", "0a5f:008c"]
    assert devs[0].family.id == "lp610bt-compatible" and devs[1].is_printer
    assert usbscan.parse_windows_pnp("", K) == []
    assert usbscan.parse_windows_pnp("{bad", K) == []
    one = usbscan.parse_windows_pnp(json.dumps(data[1]), K)       # single object, not list
    assert len(one) == 1


@linux_only
def test_report_has_facts_but_no_label_content(tmp_path):
    secret = "Aunt Mabel's Secret Plum Chutney 12345"
    doc = model.LabelDoc()
    doc.fields.update(food=secret, made_by="Mabel Q. Private", note=secret)
    settings.write_autosave(doc, str(tmp_path / "labels" / "chutney.label"), True)
    model.save(doc, tmp_path / "labels" / "chutney")
    log = settings.data_dir() / "food-labeler.log"
    log.write_text("2026-11-20 INFO food_labeler: started\n"
                   "2026-11-20 ERROR food_labeler.printers: print failed\n"
                   "Traceback (most recent call last):\n"
                   f'  File "{tmp_path}/x.py", line 1, in <module>\n'
                   "OSError: [Errno 5] Input/output error\n")
    sysr, devr = make_fake_sysfs(tmp_path)
    devs = usbscan.scan_linux(str(sysr), K)
    found = printers.discover_linux(str(sysr), str(devr), FakeRun(), K)
    text = report.build(found, devs, {"usb:1-1.4": "White label printer"}, log, K)
    assert secret not in text and "Mabel" not in text and "chutney" not in text.lower()
    assert "0483:2025" in text and "1-1.4" in text and "MDL:4B-LP610BT" in text
    assert "ZTC ZP 450-200dpi" in text and "White label printer" in text
    assert "Input/output error" in text and f"Food Labeler {__version__}" in text
    assert " INFO " not in text


def test_mailto():
    m = report.mailto("hello report", "hello@highthymekitchen.com")
    assert m.startswith("mailto:hello%40highthymekitchen.com?subject=")
    assert unquote(m.split("subject=")[1].split("&")[0]) == report.SUBJECT
    long = report.mailto("x" * 5000)
    assert len(unquote(long)) < 2400 and "copied" in unquote(long)


def test_scrub_hides_user_name_only_as_a_whole_word(monkeypatch):
    monkeypatch.setattr(report.getpass, "getuser", lambda: "lab")
    out = report._scrub("Food Labeler report for lab on LAB-PC, C:/Users/lab/x")
    assert "Food Labeler" in out and "<user> on <user>-PC" in out
    assert "lab" not in out.replace("Labeler", "")
