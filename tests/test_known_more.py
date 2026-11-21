"""The printer families added in 1.4.0 (from public driver files and manuals; see
docs/printer-list.md): each is matched by the names and ids we found for it,
speaks the right language, and none of them changes how the LP610BT-type and
Zebra printers (or printers we don't know) are matched."""
import pytest

from food_labeler import known, printers

K = known.KnownPrinters()
NEW = {"munbyn-itpp941", "munbyn-itpp941p", "munbyn-itpp130", "munbyn-941ap", "rollo-x1038",
       "idprt-hprt", "polono-pl60", "pl70e-bt", "phomemo-pm241", "jadens-beeprt",
       "xprinter-4in", "arkscan-2054a"}


def test_new_families_are_there_and_all_alpha():
    assert NEW <= set(K.defs)
    for pid in NEW:
        d = K.defs[pid]
        assert d.verified_on_paper is False and d.support == known.SUPPORT_ALPHA
        assert d.notes                                     # says where the facts came from


@pytest.mark.parametrize("vidpid, family", [
    ("09c6:0248", "munbyn-itpp941"), ("5958:0249", "munbyn-itpp941"),
    ("5958:0d14", "munbyn-itpp941"), ("5958:0318", "munbyn-itpp941"),
    ("5958:0130", "munbyn-itpp130"), ("20d1:7008", "idprt-hprt"),
    ("2e3c:5750", "phomemo-pm241"), ("09c6:0426", "jadens-beeprt"),
    ("2d37:83d7", "xprinter-4in"), ("2d37:4296", "xprinter-4in"),
    ("0483:2025", "lp610bt-compatible"), ("0a5f:008c", "zebra-zp450"),
])
def test_usb_ids(vidpid, family):
    assert K.match(vidpid=vidpid).id == family


@pytest.mark.parametrize("info, family", [
    ({"MFG": "MunByn", "MDL": "ITPP941"}, "munbyn-itpp941"),
    ({"MFG": "MUNBYN", "MDL": "ITPP941P"}, "munbyn-itpp941p"),
    ({"MFG": "ITPP130", "MDL": "ITPP130"}, "munbyn-itpp130"),
    ({"MFG": "Printer", "CMD": "XPP,XL", "MDL": "ThermalPrinter"}, "rollo-x1038"),
    ({"MFG": "iDPRT", "MDL": "SP420"}, "idprt-hprt"),
    ({"MFG": "HPRT", "MDL": "SL42"}, "idprt-hprt"),
    ({"MFG": "POLONO", "MDL": "PL60"}, "polono-pl60"),
    ({"MFG": "Nelko", "MDL": "PL70e-BT"}, "pl70e-bt"),
    ({"MFG": " ", "MDL": "PM-241-BT"}, "phomemo-pm241"),
    ({"MFG": "JADENS", "MDL": "JD-268BT"}, "jadens-beeprt"),
    ({"MFG": "Xprinter", "CMD": "CEZD", "MDL": "XP-420B"}, "xprinter-4in"),
    ({"MFG": "4BARCODE", "CMD": "TSPL2", "MDL": "4B-2054A"}, "arkscan-2054a"),
    # unchanged
    ({"MFG": "Polono", "CMD": "TSPL2", "MDL": "4B-LP610BT"}, "lp610bt-compatible"),
    ({"MANUFACTURER": "Zebra Technologies", "COMMAND SET": "ZPL",
      "MODEL": "ZTC ZP 450-200dpi"}, "zebra-zp450"),
])
def test_1284_ids(info, family):
    assert K.match(info=info).id == family


@pytest.mark.parametrize("name, family", [
    ("MUNBYN ITPP941", "munbyn-itpp941"), ("RW941B", "munbyn-itpp941"),
    ("ITPP941P", "munbyn-itpp941p"), ("MUNBYN ITPP941AP", "munbyn-941ap"),
    ("ITPP130", "munbyn-itpp130"), ("Rollo Printer", "rollo-x1038"),
    ("iDPRT SP410", "idprt-hprt"), ("HPRT SL42", "idprt-hprt"),
    ("POLONO PL60", "polono-pl60"), ("PL70e-BT", "pl70e-bt"),
    ("PM-241-BT", "phomemo-pm241"), ("PM-246S", "phomemo-pm241"),
    ("JD-268BT", "jadens-beeprt"), ("Beeprt BY-482", "jadens-beeprt"),
    ("Xprinter XP-420B", "xprinter-4in"), ("XP-460B", "xprinter-4in"),
    ("Arkscan 2054A", "arkscan-2054a"),
    # unchanged: the LP610BT-type and Zebra names still go where they did
    ("4B-LP610BT", "lp610bt-compatible"), ("Polono", "lp610bt-compatible"),
    ("Labelnize LP610BT", "lp610bt-compatible"), ("BAR PRINTER", "lp610bt-compatible"),
    ("ZDesigner ZP 450-200dpi", "zebra-zp450"), ("Zebra GK420d", "zebra-zpl"),
])
def test_names(name, family):
    assert K.match(text=name).id == family


@pytest.mark.parametrize("name", ["HP LaserJet Pro M404", "Brother QL-800",
                                  "Microsoft Print to PDF", "EPSON ET-2800 Series",
                                  "Canon PIXMA", "DYMO LabelWriter 450", "Label Printer"])
def test_printers_we_dont_know_stay_unknown(name):
    assert K.match(text=name) is None


@pytest.mark.parametrize("family, kind", [
    ("munbyn-itpp941", "tspl"), ("rollo-x1038", "tspl"), ("idprt-hprt", "tspl"),
    ("polono-pl60", "tspl"), ("pl70e-bt", "tspl"), ("phomemo-pm241", "tspl"),
    ("jadens-beeprt", "tspl"), ("xprinter-4in", "tspl"), ("arkscan-2054a", "tspl"),
    ("munbyn-itpp130", "tspl"), ("munbyn-itpp941p", "tspl"),
])
def test_language_and_classify(family, kind):
    d = K.defs[family]
    p = printers.Printer(id="x", method="device", target="/dev/usb/lp0")
    printers.classify(p, K, {}, d.windows[0].split("|")[0])
    assert p.family.id == family and p.kind == kind and not p.driver_only
    assert p.alpha


def test_rollo_cmd_says_xpp_but_it_gets_tspl():
    p = printers.Printer(id="usb:1-1.6", method="device", target="/dev/usb/lp0")
    printers.classify(p, K, {"MFG": "Printer", "CMD": "XPP,XL", "MDL": "ThermalPrinter"}, "")
    assert p.family.id == "rollo-x1038" and p.kind == "tspl"


def test_941ap_prints_through_the_driver():
    d = K.defs["munbyn-941ap"]
    assert d.language == "driver"
    p = printers.Printer(id="win:MUNBYN ITPP941AP|USB001", method="windows_raw",
                         target="MUNBYN ITPP941AP")
    printers.classify(p, K, None, "MUNBYN ITPP941AP")
    assert p.family.id == "munbyn-941ap" and p.driver_only
    assert printers.printer_config(p, {})["method"] == "windows_driver"


def test_300_dpi_munbyn():
    assert K.defs["munbyn-itpp941p"].dpi == 300


def test_widths_where_known():
    for pid in ("munbyn-itpp941", "idprt-hprt", "polono-pl60", "xprinter-4in", "arkscan-2054a"):
        assert round(K.defs[pid].max_width_mm) == 108
    assert round(K.defs["pl70e-bt"].max_width_mm) == 104
