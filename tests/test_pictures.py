"""Pictures on labels: reading files, black-and-white conversion, placement,
the wording winning space, round labels, .label files and My pictures."""
import base64
import io
import json
import math

import pytest
from PIL import Image, ImageDraw

from food_labeler import cottage, model, pictures, render, templates

import render_cases


def as_png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def gradient(w=256, h=64):
    im = Image.new("L", (w, h))
    im.putdata([x * 255 // (w - 1) for _y in range(h) for x in range(w)])
    return im


def colour_logo(w=600, h=300, transparent=True):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((20, 20, 280, 280), fill=(200, 30, 30, 255))          # red disc
    d.rectangle((320, 140, 580, 145), fill=(20, 60, 200, 255))      # thin blue line, 6 px
    return im


def pic_of(im, **kw):
    return pictures.new_picture(pictures.normalise(im), "test.png", **kw)


def black(img) -> int:
    return img.convert("L").histogram()[0]


# ---- reading files -----------------------------------------------------------

def test_modes_are_normalised():
    cases = {
        "CMYK": Image.new("CMYK", (10, 10), (0, 0, 0, 255)),
        "P": Image.new("P", (10, 10), 3),
        "I;16": Image.new("I;16", (10, 10), 40000),
        "F": Image.new("F", (10, 10), 0.5),
        "LA": Image.new("LA", (10, 10), (0, 128)),
        "1": Image.new("1", (10, 10), 0),
    }
    for name, im in cases.items():
        out = pictures.normalise(im)
        assert out.mode in ("RGB", "RGBA", "L"), name
        assert out.size == (10, 10)
    assert pictures.normalise(cases["LA"]).mode == "RGBA"
    # 16-bit picture: scaled into 8 bits, not clipped to white
    g = Image.new("I;16", (2, 1))
    g.putpixel((0, 0), 1000)
    g.putpixel((1, 0), 60000)
    n = pictures.normalise(g)
    assert n.getpixel((0, 0)) < n.getpixel((1, 0))
    p = Image.new("P", (4, 4), 0)
    p.info["transparency"] = 0
    assert pictures.normalise(p).mode == "RGBA"


def test_exif_rotation(tmp_path):
    im = Image.new("RGB", (200, 100), "white")
    exif = Image.Exif()
    exif[0x0112] = 6                                     # rotate 90° when shown
    path = tmp_path / "phone.jpg"
    im.save(path, exif=exif.tobytes())
    got, name = pictures.read_file(path)
    assert got.size == (100, 200) and name == "phone.jpg"


def test_animated_gif_first_frame(tmp_path):
    frames = [Image.new("L", (20, 20), 0), Image.new("L", (20, 20), 255)]
    path = tmp_path / "a.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], loop=0)
    got, _ = pictures.read_file(path)
    assert got.convert("L").getpixel((5, 5)) == 0


def test_size_limits(tmp_path, monkeypatch):
    assert pictures.MAX_FILE_BYTES == 25 * 1024 * 1024
    assert pictures.MAX_PIXELS == 40_000_000
    big = tmp_path / "big.png"
    with open(big, "wb") as f:
        f.seek(pictures.MAX_FILE_BYTES + 10)
        f.write(b"\0")
    with pytest.raises(pictures.PictureError, match="too big"):
        pictures.read_file(big)
    monkeypatch.setattr(pictures, "MAX_PIXELS", 1000)
    p = tmp_path / "wide.png"
    Image.new("L", (100, 20)).save(p)
    with pytest.raises(pictures.PictureError, match="too big"):
        pictures.read_file(p)
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not a picture")
    with pytest.raises(pictures.PictureError, match="can't read"):
        pictures.read_file(junk)


def test_big_pictures_are_stored_smaller():
    pic = pic_of(Image.new("RGB", (4000, 1000), "white"))
    im = Image.open(io.BytesIO(base64.b64decode(pic["png"])))
    assert max(im.size) == pictures.MAX_STORED_SIDE and im.size == (2000, 500)


# ---- black and white ---------------------------------------------------------

def test_logo_mode_threshold_on_gradient():
    pic = pic_of(gradient())
    out = pictures.to_print(pic, 256, 64)
    assert out.mode == "1" and out.size == (256, 64)
    row = [1 if out.getpixel((x, 30)) else 0 for x in range(256)]
    edge = row.index(1)
    assert all(v == 0 for v in row[:edge]) and all(v == 1 for v in row[edge:])
    assert 100 < edge < 160                               # Otsu splits the ramp near the middle
    darker = pictures.to_print(dict(pic, threshold=200), 256, 64)
    lighter = pictures.to_print(dict(pic, threshold=60), 256, 64)
    assert black(lighter) < black(out) < black(darker)
    inv = pictures.to_print(dict(pic, invert=True), 256, 64)
    assert inv.getpixel((5, 30)) != 0 and inv.getpixel((250, 30)) == 0


def test_photo_mode_dithers():
    pic = pic_of(gradient(), mode="photo")
    out = pictures.to_print(pic, 256, 64)
    cols = [sum(1 for y in range(64) if out.getpixel((x, y)) == 0) for x in range(256)]
    assert cols[10] > 50 and cols[245] < 14                # dark left, light right
    mid = cols[120:136]
    assert all(10 < c < 54 for c in mid)                   # tiny dots, not solid
    brighter = pictures.to_print(dict(pic, brightness=60), 256, 64)
    assert black(brighter) < black(out)
    contrast = pictures.to_print(dict(pic, contrast=80), 256, 64)
    assert contrast.tobytes() != out.tobytes()


def test_colour_logo_and_thin_lines_survive():
    pic = pic_of(colour_logo())
    out = pictures.to_print(pic, 300, 150)                 # half size
    assert out.getpixel((75, 75)) == 0                     # the red disc is solid black
    line = [out.getpixel((x, 71)) for x in range(165, 285)] + \
           [out.getpixel((x, 72)) for x in range(165, 285)]
    assert line.count(0) > 100                             # the 6 px line is still there
    assert out.getpixel((5, 5)) != 0                     # transparent corner = paper


def test_transparency_is_paper_even_when_swapped():
    pic = pic_of(colour_logo(), invert=True)
    out = pictures.to_print(pic, 300, 150)
    assert out.getpixel((75, 75)) != 0                   # the disc turned white
    assert out.getpixel((5, 5)) != 0                     # see-through stays paper


def test_remove_background():
    im = Image.new("L", (100, 100), 242)                   # off-white paper in a photo
    ImageDraw.Draw(im).rectangle((30, 30, 70, 70), fill=20)
    pic = pic_of(im, mode="photo")
    keep = pictures.to_print(pic, 100, 100)
    gone = pictures.to_print(dict(pic, remove_bg=True), 100, 100)
    corner = [(x, y) for x in range(0, 20) for y in range(0, 20)]
    assert any(keep.getpixel(p) == 0 for p in corner)      # dithered dots on the paper
    assert all(gone.getpixel(p) != 0 for p in corner)    # removed
    assert gone.getpixel((50, 50)) == 0


def test_clean_rejects_junk():
    assert pictures.clean(None) is None and pictures.clean({"png": ""}) is None
    assert pictures.clean({"png": "!!!"}) is None
    c = pictures.clean({"png": "iVBORw0KGgo=", "place": "nowhere", "size": 999,
                        "mode": "x", "threshold": 0, "brightness": -500})
    assert c["place"] == "above" and c["size"] == 100 and c["mode"] == "logo"
    assert c["threshold"] == 1 and c["brightness"] == -100


# ---- placement ---------------------------------------------------------------

def doc_with_picture(template="simple", stock="large", **pic):
    d = model.LabelDoc(template, stock, model.default_fields(template, render_cases.TODAY))
    d.fields.update(render_cases.SAMPLE.get(template, {}))
    d.picture = pic_of(colour_logo(), **pic)
    return d


@pytest.mark.parametrize("dpi", [203, 300])
def test_placements_reflow_text(dpi):
    for place in ("above", "left", "right", "corner"):
        res = render.render(doc_with_picture(place=place, size=40), render_cases.CTX, dpi=dpi)
        assert not res.overflow, place
        (x, y, img), = res.layout.images
        x1, y1 = x + img.width, y + img.height
        reg = templates.region_for(res.stock)
        assert reg.left - 1 <= x and x1 <= reg.right + 1 and reg.top - 1 <= y
        for ln in res.layout.lines:
            w = templates.text_width(ln.text, ln.size, ln.bold, ln.font)
            lh = templates.line_height(ln.size, ln.bold, ln.font)
            overlap_y = ln.y < y1 and ln.y + lh > y
            overlap_x = ln.x < x1 and ln.x + w > x
            assert not (overlap_x and overlap_y), (place, ln)
            if place == "above":
                assert ln.y >= y1
        assert black(img) > 0


def test_picture_label_fit_fill_and_words():
    for place in ("fit", "fill"):
        d = model.LabelDoc("picture", "large", {"text": "High Thyme Kitchen"})
        d.picture = pic_of(colour_logo(), place=place, size=100)
        res = render.render(d, {})
        assert not res.overflow
        (x, y, img), = res.layout.images
        words = [ln for ln in res.layout.lines if ln.key == "text"]
        assert words and all(ln.y >= y + img.height - 1 for ln in words)
        if place == "fill":
            reg = templates.region_for(res.stock)
            assert img.width >= reg.full_width - 2


def test_round_stock_keeps_picture_inside_circle():
    for template, place in (("picture", "fill"), ("picture", "fit"), ("simple", "left")):
        d = model.LabelDoc(template, "round", model.default_fields(template))
        d.fields["text" if template == "picture" else "food"] = "Seal"
        d.picture = pic_of(Image.new("L", (300, 300), 0), place=place, size=60)
        for dpi in (203, 300):
            res = render.render(d, {}, dpi=dpi)
            cx, cy = res.stock.circle_center
            r = res.stock.circle_dia / 2
            px = res.image.load()
            outside = [(x, y) for x in range(0, res.stock.w, 3) for y in range(0, res.stock.h, 3)
                       if math.hypot(x - cx, y - cy) > r + 1 and px[x, y] == 0]
            assert not outside, (template, place, dpi)
            assert black(res.image) > 0


def test_wording_wins_over_the_picture():
    rules = cottage.CottageRules()
    ctx = render_cases._ctx(rules, "NE")
    rule = ctx["cottage"]["rule"]
    mins = {"statement:" + s["id"]: s["min_pt"] for s in rule["statements"] if s.get("min_pt")}
    d = model.LabelDoc("cottage", "large", model.default_fields("cottage"))
    d.fields.update(render_cases.SAMPLE["cottage"])
    d.picture = pic_of(colour_logo(), place="left", size=100)
    res = render.render(d, ctx)
    assert not res.overflow
    (x, y, img), = res.layout.images
    region_h = templates.region_for(res.stock).height
    assert img.height < region_h * 0.9                       # the picture gave way
    for ln in res.layout.lines:
        if ln.key in mins:
            assert ln.size * 72 / 203 >= mins[ln.key] - 1e-9
    # far too much writing: the label says so and names the picture
    d.fields["ingredients"] = "flour, " * 250
    res = render.render(d, ctx)
    assert res.overflow


def test_picture_is_named_when_it_is_the_problem():
    d = model.LabelDoc("simple", "small", model.default_fields("simple"))
    d.fields.update(food="Chicken Noodle Soup", note="Keep refrigerated", made_by="Jo",
                    contains="Milk, Eggs, Wheat")
    plain = render.render(d, {})
    assert not plain.overflow
    d.picture = pic_of(colour_logo(), place="above", size=100)
    res = render.render(d, {})
    if res.overflow:
        assert res.problem_field == "picture" and "picture" in res.message
    else:
        (x, y, img), = res.layout.images
        assert img.height >= 1


# ---- files -----------------------------------------------------------------------

def test_label_file_round_trip(tmp_path):
    d = doc_with_picture(place="corner", size=30, mode="photo", brightness=10, invert=True)
    path = model.save(d, tmp_path / "logo")
    back = model.load(path)
    assert back.picture == pictures.clean(d.picture)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    a = render.render(d, render_cases.CTX).image.tobytes()
    b = render.render(back, render_cases.CTX).image.tobytes()
    assert a == b
    snap = back.snapshot()
    assert back.picture["png"] not in snap and len(snap) < 4000
    assert model.LabelDoc.from_snapshot(snap).picture == back.picture


def test_labels_without_picture_are_unchanged():
    d = model.LabelDoc("simple", "large", model.default_fields("simple", render_cases.TODAY))
    out = d.to_dict()
    assert "picture" not in out and "qr" not in out
    old = ('{"app": "easy-labels", "version": 1, "template": "simple", "stock": "large", '
           '"fields": {"food": "Soup"}, "copies": 1}')
    doc = model.LabelDoc.loads(old)
    assert doc.picture is None and doc.qr is None
    assert doc.copy().dumps() == doc.dumps()


def test_damaged_picture_data_is_ignored():
    d = model.LabelDoc("simple", "large", {"food": "Soup"})
    d.picture = {"png": "AAAA", "place": "left"}
    res = render.render(d, {})
    assert not res.overflow and not res.layout.images


def test_my_pictures(tmp_path):
    lib = pictures.Library(tmp_path)
    assert lib.items() == []
    pic = pic_of(colour_logo())
    pid = lib.add(pic, "Kitchen logo")
    assert lib.add(pic) == pid and len(lib.items()) == 1
    im, name = lib.load(pid)
    assert name == "Kitchen logo" and im.size == (600, 300)
    assert pictures.new_picture(im, name)["png"] == pic["png"]
    lib.remove(pid)
    assert lib.items() == []
    with pytest.raises(pictures.PictureError):
        lib.load(pid)


def test_switching_kind_keeps_the_picture():
    d = doc_with_picture(place="left", size=40)
    d.set_template("picture")
    assert d.picture["place"] == "fit" and d.picture["size"] == 100
    assert d.fields["text"] == "Chicken Noodle Soup"
    d.set_template("simple")
    assert d.picture["place"] == "above" and d.picture["size"] == 35


@pytest.mark.parametrize("bad", ["../victim.png", "/tmp/victim.png", "sub/../../victim.png",
                                 "", ".", "..", None, "..\\victim.png"])
def test_my_pictures_never_touch_files_outside_the_folder(tmp_path, bad):
    data = tmp_path / "data"
    lib = pictures.Library(data)
    pid = lib.add(pic_of(colour_logo()), "Logo")
    victim = data / "victim.png"
    victim.write_bytes((lib.dir / f"{pid}.png").read_bytes())
    # someone edits pictures.json to point an entry elsewhere
    index = json.loads(lib.index_path.read_text())
    index["pictures"].append({"id": "evil", "name": "Evil", "file": bad})
    lib.index_path.write_text(json.dumps(index))
    assert [x["id"] for x in lib.items()] == [pid]
    with pytest.raises(pictures.PictureError):
        lib.load("evil")
    lib.remove("evil")
    assert victim.exists()
    assert (lib.dir / f"{pid}.png").exists()          # the real picture is untouched


def test_my_pictures_uses_only_the_bare_file_name(tmp_path):
    lib = pictures.Library(tmp_path)
    pid = lib.add(pic_of(colour_logo()), "Logo")
    index = json.loads(lib.index_path.read_text())
    index["pictures"][0]["file"] = f"some/other/folder/{pid}.png"
    lib.index_path.write_text(json.dumps(index))
    assert lib.load(pid)[1] == "Logo"                 # found inside My pictures
    lib.remove(pid)
    assert not (lib.dir / f"{pid}.png").exists()
