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
      "printers": [{"id": "x", "name": "X", "language": "escpos"}]}, "tspl, zpl or driver"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "Bad Id", "name": "X", "language": "tspl"}]}, "id"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "usb": ["12345"]}]}, "USB id"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "windows": ["x" * 81]}]},
     "too long"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "windows": [" | "]}]},
     "empty"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl",
                    "ieee1284": {"MDL": "y" * 81}}]}, "too long"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "run": "rm -rf /"}]},
     "doesn't understand"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "stocks": ["a4"]}]},
     "unknown label size"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "dpi": 600}]}, "203 or 300"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "dpi": "300"}]}, "203 or 300"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "dpi": True}]}, "203 or 300"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "max_width_dots": 9}]},
     "max_width_dots"),
    ({"format": "food-labeler-printers", "version": 1,
      "printers": [{"id": "x", "name": "X", "language": "tspl", "max_width_dots": 832.5}]},
     "max_width_dots"),
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


@pytest.mark.parametrize("name, family", [
    ("4B-LP610BT", "lp610bt-compatible"),
    ("BAR PRINTER", "lp610bt-compatible"),
    ("Labelnize", "lp610bt-compatible"),
    ("Flexyva", "lp610bt-compatible"),
    ("Polono", "lp610bt-compatible"),
    ("ZDesigner ZP 450-200dpi", "zebra-zp450"),
    ("ZTC ZP 450-200dpi", "zebra-zp450"),
    ("Zebra ZP450", "zebra-zp450"),
    ("zdesigner zp450 (copy 1)", "zebra-zp450"),
    ("Zebra GK420d", "zebra-zpl"),
])
def test_bundled_names_still_match(name, family):
    # The bundled file is plain text patterns now; real names must still match.
    assert known.KnownPrinters().match(text=name).id == family


def test_bundled_1284_ids_still_match():
    k = known.KnownPrinters()
    for model in ("ZTC ZP 450-200dpi", "ZP450", "Zebra ZP 450"):
        assert k.match(info={"MANUFACTURER": "Zebra Technologies", "COMMAND SET": "ZPL",
                             "MODEL": model}).id == "zebra-zp450"
    assert k.match(info={"MFG": "Labelnize", "CMD": "TSPL", "MDL": "4B-LP610BT"}).id \
        == "lp610bt-compatible"


def test_patterns_are_plain_text_with_alternatives(tmp_path):
    upd = {"format": "food-labeler-printers", "version": 1, "printers": [
        {"id": "acme", "name": "Acme", "language": "tspl",
         "windows": ["Acme ?100|Acme-200"], "ieee1284": {"MDL": "A.C|AC*"}}]}
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    k.import_file(write(tmp_path, upd))
    assert k.match(text="ACME-200 driver").id == "acme"
    assert k.match(text="my acme ?100").id == "acme"
    assert k.match(text="Acme 100") is None          # "?" is a plain question mark
    assert k.match(info={"MDL": "xac*y"}).id == "acme"
    assert k.match(info={"MDL": "ABC"}) is None       # "." is a plain dot


def test_regex_looking_update_imports_and_matches_quickly(tmp_path):
    import time
    evil = "^(([a-zA-Z0-9 -]+)*)*!$"
    upd = {"format": "food-labeler-printers", "version": 1, "printers": [
        {"id": "evil", "name": "Evil", "language": "tspl",
         "windows": [evil], "ieee1284": {"MDL": evil, "MFG": evil}}]}
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    assert k.import_file(write(tmp_path, upd)) == ["Evil"]
    k = known.KnownPrinters(user_dir=tmp_path / "data")   # as at start-up
    subject = "a" * 5000 + " ZDesigner ZP 450-200dpi"
    start = time.perf_counter()
    for _ in range(20):
        k.match(info={"MDL": subject, "MFG": subject}, vidpid="ffff:0000", text=subject)
    assert time.perf_counter() - start < 0.1
    assert k.match(text="x " + evil + " y").id == "evil"   # matched literally
    assert k.match(text="ZDesigner ZP 450-200dpi").id == "zebra-zp450"


def test_long_names_are_cut_before_matching():
    k = known.KnownPrinters()
    assert k.match(text="x" * 300 + "Zebra") is None
    assert k.match(text="x" * 100 + "Zebra").id == "zebra-zpl"
