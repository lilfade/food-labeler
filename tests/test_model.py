import datetime as dt
import json

import pytest

from food_labeler import model


def test_save_load_roundtrip(tmp_path):
    doc = model.LabelDoc("simple", "round", model.default_fields("simple"), copies=4)
    doc.fields.update(food="Chili é", contains="Milk", note="Keep frozen")
    p = model.save(doc, tmp_path / "chili")
    assert p.suffix == ".label"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["app"] == "easy-labels" and data["version"] == 1
    assert data["template"] == "simple" and data["stock"] == "round" and data["copies"] == 4
    assert data["fields"]["made_on"] == dt.date.today().isoformat()
    back = model.load(p)
    assert back.to_dict() == doc.to_dict()


def test_rejects_other_files(tmp_path):
    p = tmp_path / "x.label"
    p.write_text("{not json")
    with pytest.raises(model.LabelFileError):
        model.load(p)
    p.write_text(json.dumps({"app": "other", "version": 1}))
    with pytest.raises(model.LabelFileError):
        model.load(p)
    p.write_text(json.dumps({"app": "easy-labels", "version": 99}))
    with pytest.raises(model.LabelFileError, match="newer"):
        model.load(p)
    with pytest.raises(model.LabelFileError):
        model.load(tmp_path / "missing.label")


def test_unknown_fields_and_bad_values_are_tolerated():
    doc = model.LabelDoc.from_dict({"app": "easy-labels", "version": 1, "template": "nope",
                                    "stock": "huge", "fields": {"food": "A", "evil": 1},
                                    "copies": "lots"})
    assert doc.template == "simple" and doc.stock == "large" and doc.copies == 1
    assert "evil" not in doc.fields and doc.fields["food"] == "A"


def test_refresh_dates_keeps_offset():
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"))
    doc.fields["made_on"] = "2026-11-01"
    doc.fields["use_by"] = "2026-11-06"
    doc.refresh_dates(dt.date(2026, 11, 20))
    assert doc.fields["made_on"] == "2026-11-20" and doc.fields["use_by"] == "2026-11-25"
    s = model.LabelDoc("sticker", "small", model.default_fields("sticker", dt.date(2026, 11, 1)))
    s.refresh_dates(dt.date(2026, 11, 20))
    assert s.fields["lot"] == "261120" and s.fields["made"] == "2026-11-20"


def test_template_switch_carries_name_and_dates():
    doc = model.LabelDoc()
    doc.fields.update(food="Soup", contains="Milk", use_by="2026-12-01")
    doc.set_template("package")
    assert doc.fields["product"] == "Soup" and doc.fields["contains"] == "Milk"
    assert doc.fields["best_by"] == "2026-12-01"
    assert doc.title() == "Soup"


def test_copies_clamp():
    d = model.LabelDoc(copies=500)
    d.clamp_copies()
    assert d.copies == 200


def test_safe_filename():
    assert model.safe_filename('a/b:c*?"') == "a-b-c---"
    assert model.safe_filename("   ") == "My label"


def test_safe_filename_windows_rules():
    assert model.safe_filename("con") == "con label"
    assert model.safe_filename("LPT1.txt") == "LPT1.txt label"
    assert model.safe_filename("Console soup") == "Console soup"
    # cutting to 60 characters must not leave a trailing space or dot
    assert model.safe_filename("x" * 59 + " y") == "x" * 59
