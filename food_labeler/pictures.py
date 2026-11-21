"""Pictures on labels: open a picture file, keep it in the label, turn it into
black and white dots for a thermal printer, and the "My pictures" library.

A label's picture is a plain dict (``LabelDoc.picture``)::

    {"png": "<base64 PNG>", "name": "logo.png",
     "place": "above" | "left" | "right" | "corner" | "fill" | "fit",
     "size": 35,                        # % of the label's height (10..100)
     "mode": "logo" | "photo",          # solid black (threshold) or tiny dots (dither)
     "threshold": None | 1..254,        # logo: None = automatic (Otsu)
     "brightness": 0, "contrast": 0,    # photo: -100..100
     "invert": False,                   # swap black and white
     "remove_bg": False}                # near-white (and transparent) = paper

The PNG is the ORIGINAL picture (colour, with transparency), only made
smaller if it is bigger than MAX_STORED_SIDE, so a .label file carries its
picture with it and the conversion can be redone at any size and printer
resolution. ``to_print`` does the conversion at the final print size: the
picture is resized in greyscale with LANCZOS first and only then thresholded
or dithered, so thin lines survive.

Nothing here imports Tk.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import warnings
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

log = logging.getLogger("food_labeler.pictures")

MAX_FILE_BYTES = 25 * 1024 * 1024        # refuse picture files bigger than 25 MB
MAX_PIXELS = 40_000_000                  # ... or with more than 40 megapixels
MAX_STORED_SIDE = 2000                   # longest side kept in the .label file
OPEN_TYPES = [("Pictures", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("All files", "*")]
FORMATS = {"PNG", "JPEG", "GIF", "BMP", "WEBP", "MPO"}

PLACES = {
    "above": "Above the name",
    "left": "Left side",
    "right": "Right side",
    "corner": "Top-left corner",
    "corner_right": "Top-right corner",
    "fill": "Fill the label",
    "fit": "Fit inside",
}
# Which placements each kind of label offers (Picture label: the picture is the label).
PLACES_FOR_PICTURE_LABEL = ["fit", "fill"]
PLACES_FOR_OTHERS = ["above", "left", "right", "corner"]
MODES = {"logo": "Logo / drawing (solid black)", "photo": "Photo (tiny dots)"}
SIZE_RANGE = (10, 100)
DEFAULTS = {"png": "", "name": "", "place": "above", "size": 35, "mode": "logo",
            "threshold": None, "brightness": 0, "contrast": 0, "invert": False,
            "remove_bg": False}
NEAR_WHITE = 235                         # "Remove the background": this light = paper

LIBRARY_DIR = "pictures"                 # <data dir>/pictures: My pictures
LIBRARY_INDEX = "pictures.json"


class PictureError(Exception):
    """A picture couldn't be used. The message is friendly."""


# ---------------------------------------------------------------------------
# reading picture files
# ---------------------------------------------------------------------------

def _too_big() -> PictureError:
    return PictureError("This picture is too big for Food Labeler (over 25 MB or 40 "
                        "megapixels). Please make it smaller first, or use a smaller copy "
                        "of it, like the one you would send by email.")


def normalise(im: Image.Image) -> Image.Image:
    """Any picture -> "RGBA" (if it has transparency), "RGB" or "L", 8 bits per channel.

    Handles EXIF rotation (phone photos), the first frame of animations,
    palette and CMYK pictures and 16-bit or floating point greyscale.
    """
    try:
        im.seek(0)                                   # animated GIF/WebP: first frame
    except (EOFError, AttributeError, ValueError):
        pass
    im = ImageOps.exif_transpose(im)
    mode = im.mode
    if mode in ("I;16", "I;16B", "I;16L", "I;16N", "I", "F"):
        im = im.convert("F") if mode == "F" else im.convert("I")
        lo, hi = im.getextrema()
        if mode != "F" and hi <= 255 and lo >= 0:
            scale, off = 1.0, 0.0
        else:
            span = float(hi - lo) or 1.0
            scale, off = 255.0 / span, -lo * 255.0 / span
        return im.point(lambda v: v * scale + off).convert("L")
    if mode == "1":
        return im.convert("L")
    if mode == "L":
        return im
    if mode in ("LA", "PA", "RGBA", "La", "RGBa") or (mode == "P" and "transparency" in im.info):
        return im.convert("RGBA")
    if mode == "P" or mode == "RGB":
        return im.convert("RGB")
    if mode == "CMYK":
        return im.convert("RGB")
    return im.convert("RGB")


def open_bytes(data: bytes) -> Image.Image:
    """Open and normalise picture bytes, enforcing the size limits."""
    if len(data) > MAX_FILE_BYTES:
        raise _too_big()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data))
            if im.width * im.height > MAX_PIXELS:
                raise _too_big()
            im.load()
            return normalise(im)
    except PictureError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _too_big() from None
    except Exception:  # noqa: BLE001 - any decoder problem means "not a picture we can use"
        log.exception("picture unreadable")
        raise PictureError("Food Labeler can't read this picture. Please use a PNG, JPG, "
                           "GIF, BMP or WebP picture.") from None


