"""Developer smoke test: build the real window with sample content and take
screenshots. The window fills the screen for about half a minute, so run it on
a desktop you are not using at that moment:
    python tools/screenshot.py docs
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


def grab(name, widget=None):
    """Save the window (or dialog) as docs/<name>, by asking X for that window's
    own pixels; Xwayland refuses whole-screen grabs."""
    w = widget or root
    w.update()
    subprocess.run([sys.executable, str(ROOT / "tools" / "xwingrab.py"), hex(w.winfo_id()),
                    str(OUT / name)], check=True, timeout=20)


settings.setup_logging()
cfg = settings.Settings()
# a remembered printer so the dropdown has something friendly to show
cfg["selected"] = "usb:1-1.4"
cfg.printer_info("usb:1-1.4")["nickname"] = "White label printer"
cfg["bakery_offered"] = True  # no "Set up my bakery" pop-up during the run
root = tk.Tk(className="FoodLabeler")
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
app = appmod.App(root, cfg)
root.geometry("1366x800")
doc = model.LabelDoc("simple", "large", model.default_fields("simple"))
doc.fields.update(food="Chicken Noodle Soup", contains="Wheat, Eggs", note="Keep refrigerated",
                  made_by="Grandma Jo")
app.set_doc(doc, None, mark_saved=False)
app.copies_var.set("2")

# A filled-in example bakery for the cottage food screens.
from food_labeler import bakery  # noqa: E402
app.profile.data.update(state="NE", business="High Thyme Kitchen",
                        legal_entity="Example Bakes LLC", street="123 Garden Lane",
                        city="Springfield", region="NE", zip="68000",
                        phone="(555) 010-0199", permit="CF-0000", setup_done=True)
app.profile.save()
app.products.put(bakery.product_from_fields(
    {"product": "Lemon Thyme Shortbread", "net": "8 oz",
     "ingredients": "Butter (cream, salt), all-purpose flour (wheat flour, niacin, "
                    "reduced iron, thiamine mononitrate, riboflavin, folic acid), sugar, "
                    "lemon zest, fresh thyme, sea salt",
     "contains": "Milk, Wheat", "storage": "Store in a cool, dry place"}))
app.products.put(bakery.product_from_fields(
    {"product": "Sourdough Country Loaf", "net": "1 lb 8 oz",
     "ingredients": "Bread flour (wheat flour, malted barley flour), water, salt",
     "contains": "Wheat", "storage": "Best eaten within 3 days"}))
app.products.save()

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


@step
def cottage_label():
    app.doc.set_template("cottage")
    app.doc.fields.update(
        product="Lemon Thyme Shortbread", net="8 oz",
        ingredients="Butter (cream, salt), all-purpose flour (wheat flour, niacin, reduced "
                    "iron, thiamine mononitrate, riboflavin, folic acid), sugar, lemon zest, "
                    "fresh thyme, sea salt",
        contains="Milk, Wheat", storage="Store in a cool, dry place",
        made_on="2026-11-20", best_by="2026-12-04")
    app._sync_ui_from_doc()
    root.after(800, lambda: (grab("screenshot-cottage.png"), nxt()))
    return True


@step
def cottage_missing():
    app.doc.fields["ingredients"] = ""
    app._sync_ui_from_doc()
    root.after(600, lambda: (grab("screenshot-cottage-check.png"),
                             nxt()))
    return True


@step
def bakery_wizard():
    from food_labeler.bakery_dialogs import BakeryWizard
    d = BakeryWizard(root, app)
    d.deiconify()
    root.after(700, lambda: (grab("screenshot-bakery-setup.png", d), d.destroy(), nxt()))
    return True


@step
def my_bakery():
    from food_labeler.bakery_dialogs import MyBakeryDialog
    d = MyBakeryDialog(root, app)
    d.deiconify()
    root.after(700, lambda: (grab("screenshot-my-bakery.png", d), d.destroy(), nxt()))
    return True


@step
def ingredients():
    from food_labeler.bakery_dialogs import IngredientPicker
    d = IngredientPicker(root, app)
    d.deiconify()
    root.after(700, lambda: (grab("screenshot-ingredients.png", d), d.destroy(), nxt()))
    return True


@step
def products():
    from food_labeler.bakery_dialogs import ProductPicker
    d = ProductPicker(root, app)
    d.deiconify()
    root.after(700, lambda: (grab("screenshot-products.png", d), d.destroy(), nxt()))
    return True


def nxt():
    if not steps:
        root.after(100, root.destroy)
        return
    fn = steps.pop(0)
    try:
        waits = fn()
    except Exception as e:  # keep going, so one broken step can't hang the run
        print("step failed:", fn.__name__, e)
        waits = False
    if not waits:
        root.after(300, nxt)


root.after(1500, nxt)
root.after(90000, root.destroy)  # never leave a window behind
root.mainloop()
print("smoke test OK")
