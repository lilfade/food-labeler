from food_labeler import model, settings


def test_settings_roundtrip_and_defaults():
    s = settings.Settings()
    assert s["ui_scale"] == 1.0 and s["printers"] == {}
    s["ui_scale"] = 1.35
    s.printer_info("usb:1-1.4").update(nickname="White label printer", stock="small")
    s.save()
    s2 = settings.Settings()
    assert s2["ui_scale"] == 1.35 and s2.nickname("usb:1-1.4") == "White label printer"
    assert s2["printers"]["usb:1-1.4"]["stock"] == "small"
    assert s2["kitchen"]["disclaimer"] == model.DEFAULT_DISCLAIMER


def test_bad_settings_file_uses_defaults():
    p = settings.data_dir() / "settings.json"
    p.write_text("{oops")
    assert settings.Settings()["date_style"] == "us"


def test_recent_files(tmp_path):
    s = settings.Settings()
    a = model.save(model.LabelDoc(), tmp_path / "a")
    b = model.save(model.LabelDoc(), tmp_path / "b")
    s.add_recent(a, "Soup")
    s.add_recent(b, "Stew")
    s.add_recent(a, "Soup")
    assert [r["name"] for r in s.recent()] == ["Soup", "Stew"]
    b.unlink()
    assert [r["name"] for r in s.recent()] == ["Soup"]


def test_autosave_roundtrip():
    doc = model.LabelDoc()
    doc.fields["food"] = "Soup"
    settings.write_autosave(doc, "/x/y.label", True)
    got, path, dirty = settings.read_autosave()
    assert got.fields["food"] == "Soup" and path == "/x/y.label" and dirty
    settings.autosave_path().write_text("garbage")
    assert settings.read_autosave() is None


def test_labels_dir_created():
    assert settings.labels_dir().is_dir()
