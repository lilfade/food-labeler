"""Print settings per printer: darkness, speed, nudging, upside down, gap, media,
what happens after printing. Plain words in the window, printer commands here.

Kept in settings.json under each printer (``printers[<id>]["print"]``). Only
what the user changed is stored; an empty dict means "normal", and then the
print jobs are byte for byte what they were before these settings existed.

==================  =====================================  ===========================
setting             TSPL (LP610BT and clones)              ZPL (Zebra)
==================  =====================================  ===========================
darkness            DENSITY 0–15 (normal 8)                ^MD -30..30 (normal 0 =
                                                           the printer's own)
speed               SPEED 1–6                              ^PR 2–6
nudge_x / nudge_y   the picture is moved inside the label (mm, ±5, 0.5 steps)
upside_down         the picture is turned 180°
gap                 GAP <mm> (per label size)              (the printer measures it)
media               GAP / BLINE / GAP 0 (continuous)       ^MN W / M / N
after               OFFSET <mm> ("tear" = 0)               ^TA <dots> ("tear" = 0)
==================  =====================================  ===========================

Nudging and turning are done on the picture, not with SHIFT/REFERENCE
commands, so they work the same on every printer. Nothing here is ever sent
by itself: settings only change the jobs the user prints, and the darkness
test and "feed one blank label" are sent only from their buttons.
"""
from __future__ import annotations

from PIL import Image

from . import stocks, values
from .stocks import Stock

TSPL_DARKNESS = (0, 15)
ZPL_DARKNESS = (-30, 30)
TSPL_SPEED = (1, 6)
ZPL_SPEED = (2, 6)
NUDGE_MM = 5.0
GAP_MM = (0.0, 10.0)
FEED_MM = (0.0, 10.0)
MEDIA = {"gap": "Labels with gaps", "mark": "Labels with black marks",
         "continuous": "Continuous roll"}
AFTER = {"tear": "Stop so I can tear it off", "feed": "Feed a little extra"}
DEFAULT_FEED_MM = 3.0
ZPL_MEDIA = {"gap": "W", "mark": "M", "continuous": "N"}


_num = values.is_number          # finite numbers only (no NaN or infinity from a file)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def clean(value) -> dict:
    """Valid settings only, each clamped to its range. Unknown keys are dropped."""
    out: dict = {}
    if not isinstance(value, dict):
        return out
    if _num(value.get("darkness")):
        out["darkness"] = int(_clamp(round(value["darkness"]), *TSPL_DARKNESS))
    if _num(value.get("zpl_darkness")):
        out["zpl_darkness"] = int(_clamp(round(value["zpl_darkness"]), *ZPL_DARKNESS))
    if _num(value.get("speed")):
        out["speed"] = int(_clamp(round(value["speed"]), *TSPL_SPEED))
    if _num(value.get("zpl_speed")):
        out["zpl_speed"] = int(_clamp(round(value["zpl_speed"]), *ZPL_SPEED))
    for k in ("nudge_x", "nudge_y"):
        if _num(value.get(k)):
            v = round(_clamp(float(value[k]), -NUDGE_MM, NUDGE_MM) * 2) / 2   # 0.5 mm steps
            if v:
                out[k] = v
    if value.get("upside_down") is True:
        out["upside_down"] = True
    gap = value.get("gap")
    if isinstance(gap, dict):
        g = {k: round(float(_clamp(v, *GAP_MM)), 1) for k, v in gap.items()
             if k in stocks.STOCKS and _num(v)}
        if g:
            out["gap"] = g
    if values.choice(value.get("media"), MEDIA, None):
        out["media"] = value["media"]
    if values.choice(value.get("after"), AFTER, None):
        out["after"] = value["after"]
        if value["after"] == "feed":
            f = value.get("feed_mm")
            out["feed_mm"] = round(float(_clamp(f, *FEED_MM)), 1) if _num(f) else DEFAULT_FEED_MM
    return out


