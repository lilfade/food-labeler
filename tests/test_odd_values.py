"""Files with odd values in them open with defaults or are called damaged — never
anything else.

Python's json accepts NaN, Infinity, -Infinity and numbers like 1e400 (which
become infinity), and a hand-edited or damaged file can have a list, an
object, true or null anywhere. Every part of a .label file, the settings, the
baker's files and the update files is fed each of these in turn."""
import json

import pytest
from PIL import Image

from food_labeler import bakery, cottage, known, model, pictures, printsettings, qrcodes
from food_labeler import calibrate, render, settings, stocks, values

HUGE = "x" * 300_000
# JSON text for each odd value ("1e400" has no Python spelling json would write)
ODD = {"nan": "NaN", "inf": "Infinity", "-inf": "-Infinity", "1e400": "1e400",
       "-1e400": "-1e400", "list": "[1, [2]]", "dict": '{"a": {"b": 1}}', "true": "true",
       "false": "false", "null": "null", "huge_str": json.dumps(HUGE),
       "huge_int": "9" * 400, "neg": "-5", "zero": "0", "float": "12.75"}
MARK = "\x00ODD\x00"


def with_odd(data: dict, path: tuple, odd: str) -> str:
    """``data`` as JSON text with the value at ``path`` replaced by the raw JSON ``odd``."""
    d = json.loads(json.dumps(data))
    node = d
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = MARK
    return json.dumps(d).replace(json.dumps(MARK), odd)


def paths(d: dict, prefix=()):
    """Every key path in a nested dict (("fields",), ("fields", "food"), ...)."""
    for k, v in d.items():
        yield prefix + (k,)
        if isinstance(v, dict):
            yield from paths(v, prefix + (k,))


def full_label(template: str) -> dict:
    doc = model.LabelDoc()
    doc.set_template(template)
    for k, v in doc.fields.items():
        if isinstance(v, str) and not v and k != "qr":
            doc.fields[k] = "Some " + k
    doc.stock = "medium"
    doc.lettering = {"name": "Pacifico", "other": "Lato"}
    doc.picture = dict(pictures.DEFAULTS, png=pictures.encode(Image.new("L", (40, 30), 0)),
                       name="logo", place="fit" if template == "picture" else "left",
                       threshold=128)
    doc.qr = dict(qrcodes.DEFAULTS, value="example.com", caption="Menu")
    doc.orientation = "tall"
    d = doc.to_dict()
    assert "picture" in d and "qr" in d and "lettering" in d
    return d


def check_doc(doc: model.LabelDoc, render_it: bool) -> None:
    """A loaded document is usable: it saves (with no NaN written back), has a
    title, moves its dates and draws."""
    text = json.dumps(doc.to_dict(), allow_nan=False)
    assert model.LabelDoc.loads(text).to_dict() == doc.to_dict()
    assert isinstance(doc.title(), str)
    assert 1 <= doc.copies <= 200
    assert doc.stock in stocks.STOCKS
    for v in doc.fields.values():
        assert isinstance(v, (str, bool))
    doc.copy().refresh_dates()
    if render_it:
        render.render(doc)


@pytest.mark.parametrize("template", model.TEMPLATES)
def test_every_part_of_a_label_with_every_odd_value(template):
    data = full_label(template)
    opened = refused = 0
    for path in paths(data):
        for name, odd in ODD.items():
            text = with_odd(data, path, odd)
            try:
                doc = model.LabelDoc.loads(text)
            except model.LabelFileError:
                refused += 1
                continue
            except Exception as e:      # noqa: BLE001
                pytest.fail(f"{template} {path} = {name}: {type(e).__name__}: {e}")
            check_doc(doc, render_it=False)      # drawn below (drawing each is slow)
            opened += 1
    # only a spoiled "app" or "version" makes it not a label at all
    assert refused <= 2 * len(ODD) and opened > 10 * len(ODD)


