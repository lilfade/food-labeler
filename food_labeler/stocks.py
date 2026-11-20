"""Label stocks (roll sizes). All sizes are at 203 dpi = 8 dots per mm.

A Stock is the physical label: its size in dots (what we render) and in mm
(what TSPL's SIZE/GAP want), plus per-size printer defaults. The ids
(small, medium, large, round, xl) are stored in .label files, settings and
printer definition files, so they must never change.
"""
from __future__ import annotations

from dataclasses import dataclass

DPI = 203
DOTS_PER_MM = 8


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

    @property
    def margin(self) -> int:
        """Blank border in dots kept clear on rectangular labels."""
        return 12 if self.w < 400 else 24

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


def get(stock_id: str) -> Stock:
    """Stock by id; unknown ids fall back to the default so old files still open."""
    return STOCKS.get(stock_id) or STOCKS[DEFAULT_STOCK]
