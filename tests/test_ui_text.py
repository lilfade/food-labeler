"""The words and choices behind the main window's new layout, without a window:
text sizes, the chips above the form, Open ▾, My products (recently used,
favourites, search, filling each kind of label) and the Picture window's
"mostly black" line."""
import datetime as dt
import json

import pytest
from PIL import Image

from food_labeler import bakery, model, pictures, settings, ui_text


# ---------------------------------------------------------------- text size

def test_four_text_sizes_and_normal_is_smaller_than_the_old_default():
    assert [w for _i, w, _s in ui_text.TEXT_SIZES] == ["Small", "Normal", "Large",
                                                       "Extra large"]
    scales = [s for _i, _w, s in ui_text.TEXT_SIZES]
    assert scales == sorted(scales) and all(s in ui_text.SCALES for s in scales)
    assert ui_text.scale_for("normal") == ui_text.DEFAULT_SCALE < ui_text.OLD_DEFAULT_SCALE
    assert ui_text.scale_for("large") == ui_text.OLD_DEFAULT_SCALE
    assert ui_text.scale_for("nonsense") == ui_text.DEFAULT_SCALE


@pytest.mark.parametrize("scale, sid", [(0.7, "small"), (0.8, "normal"), (0.9, "large"),
                                        (1.0, "large"), (1.1, "xl"), (1.2, "xl"),
                                        (1.7, "xl"), (0.5, "small"), ("junk", "normal")])
def test_nearest_choice(scale, sid):
    assert ui_text.text_size_id(scale) == sid


def test_steps_stop_at_the_ends_and_keep_old_sizes():
    assert ui_text.step_scale(0.8, 1) == 0.9
    assert ui_text.step_scale(0.7, -1) == 0.7
    assert ui_text.step_scale(1.7, 1) == 1.7
    for old in (0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.7):      # every size 1.4 offered
        assert ui_text.nearest_scale(old) == old
    assert ui_text.text_size_words(1.0) == "Large"
    assert ui_text.text_size_words(0.9) == "Large (a little smaller)"
    assert ui_text.text_size_words(1.35) == "Extra large (a little bigger)"


def test_new_installs_get_normal_and_existing_users_keep_their_size():
    assert settings.Settings()["ui_scale"] == ui_text.DEFAULT_SCALE        # no file yet
    path = settings.data_dir() / "settings.json"
    path.write_text(json.dumps({"date_style": "us"}))                    # older file
    assert settings.Settings()["ui_scale"] == ui_text.OLD_DEFAULT_SCALE
    path.write_text(json.dumps({"ui_scale": 1.35}))
    assert settings.Settings()["ui_scale"] == 1.35


# ---------------------------------------------------------------- chips

def test_chip_words():
    assert ui_text.kind_chip("simple") == "Kind: Simple food label"
    assert ui_text.kind_chip("cottage") == "Kind: Cottage food label"
    assert ui_text.size_chip("large") == "Size: 4 × 2 in"
    assert ui_text.size_chip("xl") == "Size: 4 × 6 in"
    assert ui_text.size_chip("round") == "Size: 2 in round"
    assert ui_text.picture_chip(None) == "+ Picture"
    assert ui_text.picture_chip({"name": "Our logo"}) == "Picture: Our logo"
    assert ui_text.picture_chip({"name": "A very long picture name indeed"}).endswith("…")
    assert ui_text.qr_chip(None) == "+ QR code"
    assert ui_text.qr_chip({"what": "link", "value": ""}) == "+ QR code"     # holds nothing
    assert ui_text.qr_chip({"what": "phone", "value": "555 0100"}) == "QR code: Phone"
    assert ui_text.lettering_chip("simple", {}) == "Lettering: Standard"
    assert ui_text.lettering_chip("simple", {"name": "Pacifico", "other": "Lato"}) == \
        "Lettering: Pacifico · Lato"
    assert ui_text.lettering_chip("free", {"name": "Pacifico", "other": "Lato"}) == \
        "Lettering: Pacifico"


def test_every_kind_and_size_has_a_chip():
    from food_labeler import stocks
    for t in model.TEMPLATES:
        assert ui_text.kind_chip(t).startswith("Kind: ")
    for s in stocks.ORDER:
        assert len(ui_text.size_chip(s)) < 22


# ---------------------------------------------------------------- Open ▾

def test_open_menu_lists_recent_labels_newest_first(tmp_path):
    s = settings.Settings()
    for name in ("Soup", "Stew", "Bread"):
        s.add_recent(model.save(model.LabelDoc(), tmp_path / name), name)
    items = ui_text.recent_menu(s.recent())
    assert [w for w, _p in items] == ["Bread", "Stew", "Soup"]
    assert all(p.endswith(".label") for _w, p in items)


