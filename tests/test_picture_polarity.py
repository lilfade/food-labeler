"""Black stays black: pictures in every mode and file type print the right way
round, a label saved with "Save as picture" prints back the same, and pictures
are stored small in .label files without changing what prints."""
import base64
import functools
import io

import pytest
from PIL import Image, ImageDraw, ImageFilter

from food_labeler import model, pictures, render


def black_frac(img) -> float:
    return img.convert("L").histogram()[0] / (img.width * img.height)


def sample_label():
    doc = model.LabelDoc()
    doc.fields.update(food="Chicken soup", contains="Wheat", note="Keep refrigerated")
    return render.render(doc)


def exported(tmp_path, res=None):
    res = res or sample_label()
    path = tmp_path / "label.png"
    render.export_png(res, path)
    return res, path


def picture_label(pic, stock="large", dpi=203, **kw):
    doc = model.LabelDoc("picture", stock, model.default_fields("picture"))
    doc.picture = dict(pic, place="fit", size=100, **kw)
    return render.render(doc, dpi=dpi)


def agreement(res_pic, original) -> float:
    """How much of the printed picture matches the original label, scaled into
    the picture's box (1.0 = the same; an inverted picture gives about 0.1)."""
    (x, y, img), = res_pic.layout.images
    ref = original.convert("L").resize(img.size, Image.LANCZOS).point(
        lambda v: 255 if v >= 128 else 0)
    a, b = img.convert("L").tobytes(), ref.tobytes()
    return sum(1 for p, q in zip(a, b) if p == q) / len(a)


def check_right_way_round(pic, original):
    out = picture_label(pic)
    assert out.image.getpixel((2, 2)) != 0                  # the paper stays white
    (x, y, img), = out.layout.images
    assert img.getpixel((1, 1)) != 0                          # the picture's corner too
    assert black_frac(img) < 0.35                             # mostly paper, like the label
    assert agreement(out, original) > 0.9
    return out


# ---- the tester's steps: Save as picture, then a Picture label from that file -----------

def test_saved_label_picture_prints_the_right_way_round(tmp_path):
    res, path = exported(tmp_path)
    saved = Image.open(path)
    assert saved.mode == "L" and saved.info["dpi"][0] == pytest.approx(406, abs=1)
    im, name = pictures.read_file(path)
    pic = pictures.new_picture(im, name)
    out = check_right_way_round(pic, res.image)
    # the same polarity as the label it came from, in the printer's own job too
    assert abs(black_frac(out.layout.images[0][2]) - black_frac(res.image)) < 0.05
    from food_labeler import printers
    job = printers.build_job(out.image, out.stock, {"kind": "tspl", "method": "network",
                                                    "target": "printer:9101"}, {}, 1)
    head = b"BITMAP 0,0,102,400,0,"
    data = job[job.index(head) + len(head):][:102 * 400]
    back = Image.frombytes("1", (816, 400), data).crop((0, 0, 812, 400))
    assert back.tobytes() == out.image.tobytes()               # 1 = white, as drawn


