"""ZPL (Zebra) job builder.

Like TSPL, the whole label is sent as one picture: a ``^GFA`` (graphic field,
ASCII hex) at 0,0 inside ``^XA … ^XZ``, with ``^PW``/``^LL`` set to the label
size, ``^MD`` darkness, ``^PR`` speed and ``^PQ`` copies. ``decode_gfa`` turns
a job back into a picture so tests and ``--selftest`` can check the round trip.
"""
from __future__ import annotations

from PIL import Image

from .stocks import Stock


def pack_gfa(img: Image.Image) -> tuple[int, int, str]:
    """Return (total bytes, row bytes, HEX). ZPL: bit 1 = burn (black).

    PIL mode-1 bytes have 1 = white, so XOR 0xFF; pad bits past the right edge
    are masked to 0 (no burn).
    """
    img = img.convert("1")
    w, h = img.size
    row_bytes = (w + 7) // 8
    # Opposite polarity to TSPL: flip every bit so 1 means "burn".
    raw = bytearray(b ^ 0xFF for b in img.tobytes())
    pad = row_bytes * 8 - w
    if pad:
        # The XOR turned PIL's 0 pad bits into 1s (= black); keep only the
        # real pixel bits (the high bits) of the last byte in every row.
        keep = (0xFF << pad) & 0xFF
        for r in range(h):
            raw[r * row_bytes + row_bytes - 1] &= keep
    return len(raw), row_bytes, raw.hex().upper()


def build_job(img: Image.Image, stock: Stock, copies: int = 1, darkness: int | None = None,
              speed: int | None = None, media: str | None = None,
              tear_dots: int | None = None) -> bytes:
    """Complete ZPL job. darkness/speed None = the stock's ^MD/^PR defaults.

    media: ^MN W (gaps), M (black marks) or N (continuous); tear_dots: ^TA
    tear-off adjustment. None = not sent (as before they existed). ^MD is
    clamped to -30..30 and ^PR to 2..6 (Zebra's ranges)."""
    copies = max(1, min(200, int(copies)))
    md = stock.zpl_md if darkness is None else max(-30, min(30, int(darkness)))
    pr = stock.zpl_pr if speed is None else max(2, min(6, int(speed)))
    total, row_bytes, hx = pack_gfa(img)
    w, h = img.size
    extra = ""
    if media in ("W", "M", "N"):
        extra += f"^MN{media}\n"
    if tear_dots is not None:
        extra += f"^TA{max(-120, min(120, int(tear_dots))):03d}\n"
    job = (f"^XA\n^CI28\n^PW{w}\n^LL{h}\n^LH0,0\n^LT{stock.zpl_lt}\n^MD{md}\n^PR{pr}\n"
           f"{extra}"
           f"^FO0,0^GFA,{total},{total},{row_bytes},{hx}^FS\n"
           f"^PQ{copies},0,0,N\n^XZ\n")
    return job.encode("ascii")


def feed_job() -> bytes:
    """Feed one blank label (~PH). Only sent from its button."""
    return b"~PH\n"


def calibrate_job(stock: Stock, media: str | None = None) -> bytes:
    """Set-up job for a new roll.

    Gaps (default) / black marks: set the media type (^MNW / ^MNM) and then
    ~JC, which makes the printer feed labels to measure them (the head must be
    closed with the roll loaded). Continuous (^MNN): nothing to measure, so
    only the label length is set (^PW/^LL). ^JUS is never sent, so nothing is
    saved in the printer for good. Only sent from a button after the person
    has said yes (calibrate.send_setup).
    """
    if media == "continuous":
        return f"^XA^MNN^PW{stock.w}^LL{stock.h}^XZ\n".encode("ascii")
    mn = "M" if media == "mark" else "W"
    return f"^XA^MN{mn}^XZ\n~JC\n".encode("ascii")


def decode_gfa(job: bytes) -> Image.Image:
    """Turn a ^GFA job back into a picture (used by the tests and --selftest).

    The result is row_bytes * 8 wide, i.e. it includes the pad bits; crop it
    to the stock width before comparing.
    """
    s = job.decode("ascii")
    a = s.index("^GFA,") + 5
    b = s.index("^FS", a)
    total, _, row_bytes, hx = s[a:b].split(",", 3)
    row_bytes, total = int(row_bytes), int(total)
    data = bytes.fromhex(hx)
    assert len(data) == total
    h = total // row_bytes
    w = row_bytes * 8
    inv = bytes(x ^ 0xFF for x in data)
    return Image.frombytes("1", (w, h), inv)
