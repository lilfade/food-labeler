"""Developer smoke test: build the real window with sample content and take
screenshots. Windows appear on the screen for a while and close themselves,
so run it on a desktop you are not using at that moment:

    python tools/screenshot.py <folder>

Uses a temporary data folder and FOOD_LABELER_DRY_RUN, so nothing is printed
and nothing of yours is touched. Printer discovery is replaced by two pretend
printers and "Test the connection" never connects.

Settings, from the environment:

    SHOT_SCALE=0.8        text size (0.7 Small, 0.8 Normal, 1.0 Large, 1.2 Extra large)
    SHOT_SIZE=1280x720    main window size (default 1366x800, the docs' size)
    SHOT_SCREEN=1280x720  pretend the screen is this big (dialogs size themselves to it)
    SHOT_ALL=1            also walk through every other window and flow
    SHOT_STEPS=a,b        only these steps (names as below)

Each window grabbed also gets a FIT line: the room it asks for, the room it
has, and any button or text that is squeezed or cut off. Dry-run PRINT jobs
are counted at the end (JOBS lines).
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
JOBS = Path(os.environ["FOOD_LABELER_DRY_RUN"])

import tkinter as tk  # noqa: E402

from food_labeler import app as appmod, known, model, printers, settings  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs")
OUT.mkdir(parents=True, exist_ok=True)
SCALE = float(os.environ.get("SHOT_SCALE") or 0)
SIZE = os.environ.get("SHOT_SIZE") or "1366x800"
SCREEN = os.environ.get("SHOT_SCREEN") or ""
ALL = os.environ.get("SHOT_ALL") == "1"
ONLY = [s for s in (os.environ.get("SHOT_STEPS") or "").split(",") if s]
MAX_W, MAX_H = 1280, 720 - 40           # a laptop screen, less a task bar
DIALOG_H = 720 - 80                     # less a task bar and the window's title bar
PROBLEMS = []

# -- never touch real printers or the network --------------------------------
FAKE_USB = dict(kind="tspl", model="4B-LP610BT", method="device", target="/dev/usb/lp0",
                port="USB port 1-1.4", vidpid="0483:2025")


def fake_printers():
    k = known.KnownPrinters()
    a = printers.Printer(id="usb:1-1.4", **FAKE_USB)
    printers.classify(a, k, {"MFG": "Polono", "CMD": "TSPL2", "MDL": "4B-LP610BT"})
    z = printers.Printer(id="usb:1-1.2", kind="zpl", model="ZTC ZP 450-200dpi",
                         method="device", target="/dev/usb/lp2", port="USB port 1-1.2")
    printers.classify(z, k)
    return [a, z]


printers.discover = lambda *a, **k: fake_printers()


def _no_network(*a, **k):
    raise printers.PrinterError("(screenshot run: not connecting)")


printers.check_network = _no_network
try:
    from food_labeler import btscan
    btscan.scan = lambda *a, **k: []
    btscan.scan_cached = lambda *a, **k: []
except ImportError:
    pass

if SCREEN:
    sw_, sh_ = (int(x) for x in SCREEN.split("x"))
    tk.Misc.winfo_screenwidth = lambda self: sw_
    tk.Misc.winfo_screenheight = lambda self: sh_

# -- questions answer themselves (first button), and are logged ---------------
ASKED = []


def auto_ask(parent, title, message, buttons, icon=""):
    value = buttons[0][1] if buttons else None
    ASKED.append((title, message, value))
    print(f"ASK {title!r}: {message[:90]!r} -> {value!r}")
    return value


def auto_tell(parent, title, message, icon=""):
    auto_ask(parent, title, message, [("OK", True, "primary")])


from food_labeler import (bakery_dialogs, dialogs, font_dialogs,  # noqa: E402
                          picture_dialogs, widgets)
for mod in (appmod, dialogs, bakery_dialogs, picture_dialogs, font_dialogs, widgets):
    if hasattr(mod, "ask"):
        mod.ask = auto_ask
    if hasattr(mod, "tell"):
        mod.tell = auto_tell
bakery_dialogs.ask_text = lambda parent, title, question, value="": (
    print(f"ASK_TEXT {title!r} -> {value or 'Country Loaf'!r}") or value or "Country Loaf")


# -- grabbing and fit checks ---------------------------------------------------
def clipped(top):
    """Buttons and words in ``top`` that are squeezed or stick out of the window
    (things inside a scrolling area are allowed to be out of view)."""
    out = []
    try:
        tx, tw = top.winfo_rootx(), top.winfo_width()
    except tk.TclError:
        return out
    todo = list(top.winfo_children())
    while todo:
        w = todo.pop()
        if isinstance(w, (tk.Canvas, tk.Toplevel, tk.Menu)):
            continue
        todo.extend(w.winfo_children())
        if not isinstance(w, (tk.Button, tk.Label, tk.Menubutton, tk.Checkbutton,
                              tk.Radiobutton)) or not w.winfo_ismapped():
            continue
        try:
            text = str(w.cget("text"))[:30]
        except tk.TclError:
            text = ""
        if not text.strip():
            continue
        if w.winfo_width() < w.winfo_reqwidth() - 2 or w.winfo_height() < w.winfo_reqheight() - 2:
            out.append(f"squeezed {text!r} {w.winfo_width()}<{w.winfo_reqwidth()}")
        elif w.winfo_rootx() + w.winfo_width() > tx + tw + 1:
            out.append(f"cut off {text!r}")
    return out


def grab(name, widget=None):
    """Save the window (or dialog) as <folder>/<name>, by asking X for that window's
    own pixels (Xwayland refuses whole-screen grabs), and print its FIT line."""
    w = widget or root
    w.update()
    rw, rh = w.winfo_reqwidth(), w.winfo_reqheight()
    if w is root:
        lw, lh = MAX_W, MAX_H
    else:
        lw, lh = MAX_W, DIALOG_H
    bad = clipped(w)
    ok = rw <= lw and rh <= lh and not bad
    sc = getattr(w, "scroller", None)
    scrolls = (f" (scrolls: content {sc.inner.winfo_reqheight()} tall)"
               if sc is not None and sc.vsb.winfo_manager() else "")
    line = (f"FIT {name}: needs {rw}x{rh}, has {w.winfo_width()}x{w.winfo_height()}"
            f"{scrolls} {'ok' if ok else 'PROBLEM'}" + (f" {bad[:4]}" if bad else ""))
    print(line)
    if not ok:
        PROBLEMS.append(line)
    subprocess.run([sys.executable, str(ROOT / "tools" / "xwingrab.py"), hex(w.winfo_id()),
                    str(OUT / name)], check=True, timeout=20, stdout=subprocess.DEVNULL)


def show(dialog, name, ms=700, after=None):
    """Show a dialog (not modal), grab it after ``ms``, close it, go on."""
    dialog.deiconify()

    def done():
        grab(name, dialog)
        if after:
            after(dialog)
        dialog.destroy()
        nxt()
    root.after(ms, done)
    return True


# -- the window ----------------------------------------------------------------
settings.setup_logging()
cfg = settings.Settings()
if SCALE:
    cfg["ui_scale"] = SCALE
# a remembered printer so the dropdown has something friendly to show
cfg["selected"] = "usb:1-1.4"
cfg.printer_info("usb:1-1.4")["nickname"] = "White label printer"
cfg["bakery_offered"] = True  # no "Set up my bakery" pop-up during the run
root = tk.Tk(className="FoodLabeler")
app = appmod.App(root, cfg)
root.geometry(SIZE)
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
for fields, used, fav in [
    ({"product": "Lemon Thyme Shortbread", "net": "8 oz",
      "ingredients": "Butter (cream, salt), all-purpose flour (wheat flour, niacin, "
                     "reduced iron, thiamine mononitrate, riboflavin, folic acid), sugar, "
                     "lemon zest, fresh thyme, sea salt",
      "contains": "Milk, Wheat", "storage": "Store in a cool, dry place"},
     "2026-11-20T08:00:00", True),
    ({"product": "Sourdough Country Loaf", "net": "1 lb 8 oz",
      "ingredients": "Bread flour (wheat flour, malted barley flour), water, salt",
      "contains": "Wheat", "storage": "Best eaten within 3 days"}, "2026-11-21T07:00:00", False),
    ({"product": "Cinnamon Rolls (4)", "net": "14 oz", "ingredients": "Flour, butter, sugar, "
      "cinnamon, eggs, milk", "contains": "Wheat, Milk, Eggs"}, "2026-11-19T07:00:00", False),
    ({"product": "Blueberry Muffins", "net": "6 muffins", "contains": "Wheat, Milk, Eggs"},
     "", False),
]:
    e = app.products.put(bakery.product_from_fields(fields))
    app.products.get(e["id"])["last_used"] = used
    app.products.get(e["id"])["favourite"] = fav
app.products.save()
app.refresh_products()

steps = []


def step(fn=None, *, docs=True):
    def reg(f):
        f.docs = docs
        steps.append(f)
        return f
    return reg(fn) if fn else reg


def set_label(template, stock="large", orientation="", **fields):
    d = model.LabelDoc(template, stock, model.default_fields(template))
    d.fields.update(fields)
    d.orientation = orientation
    app.set_doc(d, None, mark_saved=False)


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
    return show(TemplatePicker(root, app.doc, cfg.render_ctx()), "screenshot-templates.png",
                600)


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
    return show(UsbDevicesDialog(root, app), "screenshot-usb.png", 1500)


@step
def wizard():
    from food_labeler.dialogs import SetupWizard
    return show(SetupWizard(root, app), "screenshot-wizard.png", 500)


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
    root.after(600, lambda: (grab("screenshot-cottage-check.png"), nxt()))
    return True


@step
def bakery_wizard():
    from food_labeler.bakery_dialogs import BakeryWizard
    return show(BakeryWizard(root, app), "screenshot-bakery-setup.png")


@step
def my_bakery():
    from food_labeler.bakery_dialogs import MyBakeryDialog
    return show(MyBakeryDialog(root, app), "screenshot-my-bakery.png")


@step
def ingredients():
    from food_labeler.bakery_dialogs import IngredientPicker
    return show(IngredientPicker(root, app), "screenshot-ingredients.png")


@step
def products():
    from food_labeler.bakery_dialogs import ProductPicker
    return show(ProductPicker(root, app), "screenshot-products.png")


@step
def lettering():
    from food_labeler.font_dialogs import LetteringDialog
    app.doc.set_template("simple")
    app.doc.fields.update(food="Lemon Thyme Shortbread", contains="Milk, Wheat",
                          note="Keep refrigerated")
    app.doc.lettering = {"name": "Pacifico", "other": "Lato"}
    app._sync_ui_from_doc()
    d = LetteringDialog(root, app.doc, app.render_ctx())
    d.deiconify()
    root.after(900, lambda: (grab("screenshot-lettering.png", d), d.destroy(),
                             grab("screenshot-fancy-name.png"), nxt()))
    return True


@step
def font_picker():
    from food_labeler.font_dialogs import FontPicker
    return show(FontPicker(root, "name", "Pacifico"), "screenshot-font-picker.png", 900)


@step
def get_fonts():
    from food_labeler.font_dialogs import GetFontsDialog
    return show(GetFontsDialog(root, "Dancing Script"), "screenshot-get-fonts.png")


@step
def picture_and_qr():
    from PIL import Image
    from food_labeler import pictures
    app.doc.lettering = {}
    app.doc.set_template("simple")
    app.doc.fields.update(food="Lemon Thyme Shortbread", contains="Milk, Wheat",
                          note="Keep refrigerated", made_by="")
    logo = Image.open(ROOT / "food_labeler" / "assets" / "icon.png")
    app.doc.picture = pictures.new_picture(pictures.normalise(logo), "Our logo",
                                           place="left", size=70)
    app.doc.qr = {"what": "link", "value": "https://example.com/menu",
                  "caption": "Scan for our menu", "place": "right", "size": 45}
    app._sync_ui_from_doc()
    root.after(900, lambda: (grab("screenshot-picture-qr.png"), nxt()))
    return True


@step
def picture_dialog():
    from food_labeler.picture_dialogs import PictureDialog
    return show(PictureDialog(root, app), "screenshot-picture.png", 1200)


@step
def qr_dialog():
    from food_labeler.picture_dialogs import QrDialog
    return show(QrDialog(root, app), "screenshot-qr.png", 900)


@step
def print_settings():
    from food_labeler.picture_dialogs import PrintSettingsDialog
    p = printers.Printer(id="usb:1-1.4", **FAKE_USB)
    return show(PrintSettingsDialog(root, app, p), "screenshot-print-settings.png", 900)


@step
def roll_setup():
    from food_labeler.picture_dialogs import RollSetupDialog
    p = printers.Printer(id="usb:1-1.4", **FAKE_USB)
    return show(RollSetupDialog(root, app, p), "screenshot-roll-setup.png", 900)


@step
def roll_notice():
    # the printer "is connected" and last had a different roll set up
    app.found = fake_printers()
    cfg.printer_info("usb:1-1.4")["roll"] = {"stock": "medium", "media": "gap",
                                             "date": "2026-11-01", "same": []}
    app.refresh_printer_combo()
    app.refresh_roll_notice()
    root.after(900, lambda: (grab("screenshot-roll-notice.png"), nxt()))
    return True


@step
def report_dialog():
    from food_labeler.dialogs import ReportDialog
    return show(ReportDialog(root, app), "screenshot-report.png", 1500)


@step
def advanced_dialog():
    from food_labeler.dialogs import AdvancedDialog
    return show(AdvancedDialog(root, app), "screenshot-advanced.png", 900)


# ---------------------------------------------------------------------------
# the walk-through (SHOT_ALL=1): every other window and flow
# ---------------------------------------------------------------------------

@step(docs=False)
def w_products_strip():
    set_label("simple", food="")
    root.after(600, lambda: (grab("w-products-strip.png"), nxt()))
    return True


@step(docs=False)
def w_products_search():
    app.find_var.set("sour")
    root.after(500, lambda: (grab("w-products-search.png"), nxt()))
    return True


@step(docs=False)
def w_products_search_none():
    app.find_var.set("pie")
    root.after(500, lambda: (grab("w-products-search-none.png"), nxt()))
    return True


@step(docs=False)
def w_product_on_simple():
    app.find_var.set("sour")
    app._find_enter()                       # Enter: the first match
    root.after(600, lambda: (grab("w-product-simple.png"), nxt()))
    return True


@step(docs=False)
def w_product_on_sticker():
    set_label("sticker")
    p = app.products.find("Lemon Thyme Shortbread")
    app.use_product(p)                     # asks, answered yes: becomes a cottage label
    print("KIND after product on a sticker:", app.doc.template)
    root.after(800, lambda: (grab("w-product-sticker-to-cottage.png"), nxt()))
    return True


@step(docs=False)
def w_product_save():
    set_label("simple", food="Pumpkin Bread", contains="Wheat, Eggs", note="Keep cool")
    app.save_product()                      # name comes from the label
    print("PRODUCTS:", [(p["name"], p["kind"], bool(p["last_used"]))
                        for p in app.products.quick(8)])
    root.after(600, lambda: (grab("w-product-saved.png"), nxt()))
    return True


@step(docs=False)
def w_product_on_package():
    set_label("package", stock="xl")
    app.use_product(app.products.find("Pumpkin Bread"))
    root.after(600, lambda: (grab("w-product-package.png"), nxt()))
    return True


@step(docs=False)
def w_products_empty():
    saved = list(app.products.items)
    app.products.items = []
    app.refresh_products()

    def back():
        grab("w-products-none.png")
        app.products.items = saved
        app.refresh_products()
        nxt()
    root.after(500, back)
    return True


@step(docs=False)
def w_kinds():
    seq = [("free", dict(text="Happy\nBirthday!")), ("sticker", dict(count="12")),
           ("picture", dict(text="Thank you!"))]

    def one():
        if not seq:
            nxt()
            return
        t, f = seq.pop(0)
        set_label(t, "large", **f)
        if t == "picture":
            from PIL import Image
            from food_labeler import pictures
            logo = Image.open(ROOT / "food_labeler" / "assets" / "icon.png")
            app.doc.picture = pictures.new_picture(pictures.normalise(logo), "Our logo",
                                                   place="fit", size=100)
            app._sync_ui_from_doc()
        root.after(700, lambda: (grab(f"w-kind-{t}.png"), one()))
    one()
    return True


@step(docs=False)
def w_tall():
    set_label("simple", food="Chicken Noodle Soup", contains="Wheat, Eggs",
              note="Keep refrigerated")
    app.set_orientation("tall")
    root.after(700, lambda: (grab("w-tall.png"), nxt()))
    return True


@step(docs=False)
def w_round():
    set_label("simple", "round", food="Jam")
    root.after(700, lambda: (grab("w-round.png"), nxt()))
    return True


@step(docs=False)
def w_extras_chips():
    from PIL import Image
    from food_labeler import pictures
    set_label("simple", food="Lemon Thyme Shortbread", contains="Milk, Wheat")
    logo = Image.open(ROOT / "food_labeler" / "assets" / "icon.png")
    app.doc.picture = pictures.new_picture(pictures.normalise(logo), "Our logo",
                                           place="left", size=60)
    app.doc.qr = {"what": "phone", "value": "555 010 0199", "place": "right", "size": 45}
    app.doc.lettering = {"name": "Pacifico", "other": "Lato"}
    app._sync_ui_from_doc()

    def removed():
        app.remove_picture()
        app.remove_qr()
        root.after(500, lambda: (grab("w-extras-removed.png"), nxt()))
    root.after(700, lambda: (grab("w-extras.png"), removed()))
    return True


def _grab_menu(btn, name):
    btn.show_menu()

    def done():
        m = btn.menu
        grab(name, m)
        m.unpost()
        nxt()
    root.after(500, done)
    return True


@step(docs=False)
def w_printer_options():
    app.found = fake_printers()
    app.refresh_printer_combo()
    return _grab_menu(app.options_btn, "w-printer-options.png")


@step(docs=False)
def w_open_menu():
    for i, name in enumerate(["Chicken Soup", "Lemon Shortbread", "Sourdough"]):
        d = model.LabelDoc("simple", "large", model.default_fields("simple"))
        d.fields["food"] = name
        app.doc = d
        app._write(settings.labels_dir() / f"{name}.label")
    return _grab_menu(app.open_btn, "w-open-menu.png")


@step(docs=False)
def w_open_dialog():
    from food_labeler.dialogs import OpenDialog
    return show(OpenDialog(root, settings.labels_dir()), "w-open-dialog.png")


@step(docs=False)
def w_save_dialog():
    from food_labeler.dialogs import NameDialog
    return show(NameDialog(root, "Chicken Soup", settings.labels_dir()), "w-save-dialog.png")


@step(docs=False)
def w_open_recent():
    path = app.cfg.recent()[-1]["path"]
    app.open_path(path)
    root.after(500, lambda: (grab("w-opened.png"), nxt()))
    return True


@step(docs=False)
def w_print_dialog():
    from food_labeler.dialogs import PrintDialog
    return show(PrintDialog(root, app), "w-print-dialog.png")


@step(docs=False)
def w_my_printers():
    from food_labeler.dialogs import MyPrintersDialog
    app.found = fake_printers()
    return show(MyPrintersDialog(root, app), "w-my-printers.png")


@step(docs=False)
def w_network_printer():
    from food_labeler.dialogs import NetworkPrinterDialog
    printers.add_network_printer(cfg["printers"], "192.0.2.10:9100", "tspl",
                                 "lp610bt-compatible", "Shed printer")
    return show(NetworkPrinterDialog(root, app), "w-network-printer.png")


@step(docs=False)
def w_setup_wizard_2():
    from food_labeler.dialogs import SetupWizard
    d = SetupWizard(root, app)
    d.step2()
    return show(d, "w-setup-wizard-2.png")


@step(docs=False)
def w_bakery_wizard_2():
    from food_labeler.bakery_dialogs import BakeryWizard
    d = BakeryWizard(root, app)
    d.lst.lb.selection_set(0)
    d._picked()
    return show(d, "w-bakery-wizard-2.png")


@step(docs=False)
def w_bakery_wizard_3():
    from food_labeler.bakery_dialogs import BakeryWizard
    d = BakeryWizard(root, app)
    d.lst.lb.selection_set(0)
    d._picked()
    d.step3()
    return show(d, "w-bakery-wizard-3.png")


@step(docs=False)
def w_settings():
    from food_labeler.dialogs import SettingsDialog
    return show(SettingsDialog(root, app), "w-settings.png")


@step(docs=False)
def w_stock_picker():
    from food_labeler.dialogs import StockPicker
    return show(StockPicker(root, "simple", "large"), "w-stock-picker.png")


@step(docs=False)
def w_calendar():
    return show(widgets.CalendarDialog(root, "Choose the “Made on” date", None),
                "w-calendar.png")


@step(docs=False)
def w_my_pictures():
    from food_labeler import pictures
    from food_labeler.picture_dialogs import MyPicturesDialog
    return show(MyPicturesDialog(root, pictures.Library(settings.data_dir())),
                "w-my-pictures.png")


@step(docs=False)
def w_ingredient_editor():
    from food_labeler.bakery_dialogs import IngredientEditor
    return show(IngredientEditor(root), "w-ingredient-editor.png")


@step(docs=False)
def w_tab_order():
    """Where Tab goes from the top of the window (printed, for checking by eye)."""
    set_label("simple", food="Soup")
    root.update()
    seen = []
    w = app.find_entry
    for _ in range(40):
        try:
            text = w.cget("text") if "text" in w.keys() else w.winfo_class()
        except tk.TclError:
            text = w.winfo_class()
        seen.append(str(text)[:22])
        w = w.tk_focusNext()
        if w is None or w is app.find_entry:
            break
    print("TAB ORDER:", " | ".join(seen))


@step(docs=False)
def w_picture_mostly_black():
    """A dark picture: the Picture window says it will print mostly black."""
    from PIL import Image, ImageDraw
    from food_labeler import pictures
    from food_labeler.picture_dialogs import PictureDialog
    im = Image.new("RGB", (300, 200), (120, 70, 30))
    ImageDraw.Draw(im).ellipse((90, 40, 210, 160), fill=(250, 200, 120))
    set_label("simple", food="Brownies")
    app.doc.picture = pictures.new_picture(pictures.normalise(im), "Dark picture",
                                           place="left", size=80, threshold=230)
    app._sync_ui_from_doc()
    return show(PictureDialog(root, app), "w-picture-mostly-black.png", 1200,
                after=lambda d: print("BLACK WARNING:", d.black_lbl.cget("text")[:80]))


@step(docs=False)
def w_dry_run_prints():
    """PRINT for real (dry run): simple, cottage and picture, wide and tall."""
    from PIL import Image
    from food_labeler import pictures
    app.found = fake_printers()
    cfg["selected"] = "usb:1-1.4"
    app.refresh_printer_combo()
    logo = Image.open(ROOT / "food_labeler" / "assets" / "icon.png")
    cases = []
    for way in ("wide", "tall"):
        cases.append(("simple", way, dict(food="Chicken Soup", contains="Wheat")))
        cases.append(("cottage", way, dict(
            product="Lemon Thyme Shortbread", net="8 oz",
            ingredients="Butter, flour, sugar, lemon", contains="Milk, Wheat")))
        cases.append(("picture", way, dict(text="Thank you!")))

    def one():
        if not cases:
            nxt()
            return
        t, way, f = cases.pop(0)
        set_label(t, "large", **f)
        if t == "picture":
            app.doc.picture = pictures.new_picture(pictures.normalise(logo), "Our logo",
                                                   place="fit", size=100)
        app.doc.set_orientation(way)
        app._sync_ui_from_doc()
        before = len(list(JOBS.glob("*.bin"))) if JOBS.exists() else 0
        app.print_now()

        def check(tries=0):
            if app._printing and tries < 50:
                root.after(100, lambda: check(tries + 1))
                return
            now = len(list(JOBS.glob("*.bin"))) if JOBS.exists() else 0
            print(f"JOBS {t} {way}: {now - before} new job file(s); "
                  f"message: {app.message_lbl.cget('text')!r}")
            if now - before != 1:
                PROBLEMS.append(f"PRINT {t} {way} wrote {now - before} jobs")
            grab(f"w-printed-{t}-{way}.png")
            one()
        root.after(300, check)
    one()
    return True


def nxt():
    while steps:
        fn = steps.pop(0)
        if ONLY and fn.__name__ not in ONLY:
            continue
        if not ONLY and not ALL and not fn.docs:
            continue
        break
    else:
        root.after(100, root.destroy)
        return
    try:
        waits = fn()
    except Exception as e:  # keep going, so one broken step can't hang the run
        import traceback
        traceback.print_exc()
        print("step failed:", fn.__name__, e)
        PROBLEMS.append(f"step failed: {fn.__name__}: {e}")
        waits = False
    if not waits:
        root.after(300, nxt)


root.after(1500, nxt)
root.after(240000 if ALL else 90000, root.destroy)  # never leave a window behind
root.mainloop()
jobs = sorted(JOBS.glob("*.bin")) if JOBS.exists() else []
print(f"JOBS total: {len(jobs)} dry-run job file(s) in {JOBS}")
print(f"PROBLEMS: {len(PROBLEMS)}")
for p in PROBLEMS:
    print("  ", p)
print("smoke test OK")
