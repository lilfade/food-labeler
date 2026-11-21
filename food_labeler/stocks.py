"""Label stocks (roll sizes), in mm and in printer dots at 203 or 300 dpi.

A Stock is the physical label: its size in dots (what we render) and in mm
(what TSPL's SIZE/GAP want), plus per-size printer defaults. The ids
(small, medium, large, round, xl) are stored in .label files, settings and
printer definition files, so they must never change.

Resolution belongs to the printer, not to the label: ``get(stock_id, dpi)``
gives the same physical label in the dots of a 203 dpi (8 dots per mm) or a
300 dpi print head. Every other dot-based number in the layout is written
for 203 dpi and goes through ``dots()`` / ``Stock.d()``, which returns it
unchanged at 203 dpi (so 203 dpi output stays exactly as it always was) and
scales it by dpi / 203 otherwise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

DPI = 203                      # the base resolution every layout number is written for
BASE_DPI = DPI
SUPPORTED_DPI = (203, 300)
DOTS_PER_MM = 8


def dots(n: float, dpi: int = BASE_DPI) -> int:
    """A size written in 203 dpi dots, in dots of a ``dpi`` printer (rounded half up).

    At 203 dpi it is ``n`` itself, so nothing changes for 203 dpi printers.
    """
    if dpi == BASE_DPI:
        return int(n)
    return int(math.floor(n * dpi / BASE_DPI + 0.5))


def mm_to_dots(mm: float, dpi: int) -> int:
    """Millimetres to printer dots: round(mm * dpi / 25.4), half up."""
    return int(math.floor(mm * dpi / 25.4 + 0.5))


@dataclass(frozen=True)
class Stock:
    """One label size. Frozen: shared by everything, never modified."""
    id: str
    name: str            # friendly name shown to the user
    hint: str            # what it is good for
    w: int               # width in dots
    h: int               # height in dots
    w_mm: float
    h_mm: float
    gap_mm: float = 3.0
    round: bool = False
    circle_dia: int = 0  # printable circle diameter in dots (round stock only)
    density: int = 8     # TSPL DENSITY default
    speed: int = 4       # TSPL SPEED default
    zpl_lt: int = 0      # ZPL ^LT label top
    zpl_md: int = 0      # ZPL ^MD darkness (relative to the printer's setting)
    zpl_pr: int = 3      # ZPL ^PR print rate
    dpi: int = BASE_DPI  # resolution the dot sizes above are for
    # Height of the label's printed face in mm when it is shorter than the
    # roll's nominal size (0 = the same as h_mm). "2 inch" die-cut labels are
    # really about 50.0 mm: a Zebra measured this roll at 399-400 dots and the
    # LP610BT left the bottom 6 rows of a 406-row picture in the gap. ``h`` is
    # drawn to the face; TSPL SIZE still states the nominal h_mm that the
    # printers were proven with, and the gap sensor finds each label.
    face_h_mm: float = 0.0

    @property
    def drawn_h_mm(self) -> float:
        """The height the picture is drawn to, in mm (the face, if smaller)."""
        return self.face_h_mm or self.h_mm

    @property
    def scale(self) -> float:
        """dpi / 203: how much bigger one 203 dpi dot is in this stock's dots."""
        return self.dpi / BASE_DPI

    def d(self, n: float) -> int:
        """A 203 dpi dot size in this stock's dots (see ``dots``)."""
        return dots(n, self.dpi)

    @property
    def small(self) -> bool:
        """The little date sticker size (narrower than about 2 inches)."""
        return self.w_mm < 50

    @property
    def margin(self) -> int:
        """Blank border in dots kept clear on rectangular labels."""
        return self.d(12 if self.small else 24)

    @property
    def size_inches(self) -> str:
        """Human-readable size, e.g. '4 × 2 in'."""
        return f"{self.w_mm / 25.4:.3g} × {self.h_mm / 25.4:.3g} in"

    @property
    def circle_center(self) -> tuple[float, float]:
        """Centre of the printable circle on round stock (in dots)."""
        return (self.w / 2.0, self.h / 2.0)