def test_open_menu_says_which_folder_for_two_labels_with_one_name(tmp_path):
    rec = [{"path": str(tmp_path / "a" / "Soup.label"), "name": "Soup"},
           {"path": str(tmp_path / "b" / "Soup.label"), "name": "Soup"},
           {"path": "", "name": "broken"}]
    assert ui_text.recent_menu(rec) == [("Soup  (in a)", rec[0]["path"]),
                                        ("Soup  (in b)", rec[1]["path"])]
    many = [{"path": f"/x/{i}.label", "name": f"L{i}"} for i in range(20)]
    assert len(ui_text.recent_menu(many)) == ui_text.MAX_OPEN_MENU


# ---------------------------------------------------------------- My products

def _lib(tmp_path):
    lib = bakery.Products(tmp_path / bakery.PRODUCTS_NAME)
    for name in ("Apple Pie", "Banana Bread", "Sourdough Loaf", "Cinnamon Rolls",
                 "Pumpkin Bread", "Lemon Bars", "Zucchini Bread"):
        lib.put({"name": name})
    return lib


def test_old_product_files_still_open_and_keep_new_fields(tmp_path):
    path = tmp_path / bakery.PRODUCTS_NAME
    path.write_text(json.dumps({"format": bakery.PRODUCTS_FORMAT, "version": 1,
                                "products": [{"id": "a1", "name": "Pie", "net": "8 oz"}]}))
    lib = bakery.Products(path)
    p = lib.get("a1")
    assert (p["kind"], p["last_used"], p["favourite"]) == ("", "", False)
    lib.mark_used("a1", "2026-11-21T09:30:00")
    lib.set_favourite("a1", True)
    again = bakery.Products(path).get("a1")
    assert again["last_used"] == "2026-11-21T09:30:00" and again["favourite"] is True
    assert bakery.clean_product({"name": "x", "last_used": "yesterday", "favourite": "yes",
                                 "kind": "sticker"}) | {"id": ""} == \
        bakery.clean_product({"name": "x"}) | {"id": ""}


def test_quick_products_favourites_then_recent_then_by_name(tmp_path):
    lib = _lib(tmp_path)
    assert [p["name"] for p in lib.quick(3)] == ["Apple Pie", "Banana Bread",
                                                 "Cinnamon Rolls"]
    lib.mark_used(lib.find("Zucchini Bread")["id"], "2026-11-20T08:00:00")
    lib.mark_used(lib.find("Lemon Bars")["id"], "2026-11-21T08:00:00")
    lib.set_favourite(lib.find("Pumpkin Bread")["id"], True)
    assert [p["name"] for p in lib.quick()] == ["Pumpkin Bread", "Lemon Bars",
                                                "Zucchini Bread", "Apple Pie",
                                                "Banana Bread", "Cinnamon Rolls"]
    assert len(lib.quick()) == bakery.QUICK_PRODUCTS


def test_mark_used_now(tmp_path):
    lib = _lib(tmp_path)
    pid = lib.find("Lemon Bars")["id"]
    lib.mark_used(pid)
    assert lib.get(pid)["last_used"][:4].isdigit()
    assert lib.quick(1)[0]["id"] == pid
    lib.mark_used("no-such-id")                       # quietly nothing


@pytest.mark.parametrize("query, names", [
    ("bread", ["Banana Bread", "Pumpkin Bread", "Zucchini Bread"]),
    ("BREAD", ["Banana Bread", "Pumpkin Bread", "Zucchini Bread"]),
    ("sour", ["Sourdough Loaf"]),
    ("b", ["Banana Bread", "Lemon Bars", "Pumpkin Bread", "Zucchini Bread"]),
    ("pie apple", ["Apple Pie"]),
    ("lemon pie", []),
    ("", ["Apple Pie", "Banana Bread", "Cinnamon Rolls", "Lemon Bars", "Pumpkin Bread",
          "Sourdough Loaf"]),
])
def test_search(tmp_path, query, names):
    assert [p["name"] for p in _lib(tmp_path).search(query)] == names


def test_search_prefers_names_starting_with_it_then_recent(tmp_path):
    lib = _lib(tmp_path)
    lib.mark_used(lib.find("Zucchini Bread")["id"], "2026-11-21T08:00:00")
    assert [p["name"] for p in lib.search("bread")][0] == "Zucchini Bread"
    assert [p["name"] for p in lib.search("b")][:1] == ["Banana Bread"]   # starts with "b"


PRODUCT = bakery.clean_product({"name": "Lemon Bars", "net": "8 oz", "ingredients": "Flour",
                                "contains": "Wheat, Eggs", "storage": "Keep cool",
                                "best_by_days": 4})
TODAY = dt.date(2026, 11, 21)


