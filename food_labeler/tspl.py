"""TSPL job builder (the TSC label printer language, spoken by the LP610BT and clones).

A job is a short ASCII header (SIZE, GAP, DIRECTION, DENSITY, SPEED, CLS), one
BITMAP command carrying the whole label as packed 1-bit rows, then PRINT.
Lines end in CRLF. We always send the full label as one picture, so what the
preview shows is exactly what prints; no printer fonts are used.
"""
from __future__ import annotations

from PIL import Image

from .stocks import Stock

CRLF = b"\r\n"


def mm(v: float) -> str:
    """Up to one decimal, no trailing zeros: 101.6 -> '101.6', 32.0 -> '32'."""
    s = f"{round(float(v), 1):.1f}"
    return s[:-2] if s.endswith(".0") else s


def pack_bitmap(img: Image.Image, invert: bool = False) -> tuple[int, int, bytes]:
    """Pack a mode-1 image for TSPL BITMAP.

    TSPL: bit 1 = white (no burn), 0 = black. That is exactly PIL's mode-"1"
    raw bytes (MSB first, rows padded to whole bytes); pad bits past the right
    edge are forced to 1 (white). invert=True flips the polarity for clones
    that use 1 = black; pad bits are then 0.

    Returns (bytes per row, number of rows, packed data) — the width and
    height arguments of ``BITMAP x,y,width,height,mode,data``.
    """
    img = img.convert("1")
    w, h = img.size
    row_bytes = (w + 7) // 8
    raw = bytearray(img.tobytes())
    # Rows are padded to whole bytes. PIL leaves the pad bits (the low bits of
    # the last byte in each row) as 0, which TSPL would burn as a black stripe
    # down the right edge, so they must be set to "white" explicitly.
    pad = row_bytes * 8 - w
    pad_mask = (1 << pad) - 1 if pad else 0
    if invert:
        for i in range(len(raw)):
            raw[i] ^= 0xFF
    for r in range(h):
        i = r * row_bytes + row_bytes - 1
        if pad:
            if invert:
                raw[i] &= ~pad_mask & 0xFF
            else:
                raw[i] |= pad_mask
    return row_bytes, h, bytes(raw)


def header(stock: Stock, density: int | None = None, speed: int | None = None,
           gap_mm: float | None = None, media: str | None = None,
           offset_mm: float | None = None) -> bytes:
    """Setup commands for one label. None means "use the stock's default" (and,
    for media and offset, "send nothing", exactly as before they existed).

    density is clamped to TSPL's 0–15 and speed to 1–6. media: "gap" (GAP),
    "mark" (BLINE: black marks on the back) or "continuous" (GAP 0). offset_mm:
    extra feed after printing (OFFSET; 0 = stop at the tear bar).
    """
    d = stock.density if density is None else max(0, min(15, int(density)))
    s = stock.speed if speed is None else max(1, min(6, int(speed)))
    g = stock.gap_mm if gap_mm is None else float(gap_mm)
    if media == "mark":
        gapline = f"BLINE {mm(g)} mm,0 mm"
    elif media == "continuous":
        gapline = "GAP 0 mm,0 mm"
    else:
        gapline = f"GAP {mm(g)} mm,0 mm"
    lines = [
        f"SIZE {mm(stock.w_mm)} mm,{mm(stock.h_mm)} mm",
        gapline,
    ]
    if offset_mm is not None:
        lines.append(f"OFFSET {mm(max(0.0, min(10.0, float(offset_mm))))} mm")
    lines += [
        "DIRECTION 1,0",
        "REFERENCE 0,0",
        f"DENSITY {d}",
        f"SPEED {s}",
        "CLS",
    ]
    return b"".join(x.encode("ascii") + CRLF for x in lines)


def build_job(img: Image.Image, stock: Stock, copies: int = 1, density: int | None = None,
              speed: int | None = None, gap_mm: float | None = None,
              invert: bool = False, media: str | None = None,
              offset_mm: float | None = None) -> bytes:
    """Complete TSPL job printing ``img`` (stock.w x stock.h dots) ``copies`` times."""
    copies = max(1, min(200, int(copies)))
    row_bytes, h, data = pack_bitmap(img, invert)
    return (header(stock, density, speed, gap_mm, media, offset_mm)
            + f"BITMAP 0,0,{row_bytes},{h},0,".encode("ascii") + data + CRLF
            + f"PRINT {copies},1".encode("ascii") + CRLF)


def feed_job(stock: Stock, gap_mm: float | None = None, media: str | None = None) -> bytes:
    """Feed one blank label (FORMFEED). Only sent from its button."""
    return header(stock, gap_mm=gap_mm, media=media) + b"FORMFEED" + CRLF


def calibrate_job(stock: Stock, gap_mm: float | None = None) -> bytes:
    """GAPDETECT job: the printer feeds a few labels to measure label + gap.

    Only ever sent when the user presses "Feed / calibrate" (it uses up labels).
    """
    g = stock.gap_mm if gap_mm is None else float(gap_mm)
    lines = [f"SIZE {mm(stock.w_mm)} mm,{mm(stock.h_mm)} mm", f"GAP {mm(g)} mm,0 mm",
             "GAPDETECT"]
    return b"".join(x.encode("ascii") + CRLF for x in lines)
