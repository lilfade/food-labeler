"""Setting up a new roll ("calibrating"): the job for each printer language and
kind of roll, the line-up label, the by-hand instructions, and what is
remembered per printer. No Tk here; the window is ``RollSetupDialog`` in
picture_dialogs.py.

============  =======================================  ==============================
roll          TSPL (LP610BT and clones)                ZPL (Zebra)
============  =======================================  ==============================
gaps          SIZE + GAP <g> mm + GAPDETECT            ^XA^MNW^XZ then ~JC
black marks   SIZE + BLINE <b> mm + BLINEDETECT        ^XA^MNM^XZ then ~JC
              (unverified on LP610BT clones)
continuous    SIZE + GAP 0 mm (nothing is fed)         ^XA^MNN^PW^LL^XZ (nothing fed)
============  =======================================  ==============================

Nothing here is ever sent by itself. ``send_setup`` only sends after the
``confirm`` callback (the "This feeds 2–4 blank labels. OK?" question) says
yes, and the window only calls it from the "Set it up" button. Starting the
program, picking a printer or changing the label size never sends anything;
at most a one-line notice offers to set up the roll (``show_notice``).

Remembered in settings.json under each printer::

    printers[<id>]["roll"] = {"stock": "large", "media": "gap", "date": "2026-11-20",
                              "same": ["medium"]}

``same`` holds the label sizes for which the person pressed "No, same roll";
it is emptied whenever a roll is set up again.
"""
from __future__ import annotations

import datetime as _dt

from PIL import ImageDraw

from . import printsettings, stocks, templates, tspl, values, zpl
from .stocks import Stock

MEDIA = printsettings.MEDIA            # "gap" / "mark" / "continuous" in plain words
CONFIRM = "This feeds 2–4 blank labels. OK?"
CONFIRM_CONTINUOUS = ("This tells the printer the size of your labels. It doesn't feed or "
                      "use any labels. OK?")

# Shown when the printer's model has no "calibrate_by_hand" of its own.
GENERIC_BY_HAND = ("Most label printers can also do this by themselves: with the roll in and "
                   "the lid closed, hold the feed button until the light flashes, then let "
                   "go. The printer feeds a few labels and stops. The printer's own guide "
                   "calls this “media calibration” or “gap detection”.")

# BLINEDETECT has only been checked against the TSPL2 manual, not on a clone.
MARK_UNVERIFIED = ("Setting up a roll with black marks hasn't been tried on every printer of "
                   "this kind. If it doesn't line up, use the printer's own button (below).")

STEP1 = "Put the new roll in. Pull out a few labels past the front and close the lid."
STEP2 = "What is on the roll?"
STEP3 = "Set it up"
CONTINUOUS_NOTE = ("A continuous roll has no gaps to find, so there is nothing to set up. "
                   "This only tells the printer how long each label is.")


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def clean_media(media) -> str:
    """One of "gap", "mark", "continuous" (anything else: "gap")."""
    return values.choice(media, MEDIA, "gap")


def uses_labels(media) -> bool:
    """Setting up a gap or black-mark roll feeds labels; a continuous one doesn't."""
    return clean_media(media) != "continuous"


def confirm_text(media) -> str:
    """The question asked before anything is sent."""
    return CONFIRM if uses_labels(media) else CONFIRM_CONTINUOUS


def setup_job(kind: str, stock: Stock, media="gap", gap_mm: float | None = None) -> bytes:
    """The set-up job for this printer language (``kind``: "tspl" / "zpl"; anything
    else is treated as TSPL, like printing is) and kind of roll."""
    media = clean_media(media)
    if kind == "zpl":
        return zpl.calibrate_job(stock, media)
    return tspl.calibrate_job(stock, gap_mm, media)


def setup_job_for(stock: Stock, printer_cfg: dict, advanced: dict | None, media=None,
                  print_settings: dict | None = None, family=None) -> bytes:
    """``setup_job`` with the gap / mark height this printer would print with
    (its print settings, else Advanced, else the label size's)."""
    ps = printsettings.clean(print_settings)
    if media is None:
        media = ps.get("media", "gap")
    gap = printsettings.tspl_values(stock, ps, advanced or {}, family)["gap_mm"]
    return setup_job(printer_cfg.get("kind") or "tspl", stock, media, gap)


def send_setup(printer_cfg: dict, data: bytes, confirm, send=None) -> bool:
    """Send a set-up job only if ``confirm()`` returns True (the person said OK).

    Returns True if it was sent. ``send`` defaults to printers.send; it may
    raise printers.PrinterError, which is passed on.
    """
    if confirm() is not True:
        return False
    if send is None:
        from . import printers
        send = printers.send
    send(printer_cfg, data)
    return True


# ---------------------------------------------------------------------------
# the line-up label
# ---------------------------------------------------------------------------

def size_words(stock: Stock) -> str:
    """'Large 4 × 2 inches' (the size's name without the dash)."""
    return stock.name.replace(" — ", " ")


def lineup_lines(stock: Stock) -> list[str]:
    """The words on the line-up label."""
    shape = "circle" if stock.round else "box"
    return [f"Test: {size_words(stock)}", f"The {shape} should sit just inside the label"]


