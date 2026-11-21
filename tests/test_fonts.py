"""Lettering: bundled fonts, font choice in .label files, required wording in a
readable font, per-font minimum sizes, and "Get more fonts" (no real network:
every HTTP call goes to a fake)."""
import io
import json
import urllib.error
from pathlib import Path

import pytest

from food_labeler import fontget, lettering, model, render, settings, stocks, templates

FONTS = Path(lettering.__file__).resolve().parent / "fonts"
LOBSTER = (FONTS / "lobster" / "Lobster-Regular.ttf").read_bytes()
CAVEAT = (FONTS / "caveat" / "Caveat[wght].ttf").read_bytes()
OFL = (FONTS / "lobster" / "OFL.txt").read_bytes()


@pytest.fixture(autouse=True)
def _fresh_registry():
    lettering.reload()
    yield
    lettering.reload()


def cottage_ctx():
    from food_labeler import bakery, cottage
    prof = dict(bakery.PROFILE_DEFAULTS, business="Test Bakes", street="1 Main St",
                city="Town", region="NE", zip="68000", phone="555-0100")
    return {"cottage": {"rule": cottage.CottageRules().effective("NE").to_ctx(),
                        "profile": prof}}


def cottage_doc(name="Pacifico", other="Pacifico"):
    doc = model.LabelDoc("cottage", "large", model.default_fields("cottage"),
                         lettering={"name": name, "other": other})
    doc.fields.update(product="Lemon Shortbread", ingredients="Butter, flour, sugar",
                      contains="Milk, Wheat", storage="Keep in a cool, dry place")
    return doc


# --------------------------------------------------------------------------
# bundled fonts
# --------------------------------------------------------------------------

def test_bundled_fonts_present_licensed_and_render():
    names = [f.name for f in lettering.BUNDLED]
    assert names[0] == "DejaVu Sans" == lettering.DEFAULT
    for want in ("Atkinson Hyperlegible", "Roboto", "Open Sans", "Lato", "Playfair Display",
                 "Pacifico", "Lobster", "Caveat"):
        assert want in names
    total = 0
    for f in lettering.BUNDLED:
        assert Path(f.regular).is_file(), f.name
        if f.name != "DejaVu Sans":
            total += Path(f.regular).stat().st_size + (
                Path(f.bold).stat().st_size if f.bold else 0)
            lic = Path(f.regular).parent / "OFL.txt"
            assert lic.is_file() and "SIL OPEN FONT LICENSE" in lic.read_text().upper()
        ft = lettering.font(f.name, 30)
        assert ft.getname()[0] == f.name
        assert lettering.ink(f.name, 30) > 50
    assert total < 4.2 * 1024 * 1024          # keep the program small


@pytest.mark.parametrize("name", ["DejaVu Sans", "Atkinson Hyperlegible", "Roboto",
                                  "Open Sans", "Lato", "Playfair Display", "Caveat"])
def test_bold_really_is_bold(name):
    assert lettering.get(name).has_bold
    assert lettering.ink(name, 40, True) > lettering.ink(name, 40) * 1.08


def test_only_readable_sans_for_everything_else():
    other = {f.name for f in lettering.other_choices()}
    assert other == {"DejaVu Sans", "Atkinson Hyperlegible", "Roboto", "Open Sans", "Lato"}
    assert {"Pacifico", "Lobster", "Caveat", "Playfair Display"} <= \
        {f.name for f in lettering.name_choices()}


def test_standard_lettering_draws_exactly_as_before():
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"))
    doc.fields["food"] = "Chicken Soup"
    a = render.render(doc, {})
    doc.lettering = {"name": "DejaVu Sans", "other": "dejavu sans"}
    b = render.render(doc, {})
    assert a.image.tobytes() == b.image.tobytes()
    assert all(ln.font == "" for ln in a.layout.lines)


