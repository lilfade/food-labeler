"""Developer smoke test: build the real window with sample content and take
screenshots. Run under a throwaway X server, e.g.
    Xwayland :77 -geometry 1366x768 &   DISPLAY=:77 python tools/screenshot.py out_dir
Uses a temporary data folder and FOOD_LABELER_DRY_RUN, so nothing is printed.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp(prefix="fl-shot-")
os.environ["FOOD_LABELER_DATA"] = os.path.join(tmp, "data")
os.environ["FOOD_LABELER_LABELS"] = os.path.join(tmp, "labels")
os.environ["FOOD_LABELER_DRY_RUN"] = os.path.join(tmp, "jobs")

import tkinter as tk  # noqa: E402

from food_labeler import app as appmod, model, settings  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs")
OUT.mkdir(parents=True, exist_ok=True)
DISPLAY = os.environ.get("DISPLAY", ":0")


def grab(name, widget=None):
    root.update()
    code = ("from PIL import ImageGrab;import sys;"
            f"im=ImageGrab.grab(xdisplay={DISPLAY!r});"
            "b=tuple(int(x) for x in sys.argv[2:6]);"
            "im=im.crop(b) if b[2]>b[0] else im;im.save(sys.argv[1])")
    w = widget or root
    x, y = w.winfo_rootx(), w.winfo_rooty()
    box = [x, y, x + w.winfo_width(), y + w.winfo_height()]
    subprocess.run([sys.executable, "-c", code, str(OUT / name)] + [str(v) for v in box],
                   check=True)
    print("saved", OUT / name)


settings.setup_logging()
cfg = settings.Settings()
# a remembered printer so the dropdown has something friendly to show
cfg["selected"] = "usb:1-1.4"
cfg.printer_info("usb:1-1.4")["nickname"] = "White label printer"
root = tk.Tk(className="FoodLabeler")
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
app = appmod.App(root, cfg)
root.geometry(f"{sw}x{sh}+0+0")
doc = model.LabelDoc("simple", "large", model.default_fields("simple"))
doc.fields.update(food="Chicken Noodle Soup", contains="Wheat, Eggs", note="Keep refrigerated",
                  made_by="Grandma Jo")
app.set_doc(doc, None, mark_saved=False)
app.copies_var.set("2")

steps = []


def step(fn):
    steps.append(fn)
    return fn


@step
def main_window():
    grab("screenshot.png")


@step
def too_much():
    app.field_setters["note"]("Keep refrigerated and eat within three days. " * 12)
    root.after(400, lambda: (grab("screenshot-too-much.png"),
                             app.field_setters["note"]("Keep refrigerated"), nxt()))
    return True


@step
def template_picker():
    from food_labeler.dialogs import TemplatePicker
    d = TemplatePicker(root, app.doc, cfg.render_ctx())
    d.deiconify()
    root.after(600, lambda: (grab("screenshot-templates.png", d), d.destroy(), nxt()))
    return True


@step
def package():
    app.doc.set_template("package")
    app.doc.fields.update(product="Lemon Thyme Shortbread", net="8 oz (227 g)",
                          ingredients="Butter, wheat flour, sugar, lemon zest, thyme",
                          contains="Milk, Wheat", business="High Thyme Kitchen",
                          address="123 Garden Lane\nSpringfield, IL")
    app._sync_ui_from_doc()
    root.after(600, lambda: (grab("screenshot-package.png"), nxt()))
    return True


@step
def usb():
    from food_labeler.dialogs import UsbDevicesDialog
    d = UsbDevicesDialog(root, app)
    d.deiconify()
    root.after(1500, lambda: (grab("screenshot-usb.png", d), d.destroy(), nxt()))
    return True


@step
def wizard():
    from food_labeler.dialogs import SetupWizard
    d = SetupWizard(root, app)
    d.deiconify()
    root.after(500, lambda: (grab("screenshot-wizard.png", d), d.destroy(), nxt()))
    return True


def nxt():
    if not steps:
        root.after(100, root.destroy)
        return
    fn = steps.pop(0)
    if not fn():
        root.after(300, nxt)


root.after(1500, nxt)
root.mainloop()
print("smoke test OK")