def mm_to_dots(mm: float, dpi: int) -> int:
    """Millimetres to whole printer dots (rounded half away from zero)."""
    v = mm * dpi / 25.4
    return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def adjust_image(img: Image.Image, stock: Stock, ps: dict | None) -> Image.Image:
    """The label picture as it goes to the printer: nudged, then turned if asked.

    Nudge: positive x = to the right, positive y = down, as you look at the
    label. What moves off the edge is cut off; what comes in is paper. The
    turn comes after the nudge, so "move right" still means right on the
    finished label. Returns ``img`` itself when nothing is set.
    """
    ps = clean(ps)
    dx = mm_to_dots(ps.get("nudge_x", 0.0), stock.dpi)
    dy = mm_to_dots(ps.get("nudge_y", 0.0), stock.dpi)
    out = img
    if dx or dy:
        out = Image.new("1", img.size, 1)
        out.paste(img.convert("1"), (dx, dy))
    if ps.get("upside_down"):
        out = out.convert("1").transpose(Image.Transpose.ROTATE_180)
    return out


def tspl_values(stock: Stock, ps: dict | None, advanced: dict | None = None,
                family=None) -> dict:
    """DENSITY/SPEED/GAP for a TSPL job: this printer's print settings, else the
    Advanced setting for this size, else the model's default, else the size's."""
    ps = clean(ps)
    adv = advanced or {}
    dens = ps.get("darkness")
    if dens is None:
        dens = adv.get("density", {}).get(stock.id)
    if dens is None and family is not None:
        dens = family.density_for(stock.id)
    spd = ps.get("speed")
    if spd is None:
        spd = adv.get("speed", {}).get(stock.id)
    if spd is None and family is not None:
        spd = family.speed_for(stock.id)
    gap = ps.get("gap", {}).get(stock.id)
    if gap is None:
        gap = adv.get("gap", {}).get(stock.id)
    return {"density": dens, "speed": spd, "gap_mm": gap, "media": ps.get("media"),
            "offset_mm": _after_mm(ps)}


def _after_mm(ps: dict):
    if "after" not in ps:
        return None                  # never touched: send nothing (as before)
    return ps.get("feed_mm", DEFAULT_FEED_MM) if ps["after"] == "feed" else 0.0


def zpl_values(stock: Stock, ps: dict | None, advanced: dict | None = None) -> dict:
    """^MD/^PR/^MN/^TA for a ZPL job (None = as before)."""
    ps = clean(ps)
    adv = advanced or {}
    md = ps.get("zpl_darkness")
    if md is None:
        md = adv.get("zpl_darkness")
    after = _after_mm(ps)
    return {"darkness": md, "speed": ps.get("zpl_speed"),
            "media": ZPL_MEDIA.get(ps.get("media", ""), None),
            "tear_dots": None if after is None else _clamp(mm_to_dots(after, stock.dpi),
                                                           -120, 120)}


def effective_darkness(kind: str, stock: Stock, ps: dict | None, advanced=None,
                       family=None) -> int:
    """The darkness a print would use now (for the slider and the darkness test)."""
    if kind == "zpl":
        md = zpl_values(stock, ps, advanced)["darkness"]
        return int(stock.zpl_md if md is None else md)
    d = tspl_values(stock, ps, advanced, family)["density"]
    return int(stock.density if d is None else d)


def effective_speed(kind: str, stock: Stock, ps: dict | None, advanced=None,
                    family=None) -> int:
    """The speed a print would use now."""
    if kind == "zpl":
        s = zpl_values(stock, ps, advanced)["speed"]
        return int(stock.zpl_pr if s is None else s)
    s = tspl_values(stock, ps, advanced, family)["speed"]
    return int(stock.speed if s is None else s)


def darkness_levels(kind: str, current: int) -> list[tuple[str, int]]:
    """Three darkness settings to try: lighter, the current one, darker."""
    lo, hi = ZPL_DARKNESS if kind == "zpl" else TSPL_DARKNESS
    step = 10 if kind == "zpl" else 3
    return [("Lighter", _clamp(current - step, lo, hi)), ("Now", _clamp(current, lo, hi)),
            ("Darker", _clamp(current + step, lo, hi))]