@pytest.mark.parametrize("template", model.TEMPLATES)
@pytest.mark.parametrize("name", ["nan", "inf", "1e400", "list", "dict", "true", "null",
                                  "huge_str"])
def test_odd_value_everywhere_at_once_still_draws(template, name):
    odd = json.loads(ODD[name])

    def spoil(node):
        for k in list(node):
            if isinstance(node[k], dict):
                spoil(node[k])
            elif k not in ("app", "version"):
                node[k] = odd
        return node
    try:
        doc = model.LabelDoc.loads(json.dumps(spoil(full_label(template))))
    except model.LabelFileError:
        return
    check_doc(doc, render_it=True)


def test_whole_file_odd_values():
    for odd in ODD.values():
        with pytest.raises(model.LabelFileError):
            model.LabelDoc.loads(odd)
    for name, odd in ODD.items():
        text = '{"app": "%s", "version": %s}' % (model.APP_KEY, odd)
        try:
            check_doc(model.LabelDoc.loads(text), render_it=False)
        except model.LabelFileError:
            pass


def test_huge_text_is_cut_and_still_draws():
    d = full_label("package")
    del d["picture"]
    d["fields"]["ingredients"] = HUGE
    d["qr"]["value"] = "€" * 5000            # 3 bytes each in UTF-8
    doc = model.LabelDoc.from_dict(d)
    assert len(doc.fields["ingredients"]) == model.MAX_FIELD_CHARS
    assert len(doc.qr["value"].encode("utf-8")) <= qrcodes.MAX_VALUE
    render.render(doc)


def test_half_characters_are_saved(tmp_path):
    d = full_label("simple")
    text = json.dumps(d).replace('"food": "Some food"', '"food": "a\\ud800b"', 1)
    doc = model.LabelDoc.loads(text)
    assert doc.fields["food"] == "a?b"
    model.save(doc, tmp_path / "x")
    p = tmp_path / "raw.txt"
    model.atomic_write_text(p, "c\udc00d")
    assert p.read_text(encoding="utf-8") == "c?d"


def test_label_dates_thousands_of_years_apart():
    d = full_label("simple")
    d["fields"].update(made_on="0001-01-01", use_by="9999-12-31")
    doc = model.LabelDoc.from_dict(d)
    doc.refresh_dates()                 # can't move use-by that far: left as it was
    assert doc.fields["use_by"] == "9999-12-31"


def test_load_from_disk_damaged_content(tmp_path):
    p = tmp_path / "odd.label"
    p.write_text(with_odd(full_label("package"), ("copies",), "1e400"))
    assert model.load(p).copies == 1
    p.write_text(with_odd(full_label("package"), ("stock",), "[1]"))
    assert model.load(p).stock == stocks.DEFAULT_STOCK


def test_unexpected_error_inside_becomes_damaged(monkeypatch):
    text = json.dumps(full_label("simple"))

    def boom(_v):
        raise TypeError("unhashable")
    monkeypatch.setattr(model, "clean_lettering", boom)
    with pytest.raises(model.LabelFileError, match="damaged"):
        model.LabelDoc.loads(text)


def test_helpers():
    assert values.to_int(float("nan"), 0, 10, 5) == 5
    assert values.to_int(float("inf"), 0, 10, 5) == 5
    assert values.to_int(True, 0, 10, 5) == 5
    assert values.to_int(7.6, 0, 10, 5) == 8
    assert values.to_int(10 ** 400, 0, 10, 5) == 5
    assert values.to_int(10 ** 9, 0, 10, 5) == 10
    assert values.choice(["a"], {"a": 1}, "d") == "d"
    assert values.choice({"a": 1}, ("a",), "d") == "d"
    assert values.choice("a", {"a": 1}, "d") == "a"
    assert not values.is_number(float("-inf")) and values.is_number(3)


