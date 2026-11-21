"""Files that are far too big, or nested absurdly deep, are refused kindly.

Big files are made sparse (truncate), so the tests use no real disk space."""
import json

import pytest

from food_labeler import bakery, cottage, known, model, settings

DEEP = "[" * 200_000 + "]" * 200_000          # json.loads raises RecursionError on this


def big(path, size):
    """A sparse file of ``size`` bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    return path


def test_deep_json_really_recurses():
    with pytest.raises(RecursionError):
        json.loads(DEEP)


def test_deep_label_file(tmp_path):
    p = tmp_path / "deep.label"
    p.write_text(DEEP)
    with pytest.raises(model.LabelFileError, match="damaged"):
        model.load(p)
    with pytest.raises(model.LabelFileError, match="damaged"):
        model.LabelDoc.loads(DEEP)


def test_too_big_label_file_is_not_read(tmp_path):
    p = big(tmp_path / "huge.label", model.MAX_LABEL_BYTES + 1)
    with pytest.raises(model.LabelFileError, match="too big"):
        model.load(p)
    # a label just under the limit is still read (here: a real, small one)
    ok = model.save(model.LabelDoc(), tmp_path / "ok")
    assert model.load(ok).template == model.LabelDoc().template


def test_read_text_limited_never_reads_past_the_limit(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x" * 100)
    assert model.read_text_limited(p, 100) == "x" * 100
    with pytest.raises(model.FileTooBigError):
        model.read_text_limited(p, 99)
    assert issubclass(model.FileTooBigError, OSError)


def test_deep_and_big_printer_update(tmp_path):
    k = known.KnownPrinters(user_dir=tmp_path / "data")
    p = tmp_path / "deep.json"
    p.write_text(DEEP)
    with pytest.raises(known.DefinitionError, match="isn't a Food Labeler printer update"):
        k.import_file(p)
    with pytest.raises(known.DefinitionError, match="too big"):
        k.import_file(big(tmp_path / "big.json", model.MAX_UPDATE_BYTES + 1))
    assert not (tmp_path / "data" / known.USER_FILE_NAME).exists()
    # a too-big user file already in the data folder is ignored at start-up
    big(tmp_path / "data" / known.USER_FILE_NAME, model.MAX_UPDATE_BYTES + 1)
    assert "lp610bt-compatible" in known.KnownPrinters(user_dir=tmp_path / "data").defs


def test_deep_and_big_cottage_update(tmp_path):
    rules = cottage.CottageRules(user_dir=tmp_path / "data")
    p = tmp_path / "deep.json"
    p.write_text(DEEP)
    with pytest.raises(cottage.RulesError, match="isn't a Food Labeler state rules"):
        rules.import_file(p)
    with pytest.raises(cottage.RulesError, match="too big"):
        rules.import_file(big(tmp_path / "big.json", model.MAX_UPDATE_BYTES + 1))
    assert not (tmp_path / "data" / cottage.USER_RULES_NAME).exists()


def test_deep_and_big_overrides_are_set_aside(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / cottage.OVERRIDES_NAME).write_text(DEEP)
    cottage.CottageRules(user_dir=data)
    assert (data / (cottage.OVERRIDES_NAME + ".broken")).exists()
    (data / (cottage.OVERRIDES_NAME + ".broken")).unlink()
    big(data / cottage.OVERRIDES_NAME, model.MAX_BACKUP_BYTES + 1)
    cottage.CottageRules(user_dir=data)
    assert (data / (cottage.OVERRIDES_NAME + ".broken")).exists()


@pytest.mark.parametrize("cls, what", [(bakery.Products, "products"),
                                       (bakery.Ingredients, "ingredients")])
def test_deep_and_big_backups(tmp_path, cls, what):
    lib = cls(tmp_path / f"my_{what}.json")
    before = list(lib.items)
    p = tmp_path / "deep.json"
    p.write_text(DEEP)
    with pytest.raises(bakery.LibraryError, match=f"isn't a Food Labeler {what} file"):
        lib.import_file(p)
    with pytest.raises(bakery.LibraryError, match="too big"):
        lib.import_file(big(tmp_path / "big.json", model.MAX_BACKUP_BYTES + 1))
    assert lib.items == before


@pytest.mark.parametrize("name", [bakery.PROFILE_NAME, bakery.PRODUCTS_NAME])
@pytest.mark.parametrize("how", ["deep", "big"])
def test_deep_or_big_bakery_files_are_set_aside(tmp_path, name, how):
    path = tmp_path / name
    if how == "deep":
        path.write_text(DEEP)
    else:
        big(path, model.MAX_BACKUP_BYTES + 1)
    if name == bakery.PROFILE_NAME:
        assert bakery.Profile(path)["business"] == ""
    else:
        assert bakery.Products(path).items == []
    assert (tmp_path / (name + ".broken")).exists()


@pytest.mark.parametrize("how", ["deep", "big", "garbage"])
def test_bad_settings_are_set_aside(how):
    p = settings.data_dir() / "settings.json"
    if how == "deep":
        p.write_text(DEEP)
    elif how == "big":
        big(p, model.MAX_SETTINGS_BYTES + 1)
    else:
        p.write_text("{oops")
    s = settings.Settings()
    assert s["date_style"] == "us"
    assert (settings.data_dir() / "settings.json.broken").exists()
    s.save()                                   # the next save starts a fresh file
    assert settings.Settings()["date_style"] == "us"


@pytest.mark.parametrize("how", ["deep", "big"])
def test_bad_autosave_is_ignored(how):
    p = settings.autosave_path()
    if how == "deep":
        p.write_text('{"doc": ' + DEEP + "}")
    else:
        big(p, model.MAX_LABEL_BYTES + model.MB + 1)
    assert settings.read_autosave() is None
