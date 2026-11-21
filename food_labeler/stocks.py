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
              609, 406, 76.2, 50.8),
        Stock("large", "Large — 4 × 2 inches", "Most food containers",
              812, 406, 101.6, 50.8),
        Stock("round", "Round — 2 inch seal", "Round sticker for lids",
              406, 405, 50.8, 50.7, round=True, circle_dia=382, speed=3,
              zpl_lt=-3, zpl_md=8, zpl_pr=2),
        Stock("xl", "Extra-large — 4 × 6 inches", "Big boxes and bags",
              812, 1218, 101.6, 152.4),
    ]
}

DEFAULT_STOCK = "large"
ORDER = ["small", "medium", "large", "round", "xl"]


# Label sizes in dots per resolution. The 203 dpi numbers are the ones above
# (unchanged since 1.0.0); every row equals round(mm * dpi / 25.4), which
# tests/test_dpi.py checks, and the circle is the 203 dpi circle scaled.
SIZES_DOTS = {
    203: {s.id: (s.w, s.h, s.circle_dia) for s in STOCKS.values()},
    300: {"small": (378, 295, 0), "medium": (900, 600, 0), "large": (1200, 600, 0),
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
