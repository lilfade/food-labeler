import random

from PIL import Image

from food_labeler import model, render, stocks, zpl


def test_roundtrip_random():
    random.seed(1)
    img = Image.new("1", (13, 7), 1)
    for _ in range(40):
        img.putpixel((random.randrange(13), random.randrange(7)), 0)
    job = zpl.build_job(img, stocks.get("large"), 2)
    back = zpl.decode_gfa(job)
    assert back.crop((0, 0, 13, 7)).tobytes() == img.tobytes()


def test_pad_bits_zero_and_burn_is_one():
    img = Image.new("1", (10, 1), 1)
    img.putpixel((0, 0), 0)
    total, rb, hx = zpl.pack_gfa(img)
    assert (total, rb) == (2, 2)
    assert hx == "8000"                # black -> 1, pad bits masked to 0
    white = Image.new("1", (10, 1), 1)
    assert zpl.pack_gfa(white)[2] == "0000"


def test_job_format():
    doc = model.LabelDoc("simple", "large")
    doc.fields["food"] = "Soup"
    res = render.render(doc)
    job = zpl.build_job(res.image, stocks.get("large"), 5).decode()
    assert job.startswith("^XA\n^CI28\n^PW812\n^LL400\n^LH0,0\n^LT0\n^MD0\n^PR3\n^FO0,0^GFA,")
    assert job.endswith("^FS\n^PQ5,0,0,N\n^XZ\n")
    total = 102 * 400
    assert f"^GFA,{total},{total},102," in job
    hexpart = job.split("^GFA,")[1].split("^FS")[0].split(",", 3)[3]
    assert hexpart == hexpart.upper()
    back = zpl.decode_gfa(job.encode()).crop((0, 0, 812, 400))
    assert back.tobytes() == res.image.tobytes()


def test_round_settings():
    job = zpl.build_job(Image.new("1", (406, 405), 1), stocks.get("round")).decode()
    assert "^LT-3\n^MD8\n^PR2\n" in job