@pytest.mark.parametrize("dpi", [203, 300])
@pytest.mark.parametrize("stock", ["small", "large", "xl", "round"])
def test_saved_label_round_trip_every_size(tmp_path, stock, dpi):
    doc = model.LabelDoc("simple", stock)
    doc.fields["food"] = "Lemon bars"
    res = render.render(doc, dpi=dpi)
    _, path = exported(tmp_path, res)
    pic = pictures.new_picture(*pictures.read_file(path))
    for place in ("fit", "fill"):
        out = picture_label(dict(pic, place=place), stock=stock, dpi=dpi)
        assert out.image.getpixel((out.stock.w // 2, 3)) != 0
        assert black_frac(out.image) < 0.35


def _modes(label: Image.Image):
    """The saved label (2 x 2 dots, as Save as picture writes it) in every mode a
    picture program might save it in."""
    L = label.convert("L").resize((label.width * 2, label.height * 2), Image.NEAREST)
    p = L.convert("P")
    yield "1-bit", L.convert("1"), {}
    yield "greyscale", L, {}
    yield "greyscale, white see-through", L, {"transparency": 255}
    yield "palette", p, {}
    yield "palette, white see-through", p, {"transparency": p.getpixel((0, 0))}
    yield "colour", L.convert("RGB"), {}
    yield "colour + alpha", L.convert("RGBA"), {}
    yield "greyscale + alpha", L.convert("LA"), {}
    yield "16-bit", L.convert("I").point(lambda v: v * 257).convert("I;16"), {}
    big = L.copy()
    big.info["dpi"] = (812, 812)
    yield "2 x 2 with dpi", big, {"dpi": (406, 406)}


@pytest.mark.parametrize("case", [c[0] for c in _modes(Image.new("1", (8, 8), 1))])
def test_every_png_mode_prints_the_right_way_round(case):
    res = sample_label()
    name, im, kw = next(c for c in _modes(res.image) if c[0] == case)
    buf = io.BytesIO()
    im.save(buf, "PNG", **kw)
    got = pictures.open_bytes(buf.getvalue())
    check_right_way_round(pictures.new_picture(got, "label.png"), res.image)


@pytest.mark.parametrize("fmt,mode", [("JPEG", "RGB"), ("JPEG", "L"), ("GIF", "P"),
                                      ("BMP", "L"), ("BMP", "RGB"), ("WEBP", "RGB"),
                                      ("WEBP", "RGBA"), ("TIFF", "L"), ("TIFF", "1"),
                                      ("ICO", "RGBA")])
def test_every_file_type_prints_the_right_way_round(tmp_path, fmt, mode):
    res = sample_label()
    im = res.image.convert(mode)
    if fmt == "ICO":
        im = im.resize((256, 126))
    path = tmp_path / f"label.{fmt.lower()}"
    im.save(path, fmt)
    got, _name = pictures.read_file(path)
    out = picture_label(pictures.new_picture(got, path.name))
    assert out.image.getpixel((2, 2)) != 0
    (x, y, img), = out.layout.images
    assert img.getpixel((1, 1)) != 0
    assert black_frac(img) < 0.35
    if fmt != "ICO":
        assert agreement(out, res.image) > 0.9


def test_tiff_white_is_zero_prints_the_right_way_round(tmp_path):
    """1-bit TIFF scans often say "0 = white"; Pillow reads them the right way."""
    res = sample_label()
    path = tmp_path / "scan.tif"
    res.image.save(path, "TIFF", compression="group4")
    check_right_way_round(pictures.new_picture(*pictures.read_file(path)), res.image)


# ---- logos on a see-through background ------------------------------------------

def logo(fill, ring=None, w=400, h=200):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((20, 20, 180, 180), fill=fill)
    d.rectangle((220, 80, 380, 120), fill=fill)
    if ring:
        d.ellipse((70, 70, 130, 130), fill=ring)
    return im


def printed(im, **kw):
    pic = pictures.new_picture(pictures.normalise(im), "logo.png", **kw)
    return pictures.to_print(pic, 400, 200)


def test_dark_logo_on_see_through_background():
    out = printed(logo((30, 30, 120, 255)))
    assert out.getpixel((100, 100)) == 0 and out.getpixel((300, 100)) == 0
    assert out.getpixel((5, 5)) != 0 and out.getpixel((300, 170)) != 0


def test_light_logo_on_see_through_background_still_prints():
    """A white (or very light) logo would vanish on white paper: its shape prints."""
    for colour in ((255, 255, 255, 255), (250, 246, 230, 255)):
        out = printed(logo(colour))
        assert out.getpixel((100, 100)) == 0 and out.getpixel((300, 100)) == 0
        assert out.getpixel((5, 5)) != 0                       # see-through = paper
    pic = pictures.new_picture(pictures.normalise(logo((255, 255, 255, 255))), "l.png")
    assert pictures.auto_threshold(pic) == 254                # the slider shows "darkest"


def test_light_lettering_inside_a_dark_shape_stays_light():
    out = printed(logo((20, 20, 20, 255), ring=(255, 255, 255, 255)))
    assert out.getpixel((40, 100)) == 0                       # the dark disc
    assert out.getpixel((100, 100)) != 0                      # the white ring inside it
    assert out.getpixel((5, 5)) != 0


def test_light_logo_with_swap_and_remove_background():
    out = printed(logo((255, 255, 255, 255)), invert=True)
    assert out.getpixel((100, 100)) == 0 and out.getpixel((5, 5)) != 0
    gone = printed(logo((255, 255, 255, 255)), remove_bg=True)
    assert gone.getpixel((100, 100)) != 0                     # asked for: light = paper


# ---- the settings never swap black and white by themselves ------------------------

def test_defaults_never_swap():
    assert pictures.DEFAULTS["invert"] is False and pictures.DEFAULTS["remove_bg"] is False
    res = sample_label()
    pic = pictures.new_picture(pictures.normalise(res.image), "x.png")
    assert pic["invert"] is False and pic["threshold"] is None


@pytest.mark.parametrize("settings", [{}, {"remove_bg": True}, {"mode": "photo"},
                                      {"mode": "photo", "remove_bg": True},
                                      {"threshold": 1}, {"threshold": 254},
                                      {"threshold": 128}])
def test_white_paper_stays_white(settings):
    """Whatever the settings (short of "Swap black and white"), white is paper."""
    res = sample_label()
    pic = pictures.new_picture(pictures.normalise(res.image), "x.png")
    out = picture_label(dict(pic, **settings))
    (x, y, img), = out.layout.images
    corners = [(1, 1), (img.width - 2, 1), (1, img.height - 2),
               (img.width - 2, img.height - 2)]
    assert all(img.getpixel(c) != 0 for c in corners)
    assert black_frac(img) < 0.35


def test_swap_is_the_only_way_to_print_a_negative():
    res = sample_label()
    pic = pictures.new_picture(pictures.normalise(res.image), "x.png")
    out = picture_label(dict(pic, invert=True))
    (x, y, img), = out.layout.images
    assert black_frac(img) > 0.65


# ---- what the file picker offers, and what it can't open ---------------------------

def test_file_picker_offers_every_readable_kind():
    patterns = " ".join(p for _name, p in pictures.OPEN_TYPES)
    for ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "tif", "tiff", "ico"):
        assert f"*.{ext}" in patterns
    names = [n for n, _p in pictures.OPEN_TYPES]
    assert names[0] == "All pictures" and names[-1] == "All files"
    assert all(n.isascii() and n[0].isupper() for n in names)


@pytest.mark.parametrize("name,data", [
    ("IMG_0001.HEIC", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"),
    ("photo.heif", b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic"),
    ("logo.svg", b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'),
    ("renamed.png", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"),
    ("drawing.png", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
])
def test_heic_and_svg_get_a_friendly_message(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(pictures.PictureError, match="Please save it as PNG or JPG first"):
        pictures.read_file(path)


# ---- small .label files -------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def photo_12mp() -> Image.Image:
    """A stand-in for a 12 megapixel phone photo: smooth light and shade, shapes and a
    little grain (no photos are kept in the repository)."""
    w, h = 4000, 3000
    small = Image.radial_gradient("L").resize((w // 8, h // 8))
    rgb = Image.merge("RGB", (small, small.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                              Image.linear_gradient("L").resize(small.size)))
    d = ImageDraw.Draw(rgb)
    for i in range(40):
        d.ellipse((i * 12, (i * 37) % 300, i * 12 + 60, (i * 37) % 300 + 60),
                  fill=(i * 6, 255 - i * 6, (i * 40) % 255))
    rgb = rgb.filter(ImageFilter.GaussianBlur(2)).resize((w, h), Image.BICUBIC)
    grain = Image.effect_noise((w, h), 6).convert("RGB")
    return Image.blend(rgb, grain, 0.08)


def embedded_bytes(pic) -> int:
    return len(model.LabelDoc("picture", "large", {"text": ""}, picture=pic).dumps())


def old_style(im: Image.Image) -> dict:
    """The picture as Food Labeler 1.2–1.4 stored it: colour, up to 2000 pixels."""
    im = pictures.normalise(im)
    if max(im.size) > 2000:
        k = 2000 / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return dict(pictures.DEFAULTS, png=base64.b64encode(buf.getvalue()).decode("ascii"),
                name="old.png")


def test_saved_label_picture_is_small_and_prints_the_same(tmp_path):
    res, path = exported(tmp_path)
    im, name = pictures.read_file(path)
    pic = pictures.new_picture(im, name)
    stored = Image.open(io.BytesIO(base64.b64decode(pic["png"])))
    assert stored.mode == "1" and stored.size == (1624, 800)
    assert embedded_bytes(pic) < 300_000
    before = picture_label(old_style(Image.open(path))).image
    after = picture_label(pic).image
    assert before.tobytes() == after.tobytes()                # exactly the same dots


def test_big_saved_label_picture_keeps_every_dot(tmp_path):
    doc = model.LabelDoc("simple", "xl")
    doc.fields["food"] = "Granola"
    res, path = exported(tmp_path, render.render(doc, dpi=300))   # 2400 x 3600
    pic = pictures.new_picture(*pictures.read_file(path))
    stored = Image.open(io.BytesIO(base64.b64decode(pic["png"])))
    assert stored.mode == "1" and stored.size == (2400, 3600)
    assert embedded_bytes(pic) < 300_000


def test_photo_is_small_and_prints_about_the_same():
    im = photo_12mp()
    pic = pictures.new_picture(pictures.normalise(im), "photo.jpg")
    old = old_style(im)
    print("photo: before", embedded_bytes(old), "after", embedded_bytes(pic))
    assert embedded_bytes(pic) < 1_500_000
    assert embedded_bytes(pic) < embedded_bytes(old) / 2
    stored = Image.open(io.BytesIO(base64.b64decode(pic["png"])))
    assert stored.mode == "L" and max(stored.size) == pictures.MAX_STORED_SIDE
    for settings in ({}, {"threshold": 128}):
        a = picture_label(dict(old, **settings), stock="xl").image
        b = picture_label(dict(pic, **settings), stock="xl").image
        same = sum(1 for p, q in zip(a.tobytes(), b.tobytes()) if p == q) / len(a.tobytes())
        assert same > 0.98


def test_see_through_logo_is_stored_grey_with_alpha():
    im = logo((200, 30, 30, 255)).resize((2400, 1200), Image.LANCZOS)
    pic = pictures.new_picture(pictures.normalise(im), "logo.png")
    stored = Image.open(io.BytesIO(base64.b64decode(pic["png"])))
    assert stored.mode == "LA" and max(stored.size) == pictures.MAX_STORED_SIDE
    out = pictures.to_print(pic, 400, 200)
    assert out.getpixel((100, 100)) == 0 and out.getpixel((5, 5)) != 0


def test_old_files_with_big_colour_pictures_open_and_save_smaller(tmp_path):
    im = photo_12mp()
    old = old_style(im)
    doc = model.LabelDoc("simple", "large")
    doc.fields["food"] = "Bread"
    data = doc.to_dict()
    data["picture"] = dict(old, place="left", size=60)
    path = tmp_path / "old.label"
    import json
    path.write_text(json.dumps(data), encoding="utf-8")
    opened = model.load(path)
    assert opened.picture["place"] == "left" and opened.picture["size"] == 60
    saved = model.save(opened, tmp_path / "again.label")
    assert saved.stat().st_size < path.stat().st_size / 2
    assert render.render(opened).overflow is False
    # opening it twice gives the very same picture (and the label isn't "changed")
    assert model.load(path).dumps() == opened.dumps()


def test_label_file_holds_one_copy_of_the_picture(tmp_path):
    res, path = exported(tmp_path)
    doc = model.LabelDoc("picture", "large", {"text": "Thanks"})
    doc.picture = pictures.new_picture(*pictures.read_file(path))
    text = doc.dumps()
    assert text.count(doc.picture["png"][:200]) == 1
    assert len(text) - len(doc.picture["png"]) < 2000          # nothing else big in it