def read_file(path) -> tuple[Image.Image, str]:
    """Open a picture file for a label. Returns (normalised picture, file name)."""
    path = Path(path)
    try:
        size = os.path.getsize(path)
    except OSError:
        raise PictureError("That picture file couldn't be opened.") from None
    if size > MAX_FILE_BYTES:
        raise _too_big()
    try:
        data = path.read_bytes()
    except OSError:
        raise PictureError("That picture file couldn't be opened.") from None
    return open_bytes(data), path.name


def shrink_for_storing(im: Image.Image) -> Image.Image:
    """Make a picture no bigger than MAX_STORED_SIDE on its longest side."""
    side = max(im.size)
    if side <= MAX_STORED_SIDE:
        return im
    k = MAX_STORED_SIDE / side
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def encode(im: Image.Image) -> str:
    """Picture -> base64 PNG text for the .label file."""
    buf = io.BytesIO()
    shrink_for_storing(im).save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def new_picture(im: Image.Image, name: str = "", **settings) -> dict:
    """A label picture dict for a normalised picture, with default settings."""
    pic = dict(DEFAULTS, png=encode(im), name=str(name)[:120])
    pic.update(settings)
    return clean(pic) or {}


# ---------------------------------------------------------------------------
# the dict in .label files
# ---------------------------------------------------------------------------

_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _int(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return max(lo, min(hi, int(round(v))))


def clean(value) -> dict | None:
    """A valid picture dict, or None (no picture / not usable). Never raises."""
    if not isinstance(value, dict):
        return None
    png = value.get("png")
    if not isinstance(png, str) or not png or not _B64_RE.match(png[:200]):
        return None
    out = {"png": png, "name": str(value.get("name") or "")[:120]}
    place = value.get("place")
    out["place"] = place if place in PLACES else DEFAULTS["place"]
    out["size"] = _int(value.get("size"), *SIZE_RANGE, DEFAULTS["size"])
    out["mode"] = value.get("mode") if value.get("mode") in MODES else "logo"
    t = value.get("threshold")
    out["threshold"] = None if t is None else _int(t, 1, 254, None)
    out["brightness"] = _int(value.get("brightness"), -100, 100, 0)
    out["contrast"] = _int(value.get("contrast"), -100, 100, 0)
    out["invert"] = bool(value.get("invert"))
    out["remove_bg"] = bool(value.get("remove_bg"))
    return out


_DIGESTS: dict[int, tuple[str, str]] = {}


def digest(pic: dict) -> str:
    """Short id of the picture data (same picture = same id). Remembered per string
    object, because pictures can be megabytes and the label is redrawn often."""
    png = pic["png"]
    hit = _DIGESTS.get(id(png))
    if hit is not None and hit[0] is png:
        return hit[1]
    d = hashlib.sha256(png.encode("ascii")).hexdigest()[:24]
    if len(_DIGESTS) > 32:
        _DIGESTS.clear()
    _DIGESTS[id(png)] = (png, d)
    return d


_DECODED: dict[str, Image.Image] = {}


def decode(pic: dict) -> Image.Image | None:
    """The stored picture (cached), or None if the data is damaged."""
    key = digest(pic)
    im = _DECODED.get(key)
    if im is None:
        try:
            im = open_bytes(base64.b64decode(pic["png"], validate=False))
        except (PictureError, ValueError):
            log.warning("picture data in label unreadable")
            return None
        if len(_DECODED) > 8:
            _DECODED.clear()
        _DECODED[key] = im
    return im


# ---------------------------------------------------------------------------
# colour -> black and white
# ---------------------------------------------------------------------------

def otsu(grey: Image.Image, mask: Image.Image | None = None) -> int:
    """Otsu's threshold of a greyscale picture (only where mask is set)."""
    hist = grey.histogram(mask)[:256]
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * h for i, h in enumerate(hist))
    best, best_t = -1.0, 128
    w0 = s0 = 0
    for t in range(256):
        w0 += hist[t]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        s0 += t * hist[t]
        m0, m1 = s0 / w0, (sum_all - s0) / w1
        between = w0 * w1 * (m0 - m1) ** 2
        if between > best:
            best, best_t = between, t
    # pixels <= t are one class; we print black where grey < threshold
    return max(1, min(254, best_t + 1))


def _grey_and_alpha(im: Image.Image, w: int, h: int) -> tuple[Image.Image, Image.Image]:
    """Resize to w x h in greyscale (LANCZOS) over white; also the alpha mask."""
    if im.mode == "RGBA":
        # premultiply over white so edges of transparent logos don't go dark
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        flat = Image.alpha_composite(white, im).convert("L")
        alpha = im.getchannel("A")
    else:
        flat = im.convert("L")
        alpha = Image.new("L", im.size, 255)
    return flat.resize((w, h), Image.LANCZOS), alpha.resize((w, h), Image.LANCZOS)


def auto_threshold(pic: dict, w: int = 400, h: int | None = None) -> int:
    """The automatic Lighter/Darker setting for a picture (Otsu on its greyscale)."""
    im = decode(pic)
    if im is None:
        return 128
    if h is None:
        h = max(1, round(w * im.height / im.width))
    grey, alpha = _grey_and_alpha(im, w, h)
    if pic.get("invert"):
        grey = ImageOps.invert(grey)
    return otsu(grey)