def test_name_font_used_for_the_name_only():
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"),
                         lettering={"name": "Lobster", "other": "Lato"})
    doc.fields.update(food="Chicken Soup", contains="Milk")
    lines = render.render(doc, {}).layout.lines
    assert {ln.font for ln in lines if ln.key == "food"} == {"Lobster"}
    assert {ln.font for ln in lines if ln.key != "food"} == {"Lato"}


# --------------------------------------------------------------------------
# the law stays readable
# --------------------------------------------------------------------------

@pytest.mark.parametrize("script", ["Pacifico", "Lobster", "Caveat", "Playfair Display"])
def test_required_wording_never_in_script_fonts(script):
    res = render.render(cottage_doc(script, script), cottage_ctx())
    keys = set()
    for ln in res.layout.lines:
        if lettering.is_legal(ln.key):
            keys.add(ln.key)
            face = lettering.face_for(ln.font)
            assert face.readable, (ln.key, ln.font)
        if ln.key == "product":
            assert ln.font == script
    assert {"ingredients", "contains", "address"} <= keys
    assert any(k.startswith("statement:") for k in keys)


def test_package_label_allergens_and_address_stay_readable():
    doc = model.LabelDoc("package", "large", model.default_fields("package"),
                         lettering={"name": "Caveat", "other": "Caveat"})
    doc.fields.update(product="Jam", ingredients="Berries, sugar", contains="None",
                      business="My Kitchen", address="1 Main St")
    for ln in render.render(doc, {}).layout.lines:
        if ln.key != "product":
            assert lettering.face_for(ln.font).readable


def test_apply_enforces_even_if_name_key_is_legal():
    b = [templates.Block("ingredients", "x", 30, 12), templates.Block("statement:a", "y", 30, 12)]
    lettering.apply(b, "cottage", {"name": "Pacifico", "other": "Pacifico"})
    assert all(blk.font == "" for blk in b)


# --------------------------------------------------------------------------
# minimum sizes
# --------------------------------------------------------------------------

def test_script_fonts_have_bigger_minimum():
    scales = {f.name: f.min_scale for f in lettering.BUNDLED}
    assert scales["DejaVu Sans"] == 1.0
    for s in ("Pacifico", "Lobster", "Caveat"):
        assert scales[s] >= 1.3
    blocks = [templates.Block("food", "Soup", 100, 22)]
    lettering.apply(blocks, "simple", {"name": "Caveat"})
    assert blocks[0].min == 36          # 22 * 1.6, rounded up


def test_auto_shrink_stops_at_the_fonts_minimum():
    long_name = "Extraordinarily Wonderful Homemade Chicken Noodle Soup With Vegetables"
    sizes = {}
    for name in ("DejaVu Sans", "Caveat"):
        doc = model.LabelDoc("simple", "small", model.default_fields("simple"),
                             lettering={"name": name})
        doc.fields["food"] = long_name
        res = render.render(doc, {})
        sizes[name] = min(ln.size for ln in res.layout.lines if ln.key == "food")
    assert sizes["Caveat"] >= 36            # 22 * 1.6: never smaller, even if it overflows
    assert sizes["DejaVu Sans"] >= 22


def test_statements_never_below_state_minimum_with_any_font():
    ctx = cottage_ctx()
    rule = ctx["cottage"]["rule"]
    assert rule["statements"]
    for f in lettering.other_choices():
        res = render.render(cottage_doc("Pacifico", f.name), ctx)
        for st in rule["statements"]:
            lo = templates.statement_min_dots(st)
            for ln in res.layout.lines:
                if ln.key == "statement:" + st["id"]:
                    assert ln.size >= lo


# --------------------------------------------------------------------------
# .label files
# --------------------------------------------------------------------------