@pytest.mark.parametrize("cleaner", [pictures.clean, qrcodes.clean])
def test_picture_and_qr_cleaners(cleaner):
    good = {"png": pictures.encode(Image.new("L", (4, 4), 0))}
    keys = ["place", "size", "mode", "threshold", "brightness", "contrast", "what",
            "value", "caption", "invert", "remove_bg", "name"]
    for k in keys:
        for odd in ODD.values():
            v = json.loads(odd)
            out = cleaner(dict(good, **{k: v}))
            assert out is not None
            json.dumps(out, allow_nan=False)


def test_print_settings_and_rolls():
    keys = ["darkness", "zpl_darkness", "speed", "zpl_speed", "nudge_x", "nudge_y",
            "upside_down", "gap", "media", "after", "feed_mm"]
    for k in keys:
        for odd in ODD.values():
            v = json.loads(odd)
            out = printsettings.clean({k: v, "after": "feed"} if k == "feed_mm" else {k: v})
            json.dumps(out, allow_nan=False)
            out = printsettings.clean({"gap": {"medium": v}})
            json.dumps(out, allow_nan=False)
            assert calibrate.last_roll({"roll": {"stock": v}}) is None or \
                isinstance(v, str)
            r = calibrate.last_roll({"roll": {"stock": "medium", "media": v, "date": v,
                                              "same": [v, "large"]}})
            assert r["media"] == "gap" and r["same"] == ["large"]
            stocks.get(v)


def test_settings_file(tmp_path):
    p = tmp_path / "settings.json"
    base = json.loads(json.dumps(settings.DEFAULTS))
    base["printers"] = {"p1": {"nickname": "White", "kind": "tspl", "dpi": 203,
                               "print": {"darkness": 8}, "roll": {"stock": "medium"}}}
    base["recent"] = [{"path": str(tmp_path / "a.label"), "name": "A"}]
    targets = [("ui_scale",), ("date_style",), ("printers",), ("printers", "p1"),
               ("printers", "p1", "kind"), ("printers", "p1", "dpi"),
               ("printers", "p1", "print"), ("printers", "p1", "roll"), ("recent",),
               ("recent", 0), ("advanced",), ("advanced", "density"),
               ("advanced", "zpl_darkness"), ("lettering",), ("kitchen",),
               ("kitchen", "business")]
    for path in targets:
        for odd in ODD.values():
            p.write_text(with_odd(base, path, odd))
            cfg = settings.Settings(p)
            json.dumps(cfg.data, allow_nan=False)
            cfg.recent()
            cfg.nicknames()
            cfg.lettering_for("simple")
            for info in cfg["printers"].values():
                printsettings.clean(info.get("print"))
                calibrate.last_roll(info)
                assert not isinstance(info.get("kind"), (list, dict))
            for k in ("density", "speed", "gap"):
                assert all(values.is_number(n) for n in cfg["advanced"][k].values())


def _library_file(lib, entry):
    return json.dumps({"format": lib.fmt, "version": bakery.LIB_VERSION, lib.key: [entry]})


@pytest.mark.parametrize("cls", [bakery.Products, bakery.Ingredients])
def test_product_and_ingredient_imports(tmp_path, cls):
    lib = cls(tmp_path / "lib.json")
    entry = {"id": "a1", "name": "Bread", "net": "1 lb", "ingredients": "flour",
             "ingredient_ids": ["x"], "contains": "Wheat", "no_allergens": False,
             "storage": "", "best_by_days": 5, "kind": "cottage",
             "last_used": "2026-11-21T09:30:00", "favourite": True, "sub": "",
             "allergens": ["Wheat"], "check": True}
    src = tmp_path / "in.json"
    for k in list(entry) + ["version"]:
        for odd in ODD.values():
            if k == "version":
                text = _library_file(lib, entry).replace(
                    '"version": %d' % bakery.LIB_VERSION, '"version": ' + odd)
            else:
                d = json.loads(_library_file(lib, entry))
                text = with_odd(d, (lib.key, 0, k), odd)
            src.write_text(text)
            try:
                lib.import_file(src)
            except bakery.LibraryError:
                continue
            json.dumps(lib.to_json(), allow_nan=False)
            for item in lib.items:
                if cls is bakery.Products:
                    for t in ("cottage", "package", "simple"):
                        bakery.apply_to_label(t, model.default_fields(t), item)
    # and the same file read as the baker's own
    src.write_text(with_odd(json.loads(_library_file(lib, entry)), (lib.key, 0, "name"),
                            "NaN"))
    cls(src)


