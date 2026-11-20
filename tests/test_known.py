import json

import pytest

from food_labeler import known

UPDATE = {"format": "food-labeler-printers", "version": 1, "printers": [
    {"id": "acme-lp", "name": "Acme label printer", "brands": ["Acme", "Bcme"],
     "language": "tspl", "usb": ["1234:ABCD"], "ieee1284": {"MDL": "ACME"},
     "windows": ["Acme"], "density": 10, "stocks": ["small", "large"]}]}


def write(tmp_path, data, name="u.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return p


def test_builtin_has_both_printers():
    k = known.KnownPrinters()
    lp = k.match(info={"MFG": "Polono", "CMD": "TSPL2", "MDL": "4B-LP610BT"})
    assert lp.id == "lp610bt-compatible" and lp.language == "tspl"
    assert k.match(vidpid="0483:2025").id == "lp610bt-compatible"
    assert k.match(text="STMicroelectronics BAR PRINTER").id == "lp610bt-compatible"
    assert k.match(text="Labelnize LP610").id == "lp610bt-compatible"
    assert k.match(text="Flexyva thermal").id == "lp610bt-compatible"
    z = k.match(info={"MANUFACTURER": "Zebra Technologies", "COMMAND SET": "ZPL",
                      "MODEL": "ZTC ZP 450-200dpi"})
    assert z.id == "zebra-zp450" and z.language == "zpl" and "xl" in z.stocks
    assert k.match(vidpid="0a5f:008c").id == "zebra-zp450"
    assert k.match(text="ZDesigner ZP 450-200dpi").id == "zebra-zp450"
    assert k.match(text="ZDesigner GK420d").id == "zebra-zpl"
    assert set(lp.stocks) == {"small", "medium", "large", "round", "xl"}
    assert lp.display_name.startswith("LP610BT-compatible label printer (Labelnize / Flexyva")
    assert k.match(vidpid="ffff:0000", text="Microsoft Print to PDF") is None


def test_import_and_merge(tmp_path):
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    names = k.import_file(write(tmp_path, UPDATE))
    assert names == ["Acme label printer (Acme / Bcme…)"]
    d = k.match(vidpid="1234:abcd")
    assert d.id == "acme-lp" and d.density_for("large") == 10
    # survives a restart, built-ins still there
    k2 = known.KnownPrinters(user_dir=tmp_path / "data")
    assert "acme-lp" in k2.defs and "lp610bt-compatible" in k2.defs
    # a user update can override a built-in entry
    over = {"format": "food-labeler-printers", "version": 1, "printers": [
        {"id": "lp610bt-compatible", "name": "LP610BT-compatible label printer",
         "brands": ["Labelnize", "Flexyva", "Polono", "Newbrand"], "language": "tspl",
         "usb": ["0483:2025"]}]}
    k2.import_file(write(tmp_path, over, "o.json"))
    assert "Newbrand" in k2.defs["lp610bt-compatible"].brands
    assert "acme-lp" in k2.defs


@pytest.mark.parametrize("bad, msg", [
    ("not json", "isn't a Food Labeler"),
    ({"format": "something", "version": 1, "printers": []}, "isn't a Food Labeler"),
    ({"format": "food-labeler-printers", "version": 2, "printers": [{}]}, "different version"),
    ({"format": "food-labeler-printers", "version": 1, "printers": []}, "no printers"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "escpos"}]}, "tspl or zpl"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "Bad Id", "name": "X", "language": "tspl"}]}, "id"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "usb": ["12345"]}]}, "USB id"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "windows": ["(unclosed"]}]},
     "pattern"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "run": "rm -rf /"}]},
     "doesn't understand"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "stocks": ["a4"]}]},
     "unknown label size"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "dpi": 300}]}, "203"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl"},
                   {"id": "x", "name": "Y", "language": "zpl"}]}, "twice"),
])
def test_rejects_bad_files(tmp_path, bad, msg):
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    with pytest.raises(known.DefinitionError, match=msg):
        k.import_file(write(tmp_path, bad))
    assert not (tmp_path / "data" / "known_printers.json").exists()


def test_broken_user_file_is_ignored(tmp_path):
    (tmp_path / "known_printers.json").write_text("garbage")
    k = known.KnownPrinters(user_dir=tmp_path)
    assert "lp610bt-compatible" in k.defs


def test_app_config_has_support_email():
    assert known.app_config()["support_email"] == "hello@highthymekitchen.com"


def test_update_file_with_byte_order_mark(tmp_path):
    # Windows Notepad saves UTF-8 with a BOM; that must still be accepted.
    p = tmp_path / "bom.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(UPDATE).encode("utf-8"))
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    assert k.import_file(p) == ["Acme label printer (Acme / Bcme…)"]
