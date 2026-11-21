"""Builds the real main window WITHDRAWN (never shown on screen) and checks
that everything fits a 1280x720 screen at the Small, Normal and Large text sizes.

If nothing needs more room than the window has, pack/grid never squeeze a
button, so no button text can be clipped. Skipped when there is no display.
"""
import os

import pytest

tk = pytest.importorskip("tkinter")

from food_labeler import model, printers, settings  # noqa: E402

SCREEN_W, SCREEN_H = 1280, 720


def make_root():
    # Opt-in only: needs a throwaway display (e.g. Xvfb). Never run on a desktop
    # someone is using.  FOOD_LABELER_UI_TESTS=1 DISPLAY=:99 pytest tests/test_ui_layout.py
    if os.environ.get("FOOD_LABELER_UI_TESTS") != "1":
        pytest.skip("UI tests are opt-in (FOOD_LABELER_UI_TESTS=1 with a spare display)")
    try:
        root = tk.Tk(className="FoodLabelerTest")
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()             # before any widget exists: the window is never mapped
    return root


FAKE = [
    printers.Printer(id="usb:1-1.3", kind="tspl", model="4B-LP610BT", method="device",
                     target="/dev/usb/lp0", port="USB port 1-1.3"),
    printers.Printer(id="usb:1-1.4", kind="tspl", model="4B-LP610BT", method="device",
                     target="/dev/lp610bt-white", port="USB port 1-1.4"),
    printers.Printer(id="usb:1-1.2", kind="zpl", model="ZTC ZP 450-200dpi", method="device",
                     target="/dev/usb/lp2", port="USB port 1-1.2"),
]


@pytest.mark.parametrize("scale", [0.7, 0.8, 1.0])
@pytest.mark.parametrize("template", model.TEMPLATES)
def test_main_window_fits_small_screen(scale, template):
    from food_labeler import app as appmod, known
    root = make_root()
    try:
        cfg = settings.Settings()
        cfg["ui_scale"] = scale
        cfg["selected"] = "usb:1-1.4"
        cfg.printer_info("usb:1-1.4")["nickname"] = "White label printer"
        a = appmod.App(root, cfg)
        k = known.KnownPrinters()
        for p in FAKE:
            printers.classify(p, k)
        a.set_found(list(FAKE))
        doc = model.LabelDoc(template, "xl" if template == "package" else "large",
                             model.default_fields(template))
        a.set_doc(doc, None)
        for i in range(4):                      # long recent-file names
            path = model.save(doc, settings.labels_dir() / f"A very long label name {i}")
            cfg.add_recent(path, f"A very long label name number {i}")
        a.flash("Package labels need a bigger label, so I picked Large — 4 × 2 inches.")
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        assert w <= SCREEN_W, f"window needs {w}px wide at scale {scale}"
        assert h <= SCREEN_H - 40, f"window needs {h}px tall at scale {scale}"
        # the printer dropdown shows the chosen printer
        assert "White label printer" in a.printer_btn.cget("text")
        # the form asks for its full width (so it is never squeezed)
        assert int(a.scroll.canvas.cget("width")) >= a.form.winfo_reqwidth()
    finally:
        root.destroy()


def test_no_printers_placeholder():
    from food_labeler import app as appmod
    root = make_root()
    try:
        a = appmod.App(root, settings.Settings())
        a.set_found([])
        assert "No printer found" in a.printer_btn.cget("text")
    finally:
        root.destroy()
