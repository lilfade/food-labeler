"""Will every button fit at 1280x720? Checked with arithmetic, no window needed.

Widths are worked out from the real DejaVu Sans font metrics (the font the app
uses on Linux; Windows uses Segoe UI, which is narrower) at 96 dpi, using the
same paddings as widgets.button(). Each row's needed width must fit the space
the window gives it.
"""
import pytest

from food_labeler import app as appmod, dates, model, templates

PT = appmod.FONT_SIZES
SCREEN_W = 1280
BTN_PAD = 2 * 12 + 2 * 2 + 4            # padx both sides, focus ring, Tk internal
CHIP_GAP = 6


def px(text, font, scale):
    size, weight = PT[font]
    pixels = round(size * scale * 96 / 72)
    return templates.font(pixels, weight == "bold").getlength(text)


def btn(text, font="ui", scale=1.0):
    return px(text, font, scale) + BTN_PAD


def left_column(scale):
    rows = []
    # kind / size bar: label + (wrapped) name + Change...
    rows.append(px("Kind of label:", "ui", scale) + 8 + min(240, px("Simple food label", "ui_bold", scale))
                + btn("Change…", "ui", scale) + 28)
    rows.append(px("Label size:", "ui", scale) + 8 + min(240, px("Extra-large — 4 × 6 inches",
                                                                   "ui_bold", scale))
                + btn("Change…", "ui", scale) + 28)
    form = []
    form.append(sum(btn(t, "ui", scale) + 4 for t in ["− 1 day", "+ 1 day", "Calendar", "Today"]))
    form.append(3 * (max(btn(t, "ui", scale) for t, _, _ in dates.QUICK) + 4))
    form.append(3 * (max(px("✔ " + a, "ui", scale) + 24 for a in model.ALLERGENS) + 6))
    form.append(2 * (max(btn(t, "ui", scale) for t in model.NOTE_CHIPS) + 6))
    form.append(px("\U0001F4C5  " + dates.fmt_long(dates.dt.date(2026, 9, 30)), "field", scale)
                + BTN_PAD)
    form.append(px("Put my kitchen name on the label", "ui", scale) + 28)
    sections = max(form) + 2 * 14 + 2 * 3            # section padding + highlight
    rows.append(sections + 24 + 2)                   # scrollbar + border
    return max(rows)


def right_column(scale):
    rows = [
        px("This is how your label will look", "ui_bold", scale) + btn("Save as picture", "ui", scale),
        px("Printer:", "ui_bold", scale) + 8 + 420 + 20 + 6 + 24 + 2,   # menubutton wraps at 420
        btn("Look for printers again", "ui", scale) + 6 + btn("My printers…", "ui", scale) + 26,
        btn("My printer isn't in the list", "ui", scale) + 26,
        px("“White label printer” isn't connected", "ui", scale) + 26,
    ]
    return max(rows)


@pytest.mark.parametrize("scale", [1.0, 1.1])
def test_rows_fit_1280(scale):
    top = (56 + 8 + max(px("Food Labeler", "title", scale), px("by High Thyme Kitchen", "small", scale))
           + 18 + sum(btn(t, "ui", scale) + 8 for t in ["New", "Open", "Save", "Print…", "Undo"])
           + btn("Settings", "ui", scale) + 8 + 2 * (btn("A+", "ui", scale) + 4)
           + px("Text size", "small", scale) + 12 + 28)
    recent = (px("My saved labels:", "ui_bold", scale) + 8
              + 3 * (btn("A very long lab…", "ui", scale) + 6) + btn("More…", "ui", scale) + 28)
    main = left_column(scale) + 10 + right_column(scale) + 28
    zero = px("0", "huge", scale)
    bottom = (px("How many labels?", "big", scale) + 12 + 2 * (2 * zero + BTN_PAD + 8)
              + 3 * zero + 8 + 18 + px("PRINT", "huge", scale) + 2 * 60 + 8 + 20 + 28)
    for name, w in [("top bar", top), ("saved labels", recent), ("form + preview", main),
                    ("bottom bar", bottom)]:
        assert w <= SCREEN_W, f"{name} needs {w:.0f}px at scale {scale}"