def test_bakery_profile(tmp_path):
    p = tmp_path / "my_bakery.json"
    base = {"format": bakery.PROFILE_FORMAT, "version": bakery.PROFILE_VERSION,
            **bakery.PROFILE_DEFAULTS}
    for k in list(base):
        for odd in ODD.values():
            p.write_text(with_odd(base, (k,), odd))
            prof = bakery.Profile(p)
            prof.address_lines()
            prof.metric_for(False)


def test_cottage_overrides(tmp_path):
    rules = cottage.CottageRules(user_dir=tmp_path)
    sid = next(iter(rules.bundled))
    p = tmp_path / cottage.OVERRIDES_NAME
    base = {"format": cottage.OVERRIDES_FORMAT, "version": cottage.OVERRIDES_VERSION,
            "states": {sid: {"statements": {"main": {"text": "Made at home",
                                                     "based_on": "x"}},
                             "own": [{"id": "own1", "text": "Mine", "min_pt": 8}],
                             "required": {"value": ["product_name"],
                                          "based_on": ["product_name"]}}}}
    targets = [("version",), ("states",), ("states", sid), ("states", sid, "statements"),
               ("states", sid, "statements", "main"),
               ("states", sid, "statements", "main", "text"),
               ("states", sid, "statements", "main", "based_on"),
               ("states", sid, "own"), ("states", sid, "own", 0),
               ("states", sid, "own", 0, "min_pt"), ("states", sid, "own", 0, "id"),
               ("states", sid, "own", 0, "text"), ("states", sid, "required"),
               ("states", sid, "required", "value"), ("states", sid, "required", "based_on")]
    for path in targets:
        for odd in ODD.values():
            p.write_text(with_odd(base, path, odd))
            broken = p.with_suffix(".json.broken")
            if broken.exists():
                broken.replace(tmp_path / "old.broken")
            rules.overrides.load()
            eff = rules.effective(sid)
            for s in eff.statements:
                assert s.min_pt is None or values.is_number(s.min_pt)


def _rules_text():
    return cottage.BUILTIN.read_text(encoding="utf-8")


def test_cottage_rules_update_file():
    data = json.loads(_rules_text())
    state = data["states"][0]
    targets = [("version",), ("updated",), ("states",), ("states", 0)] + \
        [("states", 0, k) for k in state]
    if state.get("statements"):
        targets += [("states", 0, "statements", 0, k) for k in state["statements"][0]] + \
            [("states", 0, "statements", 0, "min_pt"), ("states", 0, "statements", 0, "kind")]
    for path in targets:
        for odd in ODD.values():
            try:
                cottage.parse_rules_text(with_odd(data, path, odd))
            except cottage.RulesError:
                pass


def test_printer_update_file():
    data = json.loads(known.BUILTIN.read_text(encoding="utf-8"))
    entry = data["printers"][0]
    for k in ["dpi", "max_width_dots", "max_width_mm", "bt_chunk", "bt_delay_ms", "media",
              "language", "density", "speed", "stocks", "usb", "ieee1284", "windows",
              "verified_on_paper", "notes", "calibrate_by_hand", "id", "name"]:
        entry.setdefault(k, None)
    targets = [("version",), ("printers",), ("printers", 0)] + \
        [("printers", 0, k) for k in entry]
    for path in targets:
        for odd in ODD.values():
            try:
                known.parse_file_text(with_odd(data, path, odd))
            except known.DefinitionError:
                pass