def test_product_on_a_simple_label():
    f = bakery.apply_to_label("simple", model.default_fields("simple", TODAY), PRODUCT, TODAY)
    assert (f["food"], f["contains"], f["note"]) == ("Lemon Bars", "Wheat, Eggs", "Keep cool")
    assert (f["made_on"], f["use_by"]) == ("2026-11-21", "2026-11-25")
    assert "ingredients" not in f


def test_product_on_a_package_label():
    f = bakery.apply_to_label("package", model.default_fields("package", TODAY), PRODUCT,
                              TODAY)
    assert (f["product"], f["net"], f["ingredients"], f["contains"]) == \
        ("Lemon Bars", "8 oz", "Flour", "Wheat, Eggs")
    assert f["best_by"] == "2026-11-25"
    assert f["business"] == ""                          # kitchen details untouched


def test_product_on_a_cottage_label_is_unchanged_behaviour():
    a = bakery.apply_to_label("cottage", model.default_fields("cottage", TODAY), PRODUCT, TODAY)
    b = bakery.apply_product(model.default_fields("cottage", TODAY), PRODUCT, TODAY)
    assert a == b


def test_saving_from_a_simple_label_keeps_what_it_does_not_show():
    existing = dict(PRODUCT, id="p1", favourite=True, last_used="2026-11-01T10:00:00",
                    kind="cottage")
    fields = dict(model.default_fields("simple", TODAY), food="Lemon Bars",
                  contains="Wheat", note="Keep frozen")
    p = bakery.product_from_label("simple", fields, "Lemon Bars", existing)
    assert (p["id"], p["ingredients"], p["net"]) == ("p1", "Flour", "8 oz")
    assert (p["contains"], p["storage"], p["best_by_days"]) == ("Wheat", "Keep frozen", 5)
    assert (p["kind"], p["favourite"], p["last_used"]) == ("simple", True,
                                                           "2026-11-01T10:00:00")


def test_saving_from_package_and_cottage():
    f = dict(model.default_fields("package", TODAY), product="Pie", net="1 lb",
             ingredients="Apples", contains="Wheat")
    p = bakery.product_from_label("package", f, "Pie", today=TODAY)
    assert (p["kind"], p["net"], p["ingredients"], p["best_by_days"]) == \
        ("package", "1 lb", "Apples", 14)
    c = dict(model.default_fields("cottage", TODAY), product="Pie", net="1 lb")
    p = bakery.product_from_label("cottage", c, "Pie")
    assert (p["kind"], p["net"], p["best_by_days"]) == ("cottage", "1 lb", 7)


def test_which_kind_a_product_asks_for():
    assert bakery.product_kind({"kind": "simple"}) == "simple"
    assert bakery.product_kind({"kind": ""}) == "cottage"            # saved before 1.5.0
    assert bakery.product_kind({}) == "cottage"
    assert set(bakery.PRODUCT_KINDS) <= set(model.TEMPLATES)


# ---------------------------------------------------------------- mostly black

def test_black_share():
    assert pictures.black_share(Image.new("1", (10, 10), 0)) == 1.0
    assert pictures.black_share(Image.new("1", (10, 10), 1)) == 0.0
    im = Image.new("1", (10, 10), 1)
    im.paste(0, (0, 0, 10, 7))
    assert pictures.black_share(im) == pytest.approx(0.7)
    assert pictures.black_share(Image.new("1", (0, 0))) == 0.0


@pytest.mark.parametrize("share, shown", [(0.0, False), (0.5, False), (0.65, False),
                                          (0.66, True), (1.0, True)])
def test_mostly_black_threshold(share, shown):
    assert bool(pictures.mostly_black_warning(share)) is shown


def test_mostly_black_words():
    logo = pictures.mostly_black_warning(0.9)
    assert logo == ("This picture will print mostly black. Try moving the slider toward "
                    "Lighter, or choose Photo (tiny dots).")
    swapped = pictures.mostly_black_warning(0.9, invert=True)
    assert swapped.startswith("“Swap black and white” is on") and \
        swapped.endswith(logo)
    assert "Brighter" in pictures.mostly_black_warning(0.9, mode="photo")
    assert pictures.mostly_black_warning(0.1, invert=True) == ""


def test_an_orange_cartoon_does_not_print_as_a_black_block():
    """The kind of picture that once printed as a black block: warm colours on white."""
    from PIL import ImageDraw
    im = Image.new("RGB", (300, 200), "white")
    d = ImageDraw.Draw(im)
    d.ellipse((40, 20, 260, 180), fill=(240, 140, 40), outline=(90, 50, 20), width=6)
    d.ellipse((100, 70, 130, 100), fill=(90, 50, 20))
    pic = pictures.new_picture(pictures.normalise(im), "cartoon")
    share = pictures.black_share(pictures.to_print(pic, 300, 200))
    assert pictures.mostly_black_warning(share) == ""