STOCKS: dict[str, Stock] = {
    s.id: s
    for s in [
        Stock("small", "Small — date sticker", "Little sticker for dates",
              256, 200, 32.0, 25.0, gap_mm=2.0, density=9, speed=3),
        Stock("medium", "Medium — 3 × 2 inches", "Jars and small boxes",
              609, 400, 76.2, 50.8, face_h_mm=50.0),
        Stock("large", "Large — 4 × 2 inches", "Most food containers",
              812, 400, 101.6, 50.8, face_h_mm=50.0),
        Stock("round", "Round — 2 inch seal", "Round sticker for lids",
              406, 405, 50.8, 50.7, round=True, circle_dia=382, speed=3,
              zpl_lt=-3, zpl_md=8, zpl_pr=2),
        Stock("xl", "Extra-large — 4 × 6 inches", "Big boxes and bags",
              812, 1218, 101.6, 152.4),
    ]
}

DEFAULT_STOCK = "large"
ORDER = ["small", "medium", "large", "round", "xl"]


# Label sizes in dots per resolution. The 203 dpi numbers are the ones above;
# every row equals round(mm * dpi / 25.4) of the drawn size (the printed face,
# see Stock.face_h_mm), which tests/test_dpi.py checks, and the circle is the
# 203 dpi circle scaled. 3 x 2 and 4 x 2 were 406 rows (50.8 mm) before 1.3.1.
SIZES_DOTS = {
    203: {s.id: (s.w, s.h, s.circle_dia) for s in STOCKS.values()},
    300: {"small": (378, 295, 0), "medium": (900, 591, 0), "large": (1200, 591, 0),
          "round": (600, 599, 565), "xl": (1200, 1800, 0)},
}

_SCALED: dict[tuple[str, int], Stock] = {}


def check_dpi(dpi) -> int:
    """``dpi`` if it is a resolution Food Labeler lays out for, else ValueError."""
    if dpi not in SUPPORTED_DPI or isinstance(dpi, bool):
        raise ValueError(f"unsupported resolution {dpi!r}")
    return int(dpi)


def get(stock_id: str, dpi: int = BASE_DPI) -> Stock:
    """Stock by id at a printer resolution (203 or 300 dpi); unknown ids fall back
    to the default so old files still open."""
    base = STOCKS.get(stock_id) or STOCKS[DEFAULT_STOCK]
    if dpi == BASE_DPI:
        return base
    dpi = check_dpi(dpi)
    key = (base.id, dpi)
    if key not in _SCALED:
        w, h, dia = SIZES_DOTS[dpi][base.id]
        _SCALED[key] = replace(base, w=w, h=h, circle_dia=dia, dpi=dpi,
                               zpl_lt=dots(base.zpl_lt, dpi))
    return _SCALED[key]


# ---------------------------------------------------------------------------
# which way round: wide (landscape) or tall (portrait)
# ---------------------------------------------------------------------------

ORIENTATIONS = {"wide": "Wide", "tall": "Tall"}


def natural(stock: Stock) -> str:
    """How a label size is laid out unless the person turns it: "wide" when it is
    wider than tall on the roll (date stickers, 3 x 2, 4 x 2), "tall" otherwise
    (4 x 6). Round labels have no way round ("")."""
    if stock.round:
        return ""
    return "wide" if stock.w >= stock.h else "tall"


def turned(stock: Stock, orientation: str | None) -> bool:
    """True when ``orientation`` asks for the other way round than the roll's."""
    return bool(orientation) and orientation in ORIENTATIONS and not stock.round and \
        orientation != natural(stock)


_TURNED: dict[tuple[str, int], Stock] = {}


def rotated(stock: Stock) -> Stock:
    """The same label turned a quarter turn: what a "tall" design on a wide roll (or a
    "wide" one on a tall roll) is laid out on. Width and height swap; everything
    else (margins, resolution, printer defaults) is the label's own. Only used
    for laying out: the printer always gets the roll's own size (the drawing is
    turned back before printing, see render.render)."""
    key = (stock.id, stock.dpi)
    if key not in _TURNED:
        _TURNED[key] = replace(stock, w=stock.h, h=stock.w, w_mm=stock.drawn_h_mm,
                               h_mm=stock.w_mm, face_h_mm=0.0)
    return _TURNED[key]