def test_label_file_from_1_1_opens_unchanged(tmp_path):
    """A file written by 1.1.x (no lettering key) opens, draws the same and
    saves back byte for byte."""
    old = {"app": "easy-labels", "version": 1, "template": "simple", "stock": "large",
           "fields": {"food": "Chili", "made_on": "2026-11-20", "use_by": "2026-11-25",
                      "contains": "Milk", "note": "", "made_by": "", "kitchen": False},
           "copies": 2}
    text = json.dumps(old, indent=2, ensure_ascii=False)
    p = tmp_path / "old.label"
    p.write_text(text, encoding="utf-8")
    doc = model.load(p)
    assert doc.lettering == {}
    assert doc.dumps() == text
    assert all(ln.font == "" for ln in render.render(doc, {}).layout.lines)


def test_lettering_round_trip(tmp_path):
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"),
                         lettering={"name": "Pacifico", "other": "Lato"})
    p = model.save(doc, tmp_path / "x")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["lettering"] == {"name": "Pacifico", "other": "Lato"}
    assert data["version"] == 1
    back = model.load(p)
    assert back.lettering == {"name": "Pacifico", "other": "Lato"}
    assert back.copy().lettering == back.lettering


def test_standard_lettering_not_written_and_bad_values_dropped():
    doc = model.LabelDoc(lettering={"name": "DejaVu Sans"})
    assert "lettering" not in doc.to_dict()
    d = model.LabelDoc.from_dict({"app": "easy-labels", "version": 1, "template": "simple",
                                  "lettering": {"name": 5, "other": "x" * 500, "evil": "y"}})
    assert d.lettering == {}
    d = model.LabelDoc.from_dict({"app": "easy-labels", "version": 1, "lettering": "Lobster"})
    assert d.lettering == {}


def test_missing_font_falls_back_to_standard():
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"),
                         lettering={"name": "Dancing Script", "other": "Lato"})
    doc.fields["food"] = "Soup"
    assert lettering.missing(doc.lettering) == ["Dancing Script"]
    res = render.render(doc, {})
    assert not res.overflow
    plain = model.LabelDoc("simple", "large", dict(doc.fields), lettering={"other": "Lato"})
    assert res.image.tobytes() == render.render(plain, {}).image.tobytes()
    # the choice is kept, so it comes back on a computer that has the font
    assert doc.to_dict()["lettering"]["name"] == "Dancing Script"


def test_missing_message_is_gentle():
    from food_labeler.font_dialogs import missing_message
    msg = missing_message("Dancing Script")
    assert "isn't on this computer" in msg and "standard lettering" in msg
    assert msg.endswith("Get the font?")


def test_settings_remember_lettering_per_kind():
    cfg = settings.Settings()
    assert cfg.lettering_for("simple") == {}
    cfg.remember_lettering("simple", {"name": "Lobster", "other": "Lato", "junk": 1})
    again = settings.Settings()
    assert again.lettering_for("simple") == {"name": "Lobster", "other": "Lato"}
    assert again.lettering_for("package") == {}


# --------------------------------------------------------------------------
# Get more fonts (fake HTTP)
# --------------------------------------------------------------------------

META_STATIC = """name: "Dancing Script"
license: "OFL"
category: "HANDWRITING"
fonts {
  name: "Dancing Script"
  style: "normal"
  weight: 400
  filename: "DancingScript-Regular.ttf"
}
fonts {
  name: "Dancing Script"
  style: "normal"
  weight: 700
  filename: "DancingScript-Bold.ttf"
}
fonts {
  style: "italic"
  weight: 400
  filename: "DancingScript-Italic.ttf"
}
"""
META_VAR = """name: "Dancing Script"
license: "OFL"
category: "HANDWRITING"
fonts {
  name: "Dancing Script"
  style: "normal"
  weight: 400
  filename: "DancingScript[wght].ttf"
}
axes {
  tag: "wght"
  min_value: 400.0
  max_value: 700.0
}
source {
  files {
    source_file: "x"
    dest_file: "y"
  }
}
"""
RAW = "https://raw.githubusercontent.com/google/fonts/main/"