def _key(pic: dict) -> tuple:
    return (digest(pic), pic.get("mode"), pic.get("threshold"), pic.get("brightness"),
            pic.get("contrast"), bool(pic.get("invert")), bool(pic.get("remove_bg")))


_PRINTED: dict[tuple, Image.Image] = {}


def to_print(pic: dict, w: int, h: int) -> Image.Image:
    """The picture as printer dots: a mode "1" image of exactly w x h (1 = white).

    Cached: the same picture, settings and size give the same (shared, never
    modified) picture."""
    w, h = max(1, int(w)), max(1, int(h))
    key = (_key(pic), w, h)
    out = _PRINTED.get(key)
    if out is None:
        out = _convert(pic, w, h)
        if len(_PRINTED) > 24:
            _PRINTED.clear()
        _PRINTED[key] = out
    return out


def _convert(pic: dict, w: int, h: int) -> Image.Image:
    im = decode(pic)
    if im is None:
        return Image.new("1", (w, h), 1)
    grey, alpha = _grey_and_alpha(im, w, h)
    paper = alpha.point(lambda a: 255 if a < 128 else 0)       # transparent = paper
    if pic.get("remove_bg"):
        near = grey.point(lambda v: 255 if v >= NEAR_WHITE else 0)
        paper = Image.composite(Image.new("L", grey.size, 255), paper, near)
    if pic.get("invert"):
        grey = ImageOps.invert(grey)
    if pic.get("mode") == "photo":
        b, c = pic.get("brightness", 0), pic.get("contrast", 0)
        if b:
            grey = ImageEnhance.Brightness(grey).enhance(1.0 + b / 100.0)
        if c:
            grey = ImageEnhance.Contrast(grey).enhance(1.0 + c / 100.0)
        out = grey.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        t = pic.get("threshold")
        if t is None:
            # over the whole picture, transparent parts counting as white paper,
            # so a coloured logo on a see-through background turns solid black
            t = otsu(grey)
        out = grey.point(lambda v: 255 if v >= t else 0).convert("1", dither=Image.Dither.NONE)
    white = Image.new("1", (w, h), 1)
    return Image.composite(white, out, paper.convert("1", dither=Image.Dither.NONE))


def aspect(pic: dict) -> float:
    """Width / height of the stored picture (1.0 if unreadable)."""
    im = decode(pic)
    return im.width / im.height if im is not None and im.height else 1.0


# ---------------------------------------------------------------------------
# My pictures (kept in the data folder, survives updates)
# ---------------------------------------------------------------------------

class Library:
    """<data dir>/pictures/: one PNG per picture plus pictures.json with names.

    Pictures are stored as the same PNG that goes into labels, so choosing one
    from the library is one click and gives exactly the same label.
    """

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / LIBRARY_DIR
        self.index_path = self.dir / LIBRARY_INDEX

    def _read(self) -> list[dict]:
        try:
            from .model import MAX_SETTINGS_BYTES, read_text_limited
            got = json.loads(read_text_limited(self.index_path, MAX_SETTINGS_BYTES))
            items = got.get("pictures") if isinstance(got, dict) else None
            return [x for x in items or [] if isinstance(x, dict) and x.get("file")]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, RecursionError):
            log.exception("My pictures list unreadable")
            return []

    def _write(self, items: list[dict]) -> None:
        from .model import atomic_write_text
        atomic_write_text(self.index_path, json.dumps(
            {"format": "food-labeler-pictures", "version": 1, "pictures": items}, indent=1,
            ensure_ascii=False))

    def items(self) -> list[dict]:
        """[{"id", "name", "file"}] for pictures whose file is still there."""
        return [x for x in self._read() if (self.dir / x["file"]).is_file()]

    def add(self, pic: dict, name: str = "") -> str:
        """Keep a label picture in My pictures (no duplicates). Returns its id."""
        pid = digest(pic)
        items = self._read()
        if any(x.get("id") == pid for x in items):
            return pid
        self.dir.mkdir(parents=True, exist_ok=True)
        f = self.dir / f"{pid}.png"
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(base64.b64decode(pic["png"]))
        os.replace(tmp, f)
        items.append({"id": pid, "name": (name or pic.get("name") or "My picture")[:120],
                      "file": f.name})
        self._write(items)
        return pid

    def load(self, pid: str) -> tuple[Image.Image, str]:
        """(picture, name) of a library picture."""
        for x in self._read():
            if x.get("id") == pid:
                return open_bytes((self.dir / x["file"]).read_bytes()), x.get("name", "")
        raise PictureError("That picture isn't in My pictures any more.")

    def remove(self, pid: str) -> None:
        """Take a picture out of My pictures (labels that use it keep their copy)."""
        items = self._read()
        keep = [x for x in items if x.get("id") != pid]
        for x in items:
            if x.get("id") == pid:
                try:
                    (self.dir / x["file"]).unlink()
                except OSError:
                    pass
        self._write(keep)
