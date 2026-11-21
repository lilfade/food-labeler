"""Command-line entry point: ``python -m food_labeler [--selftest | --version | FILE]``.

``--selftest`` renders every template on every label size it allows (and one
label at 300 dpi, one with a picture and a QR code), builds
TSPL and ZPL jobs from the pictures and checks they decode back to the same
bits — without opening a window or touching any printer. It exits 0 if all
is well; the build scripts and the release workflow run it on the finished
one-file program to prove it starts and has all its parts bundled.
"""
from __future__ import annotations

import sys


def _say(msg: str) -> None:
    """Print if there is a console. A windowed .exe has sys.stdout = None."""
    try:
        if sys.stdout is not None:
            print(msg, flush=True)
    except OSError:
        pass


def selftest() -> int:
    """Render and encode every template x stock; raise AssertionError on any problem."""
    from . import APP_NAME, __version__, known, model, render, stocks, templates, tspl, zpl
    count = 0
    for t in model.TEMPLATES:
        for sid in templates.ALLOWED_STOCKS[t]:
            doc = model.LabelDoc(t, sid, model.default_fields(t))
            key = {"simple": "food", "package": "product", "sticker": "lot", "free": "text",
                   "cottage": "product", "picture": "text"}[t]
            doc.fields[key] = "Selftest Soup"
            res = render.render(doc, {})
            st = stocks.get(sid)
            assert res.image.size == (st.w, st.h) and res.image.mode == "1"
            assert not res.overflow, (t, sid)
            job = tspl.build_job(res.image, st, 1)
            assert job.startswith(b"SIZE ") and job.endswith(b"PRINT 1,1\r\n")
            zjob = zpl.build_job(res.image, st, 1)
            back = zpl.decode_gfa(zjob).crop((0, 0, st.w, st.h))
            assert back.tobytes() == res.image.tobytes()
            count += 1
    # a 300 dpi printer: same label, more dots, same physical size
    doc = model.LabelDoc("cottage", "large", model.default_fields("cottage"))
    doc.fields["product"] = "Selftest Soup"
    res = render.render(doc, {}, dpi=300)
    st = stocks.get("large", 300)
    assert res.image.size == (st.w, st.h) == (1200, 600) and not res.overflow
    job = tspl.build_job(res.image, st, 1)
    assert job.startswith(b"SIZE 101.6 mm,50.8 mm") and b"BITMAP 0,0,150,600," in job
    zjob = zpl.build_job(res.image, st, 1)
    assert b"^PW1200\n^LL600\n" in zjob
    assert zpl.decode_gfa(zjob).crop((0, 0, st.w, st.h)).tobytes() == res.image.tobytes()
    count += 1
    # a picture and a QR code (300 dpi): picture converted, code drawn in whole dots
    from PIL import Image, ImageDraw
    from . import pictures, qrcodes
    im = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((10, 10, 90, 90), fill=(200, 40, 40, 255))
    doc = model.LabelDoc("simple", "large", model.default_fields("simple"))
    doc.fields["food"] = "Selftest Soup"
    doc.picture = pictures.new_picture(pictures.normalise(im), "selftest", place="left")
    doc.qr = dict(qrcodes.DEFAULTS, value="example.com")
    doc = model.LabelDoc.loads(doc.dumps())
    res = render.render(doc, {}, dpi=300)
    assert not res.overflow and res.layout.images and res.layout.qr, res.message
    assert res.layout.qr[2] >= qrcodes.min_module(300)
    assert res.image.convert("L").histogram()[0] > 0
    count += 1
    # every bundled font is there, draws, and has a real bold where it should
    from . import lettering
    for face in lettering.BUNDLED:
        assert lettering.font(face.name, 40).getlength("Soup") > 0, face.name
        if face.has_bold:
            assert lettering.ink(face.name, 40, True) > lettering.ink(face.name, 40), face.name
        doc = model.LabelDoc("simple", "large", model.default_fields("simple"),
                             lettering={"name": face.name})
        doc.fields["food"] = "Selftest Soup"
        assert not render.render(doc, {}).overflow, face.name
    # the bundled state rules load and every preset is usable
    from . import bakery, cottage
    rules = cottage.CottageRules()
    assert len(rules.states()) >= 52, "state rules missing"
    assert rules.effective("NE").statements, "Nebraska preset missing"
    assert bakery.load_starter(), "starter ingredients missing"
    k = known.KnownPrinters()
    assert k.match({}, "0483:2025") is not None
    # Make sure the GUI toolkit is bundled. Importing tkinter never opens a
    # window; only creating tk.Tk() would.
    import tkinter
    assert tkinter.TkVersion >= 8.5
    _say(f"{APP_NAME} {__version__} selftest OK ({count} labels rendered)")
    return 0


def main(argv=None) -> int:
    """Run the self test, print the version, or start the app (optionally opening a file)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        try:
            return selftest()
        except Exception as e:  # noqa: BLE001
            _say(f"selftest FAILED: {e!r}")
            return 1
    if "--version" in argv:
        from . import __version__
        _say(__version__)
        return 0
    from . import app
    app.main(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