def lineup_label_image(stock: Stock):
    """A label to see whether printing lines up with the roll.

    A box (a circle on round labels) 1 mm inside the edges, the size's name,
    and an arrow pointing to the top edge of the picture, which is the edge
    that leaves the printer first (TSPL DIRECTION 1 / ZPL normal orientation;
    "Print upside down" turns the whole picture, arrow included). Drawn at the
    stock's resolution; mode "1", stock.w × stock.h dots.
    """
    from . import render
    one_mm = stocks.mm_to_dots(1.0, stock.dpi)
    line = max(2, stock.d(3))
    region = templates.region_for(stock)
    # keep a band at the top of the text area for the arrow
    arrow_h = max(stock.d(20), int(region.height * 0.22))
    region.top += arrow_h
    base = templates._base(region)
    blocks = [templates.Block("", t, base * (0.2 if i == 0 else 0.12), stock.d(12), i == 0,
                              "center", 0.3, True)
              for i, t in enumerate(lineup_lines(stock))]
    lay = templates.fit(blocks, region, "center")
    img = render.draw_layout(lay, stock.w, stock.h, stock.dpi > stocks.BASE_DPI)
    d = ImageDraw.Draw(img)
    if stock.round:
        cx, cy = stock.circle_center
        r = stock.circle_dia / 2.0 - one_mm
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=line)
    else:
        d.rectangle((one_mm, one_mm, stock.w - 1 - one_mm, stock.h - 1 - one_mm), outline=0,
                    width=line)
    # the arrow: a triangle head on a short shaft, centred in the band
    cx = stock.w / 2.0
    top = region.top - arrow_h + stock.d(2)
    bottom = region.top - stock.d(2)
    head = max(4, (bottom - top) * 0.55)
    half = head * 0.8
    d.polygon([(cx, top), (cx - half, top + head), (cx + half, top + head)], fill=0)
    shaft = max(2, stock.d(5))
    d.rectangle((cx - shaft / 2, top + head - 1, cx + shaft / 2, bottom), fill=0)
    return img


def lineup_label_job(stock: Stock, printer_cfg: dict, advanced: dict | None, family=None,
                     print_settings: dict | None = None) -> bytes:
    """The line-up label as a normal print job: this printer's print settings
    (darkness, speed, media, nudge, upside down) and resolution apply, exactly
    as for any label. ``stock`` must be at the printer's dpi."""
    from . import printers
    img = printsettings.adjust_image(lineup_label_image(stock), stock, print_settings)
    return printers.build_job(img, stock, printer_cfg, advanced or {}, 1, family,
                              print_settings)


# ---------------------------------------------------------------------------
# words
# ---------------------------------------------------------------------------

def by_hand(family) -> str:
    """How to set up the roll with the printer's own button (from known_printers.json)."""
    text = getattr(family, "calibrate_by_hand", "") if family is not None else ""
    return text or GENERIC_BY_HAND


def still_not_right(family) -> str:
    """The line shown in the window under the steps."""
    return "If it still isn't right: " + by_hand(family)


def help_text(family, kind: str = "tspl", media: str = "gap") -> str:
    """What to try when the line-up label is off ("It's off — help me")."""
    parts = [
        "If the writing is a little to one side, or too high or too low: press "
        "“Print settings…” and use “Nudge the print”.",
        "If it prints across the gap between labels, or skips labels: check the size and "
        "the kind of roll above and press “Set it up” again.",
    ]
    if kind != "zpl" and clean_media(media) == "mark":
        parts.append(MARK_UNVERIFIED)
    parts.append(still_not_right(family))
    return "\n\n".join(parts)


def notice_text(printer_name: str) -> str:
    """The one-line notice under the printer when the size changed."""
    return (f"New roll in the {printer_name}? Set it up so labels line up —")


# ---------------------------------------------------------------------------
# what is remembered per printer
# ---------------------------------------------------------------------------

def last_roll(info: dict | None) -> dict | None:
    """The last roll set up on this printer ({"stock", "media", "date", "same"}) or None."""
    r = (info or {}).get("roll")
    if not isinstance(r, dict) or values.choice(r.get("stock"), stocks.STOCKS, None) is None:
        return None
    same = r.get("same")
    return {"stock": r["stock"], "media": clean_media(r.get("media")),
            "date": r.get("date") if isinstance(r.get("date"), str) else "",
            "same": [s for s in same if values.choice(s, stocks.STOCKS, None)]
            if isinstance(same, list) else []}


def remember_roll(info: dict, stock_id: str, media, when: _dt.date | None = None) -> dict:
    """Keep the roll just set up in this printer's settings (and forget "same roll")."""
    when = when or _dt.date.today()
    info["roll"] = {"stock": stock_id, "media": clean_media(media), "date": when.isoformat(),
                    "same": []}
    return info["roll"]


def show_notice(info: dict | None, stock_id: str) -> bool:
    """True when the label size differs from the last roll set up on this printer
    and the person hasn't said "No, same roll" for this size. No roll set up
    yet: no notice (nothing to compare with)."""
    r = last_roll(info)
    return bool(r) and stock_id != r["stock"] and stock_id not in r["same"]


def dismiss_notice(info: dict, stock_id: str) -> None:
    """ "No, same roll": don't offer again for this size until a roll is set up."""
    r = last_roll(info)
    if r is None:
        return
    if stock_id not in r["same"]:
        r["same"].append(stock_id)
    info["roll"] = r