class FakeWeb:
    """Answers GET by URL; anything else is a 404. Records what was asked."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def __call__(self, url, limit):
        fontget.check_url(url)
        self.asked.append(url)
        v = self.pages.get(url)
        if v is None:
            raise fontget.HttpStatus(404)
        if isinstance(v, Exception):
            raise v
        if len(v) > limit:
            raise fontget.FontGetError(fontget.TOO_BIG)
        return v


def test_url_building_and_folder_names():
    assert fontget.folder_name("Dancing Script") == "dancingscript"
    assert fontget.file_url("ofl", "roboto", "Roboto[wdth,wght].ttf") == \
        RAW + "ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf"
    assert fontget.api_url("apache", "x") == \
        "https://api.github.com/repos/google/fonts/contents/apache/x"
    for bad in ("../../etc/passwd", "a/b.ttf", ".hidden.ttf", ""):
        with pytest.raises(fontget.FontGetError):
            fontget.file_url("ofl", "x", bad)
    with pytest.raises(fontget.FontGetError):
        fontget.file_url("evil", "x", "a.ttf")
    for bad in ("Dancing/Script", "x" * 61, "   ", "a;b"):
        with pytest.raises(fontget.NotFound):
            fontget.clean_family(bad)
    assert fontget.clean_family("  Dancing   Script ") == "Dancing Script"


@pytest.mark.parametrize("url", [
    "http://raw.githubusercontent.com/google/fonts/main/x",
    "https://example.com/font.ttf",
    "https://raw.githubusercontent.com.evil.com/x",
    "https://user:pw@github.com/x",
    "https://github.com:8443/x",
    "ftp://github.com/x",
])
def test_host_allow_list(url):
    with pytest.raises(fontget.FontGetError):
        fontget.check_url(url)


def test_allowed_hosts_pass():
    for url in (RAW + "ofl/x/OFL.txt", "https://github.com/google/fonts",
                "https://api.github.com/repos/google/fonts/contents/ofl/x"):
        assert fontget.check_url(url) == url


def test_redirect_to_another_host_is_refused():
    import urllib.request
    h = fontget._SafeRedirect()
    req = urllib.request.Request(RAW + "ofl/x/a.ttf")
    with pytest.raises(fontget.FontGetError):
        h.redirect_request(req, None, 302, "Found", {}, "https://evil.example/a.ttf")


def test_read_limited_refuses_big_answers():
    class Resp:
        def __init__(self, data, length=None):
            self.f = io.BytesIO(data)
            self.headers = {"Content-Length": str(length)} if length else {}

        def read(self, n):
            return self.f.read(n)
    assert fontget.read_limited(Resp(b"abc"), 10) == b"abc"
    with pytest.raises(fontget.FontGetError, match="too big"):
        fontget.read_limited(Resp(b"x" * 100), 10)          # no Content-Length
    with pytest.raises(fontget.FontGetError, match="too big"):
        fontget.read_limited(Resp(b"", 10 ** 9), 10)          # Content-Length says so


def test_offline_says_needs_the_internet(monkeypatch):
    class Opener:
        def open(self, *a, **k):
            raise urllib.error.URLError(OSError("Name or service not known"))
    monkeypatch.setattr(fontget.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(fontget.FontGetError, match="needs the internet"):
        fontget.http_get(RAW + "ofl/x/METADATA.pb")
    with pytest.raises(fontget.FontGetError):
        fontget.http_get("https://example.com/x")          # never even tried


def test_timeout_message(monkeypatch):
    class Opener:
        def open(self, *a, **k):
            assert k.get("timeout") == fontget.TIMEOUT
            raise TimeoutError()
    monkeypatch.setattr(fontget.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(fontget.FontGetError, match="in time"):
        fontget.http_get(RAW + "ofl/x/METADATA.pb")


def test_parse_metadata():
    m = fontget.parse_metadata(META_STATIC)
    assert m["name"] == "Dancing Script" and m["category"] == "HANDWRITING"
    assert fontget.pick_files(m) == ("DancingScript-Regular.ttf", "DancingScript-Bold.ttf",
                                     False, True)
    v = fontget.parse_metadata(META_VAR)
    assert fontget.pick_files(v) == ("DancingScript[wght].ttf", "", True, True)


def test_fetch_static_family_and_install(tmp_path):
    web = FakeWeb({RAW + "ofl/dancingscript/METADATA.pb": META_STATIC.encode(),
                   RAW + "ofl/dancingscript/DancingScript-Regular.ttf": LOBSTER,
                   RAW + "ofl/dancingscript/DancingScript-Bold.ttf": LOBSTER,
                   RAW + "ofl/dancingscript/OFL.txt": OFL})
    c = fontget.fetch_family("dancing script", get=web)
    assert c.name == "Dancing Script" and c.bold and c.license_text == OFL
    assert all("raw.githubusercontent.com" in u for u in web.asked)
    face = fontget.install(c)
    folder = settings.data_dir() / "fonts" / "dancingscript"
    assert {p.name for p in folder.iterdir()} == {"DancingScript-Regular.ttf",
                                                  "DancingScript-Bold.ttf", "OFL.txt",
                                                  "font.json"}
    assert face.name == "Dancing Script" and not face.bundled and not face.readable
    assert face.min_scale >= 1.3                     # handwriting
    assert "Dancing Script" in [f.name for f in lettering.name_choices()]
    assert "Dancing Script" not in [f.name for f in lettering.other_choices()]
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"),
                         lettering={"name": "Dancing Script"})
    doc.fields["food"] = "Soup"
    assert {ln.font for ln in render.render(doc, {}).layout.lines
            if ln.key == "food"} == {"Dancing Script"}
    assert lettering.missing(doc.lettering) == []


def test_variable_only_family_downloads_one_file():
    web = FakeWeb({RAW + "apache/dancingscript/METADATA.pb": META_VAR.encode(),
                   RAW + "apache/dancingscript/DancingScript%5Bwght%5D.ttf": CAVEAT,
                   RAW + "apache/dancingscript/LICENSE.txt": b"Apache License"})
    c = fontget.fetch_family("Dancing Script", get=web)
    assert c.variable and c.can_bold and not c.bold
    assert c.license_name == "Apache License 2.0"
    assert web.asked[0].endswith("ofl/dancingscript/METADATA.pb")   # tried ofl first
    face = fontget.install(c)
    assert face.variable and face.has_bold
    assert lettering.ink(face.name, 40, True) > lettering.ink(face.name, 40)


def test_listing_used_when_metadata_lists_no_files():
    import json as _j
    listing = [{"type": "file", "name": "Foo-Regular.ttf"}, {"type": "file", "name": "OFL.txt"},
               {"type": "file", "name": "Foo-Italic.ttf"}]
    web = FakeWeb({RAW + "ufl/foo/METADATA.pb": b'name: "Foo"\n',
                   "https://api.github.com/repos/google/fonts/contents/ufl/foo":
                       _j.dumps(listing).encode(),
                   RAW + "ufl/foo/Foo-Regular.ttf": LOBSTER})
    c = fontget.fetch_family("Foo", get=web)
    assert c.regular_name == "Foo-Regular.ttf" and not c.bold


def test_not_found_message():
    with pytest.raises(fontget.NotFound) as e:
        fontget.fetch_family("Comic Sands", get=FakeWeb({}))
    assert "Couldn't find a font called “Comic Sands”" in str(e.value)
    assert "fonts.google.com" in str(e.value)


def test_rate_limit_is_a_plain_message():
    web = FakeWeb({RAW + "ofl/foo/METADATA.pb": b'name: "Foo"\n',
                   "https://api.github.com/repos/google/fonts/contents/ofl/foo":
                       fontget.HttpStatus(403, {"X-RateLimit-Remaining": "0"})})
    with pytest.raises(fontget.FontGetError) as e:
        fontget.fetch_family("Foo", get=web)
    assert "try again later" in str(e.value)


def test_invalid_font_file_refused():
    web = FakeWeb({RAW + "ofl/foo/METADATA.pb": META_STATIC.replace(
        "DancingScript", "Foo").encode(),
        RAW + "ofl/foo/Foo-Regular.ttf": b"<html>not a font</html>" * 10})
    with pytest.raises(fontget.FontGetError, match="isn't a font"):
        fontget.fetch_family("Foo", get=web)
    with pytest.raises(fontget.FontGetError):
        fontget.check_font_bytes(b"\x00\x01\x00\x00" + b"\x00" * 200)   # right magic, junk


def test_font_too_big_refused():
    web = FakeWeb({RAW + "ofl/foo/METADATA.pb": META_STATIC.replace(
        "DancingScript", "Foo").encode(),
        RAW + "ofl/foo/Foo-Regular.ttf": LOBSTER + b"\x00" * (fontget.MAX_FONT_BYTES)})
    with pytest.raises(fontget.FontGetError, match="too big"):
        fontget.fetch_family("Foo", get=web)


def test_bundled_font_is_not_downloaded_again():
    with pytest.raises(fontget.FontGetError, match="comes with Food Labeler"):
        fontget.fetch_family("pacifico", get=FakeWeb({}))


def test_add_font_file_from_computer_and_remove(tmp_path):
    src = tmp_path / "MyHand.ttf"
    src.write_bytes(LOBSTER)
    c = fontget.from_file(src)
    assert c.name == "Lobster"              # the font's own family name
    with pytest.raises(fontget.FontGetError, match="comes with"):
        fontget.install(c)                  # same name as a bundled font
    c.name = "My Hand"
    face = fontget.install(c)
    assert face.folder and Path(face.folder).parent == settings.data_dir() / "fonts"
    (tmp_path / "x.ttf").write_bytes(b"nope")
    with pytest.raises(fontget.FontGetError):
        fontget.from_file(tmp_path / "x.ttf")
    with pytest.raises(fontget.FontGetError):
        fontget.from_file(tmp_path / "x.txt")
    fontget.remove("My Hand")
    assert lettering.get("My Hand") is None and not Path(face.folder).exists()
    with pytest.raises(fontget.FontGetError):
        fontget.remove("Pacifico")
    assert Path(lettering.get("Pacifico").regular).is_file()


def test_user_fonts_live_in_the_data_folder_not_the_bundle(tmp_path, monkeypatch):
    c = fontget.Candidate(name="Keeper", regular_name="Keeper-Regular.ttf", regular=LOBSTER)
    face = fontget.install(c)
    assert lettering.user_dir() == settings.data_dir() / "fonts"
    assert FONTS not in Path(face.regular).parents
    # "update": a new program run with the same data folder still has it
    lettering._loaded_for = None
    assert lettering.get("Keeper") is not None
    # a broken manifest is skipped, not fatal
    bad = settings.data_dir() / "fonts" / "broken"
    bad.mkdir()
    (bad / "font.json").write_text("{nope")
    assert "keeper" in lettering.reload()
    # another data folder (another user) doesn't see it
    monkeypatch.setenv("FOOD_LABELER_DATA", str(tmp_path / "other"))
    lettering.registry()
    assert lettering.get("Keeper") is None


def test_every_url_on_an_allowed_host():
    web = FakeWeb({})
    with pytest.raises(fontget.NotFound):
        fontget.fetch_family("Some Font", get=web)
    assert len(web.asked) == 3
    assert [u.split("/")[6] for u in web.asked] == ["ofl", "apache", "ufl"]
    assert all(u.startswith("https://raw.githubusercontent.com/google/fonts/") for u in web.asked)


def test_stock_sizes_unaffected():
    # sanity: a script font on every stock the simple label allows still fits a short name
    for sid in templates.ALLOWED_STOCKS["simple"]:
        doc = model.LabelDoc("simple", sid, model.default_fields("simple"),
                             lettering={"name": "Pacifico"})
        doc.fields["food"] = "Soup"
        assert not render.render(doc, {}).overflow, stocks.get(sid).name
