"""Pictures on labels: open a picture file, keep it in the label, turn it into
black and white dots for a thermal printer, and the "My pictures" library.

A label's picture is a plain dict (``LabelDoc.picture``)::

    {"png": "<base64 PNG>", "name": "logo.png",
     "place": "above" | "bottom" | "left" | "right" | "corner" | "corner_right"
              | "corner_bottom_left" | "corner_bottom_right" | "fill" | "fit",
     "size": 35,                        # % of the label's height (10..100)
     "mode": "logo" | "photo",          # solid black (threshold) or tiny dots (dither)
     "threshold": None | 1..254,        # logo: None = automatic (Otsu)
     "brightness": 0, "contrast": 0,    # photo: -100..100
     "invert": False,                   # swap black and white
     "remove_bg": False}                # near-white (and transparent) = paper

The PNG is the original picture in greyscale (with its transparency, or as
exact black and white dots if that is all it has), only made smaller if it is
bigger than MAX_STORED_SIDE (see ``for_storing``), so a .label file carries
its picture with it and the conversion can be redone at any size and printer
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
# Longest side kept in the .label file. Labels print in black and white, so the
# picture is kept in greyscale (with its see-through parts, if it has any) and no
# bigger than a 4 x 6 inch label at 300 dpi really needs: a 12 megapixel phone
# photo goes in at about 1 MB instead of 6 MB. A plain black-and-white picture
# (such as a label saved with "Save as picture") is kept as exact black and
# white dots, which is tiny, so it can stay sharper.
MAX_STORED_SIDE = 1600
MAX_STORED_SIDE_BW = 3600
# What the file picker offers: every kind of picture Food Labeler reads.
OPEN_TYPES = [
    ("All pictures", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff *.ico"),
    ("PNG pictures", "*.png"),
    ("JPG photos", "*.jpg *.jpeg"),
    ("GIF pictures", "*.gif"),
    ("BMP pictures", "*.bmp"),
    ("WebP pictures", "*.webp"),
    ("TIFF pictures", "*.tif *.tiff"),
    ("Icons", "*.ico"),
    ("All files", "*"),
]
FORMATS = {"PNG", "JPEG", "GIF", "BMP", "WEBP", "MPO", "TIFF", "ICO"}
# Kinds of picture Pillow can't read without extra parts we don't ship.
NOT_SUPPORTED_EXT = {".heic": "iPhone photos (HEIC)", ".heif": "iPhone photos (HEIC)",
                     ".avif": "AVIF pictures", ".svg": "SVG drawings",
                     ".svgz": "SVG drawings"}
NOT_SUPPORTED = ("Food Labeler can't open {what} yet. Please save it as PNG or JPG first "
                 "(most photo and drawing programs can do this with “Save as” or "
                 "“Export”), then open that.")

PLACES = {
    "above": "Above the name",
    "left": "Left side",
    "right": "Right side",
    "corner": "Top-left corner",
    "corner_right": "Top-right corner",
    "bottom": "Below the writing",
    "corner_bottom_left": "Bottom-left corner",
    "corner_bottom_right": "Bottom-right corner",
    "fill": "Fill the label",
    "fit": "Fit inside",
}
# Which placements each kind of label offers (Picture label: the picture is the label).
PLACES_FOR_PICTURE_LABEL = ["fit", "fill"]
PLACES_FOR_OTHERS = ["above", "bottom", "left", "right", "corner", "corner_right",
                     "corner_bottom_left", "corner_bottom_right"]
# Round labels: only across the top or the bottom of the circle.
PLACES_ON_ROUND = ["above", "bottom"]
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
    palette and CMYK pictures, 16-bit or floating point greyscale, and the
    see-through colour some PNG, GIF and BMP files name instead of having an
    alpha channel (greyscale and colour pictures too, not only palette ones).
    Black stays black: nothing here ever swaps light and dark.
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
    see_through = "transparency" in im.info
    if mode in ("1", "L") and not see_through:
        return im.convert("L")
    if mode in ("LA", "PA", "RGBA", "La", "RGBa") or see_through:
        # "1"/"L"/"RGB"/"P" with a see-through colour: Pillow turns that colour
        # into alpha when converting to RGBA
        return im.convert("RGBA")
    return im.convert("RGB")


def _not_supported(data: bytes) -> str:
    """What kind of unsupported picture this is ("" if it isn't one we know)."""
    head = data[:64]
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return "iPhone photos (HEIC)"
        if brand in (b"avif", b"avis"):
            return "AVIF pictures"
    text = data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in text):
        return "SVG drawings"
    return ""


def open_bytes(data: bytes) -> Image.Image:
    """Open and normalise picture bytes, enforcing the size limits."""
    if len(data) > MAX_FILE_BYTES:
        raise _too_big()
    what = _not_supported(data)
    if what:
        raise PictureError(NOT_SUPPORTED.format(what=what))
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
                           "GIF, BMP, WebP or TIFF picture.") from None


def read_file(path) -> tuple[Image.Image, str]:
    """Open a picture file for a label. Returns (normalised picture, file name)."""
    path = Path(path)
    what = NOT_SUPPORTED_EXT.get(path.suffix.lower())
    if what:
        raise PictureError(NOT_SUPPORTED.format(what=what))
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


def _two_tone(im: Image.Image) -> bool:
    """Only pure black and pure white pixels (a label saved as a picture, a scan)."""
    if im.mode != "L":
        return False
    hist = im.histogram()
    return sum(hist[1:255]) == 0


def for_storing(im: Image.Image) -> Image.Image:
    """The picture as it is kept in the .label file: as small as it can be without
    changing what prints.

    * greyscale ("L"), because labels print in black and white; the print
      conversion turns colour into the same greys (``Image.convert("L")``);
    * with its alpha channel ("LA") only if some of it is see-through;
    * exact black and white dots ("1") if it has nothing else, which keeps a
      label saved with "Save as picture" tiny and exact;
    * no longer than MAX_STORED_SIDE (MAX_STORED_SIDE_BW for black and white),
      never made bigger.
    """
    if im.mode not in ("L", "RGB", "RGBA"):
        im = normalise(im)
    alpha = None
    if im.mode == "RGBA":
        a = im.getchannel("A")
        if a.getextrema()[0] < 255:
            alpha = a
        grey = im.convert("RGB").convert("L")
    else:
        grey = im.convert("L")
    bw = alpha is None and _two_tone(grey)
    side = max(grey.size)
    cap = MAX_STORED_SIDE_BW if bw else MAX_STORED_SIDE
    if side > cap:
        k = cap / side
        size = (max(1, round(grey.width * k)), max(1, round(grey.height * k)))
        grey = grey.resize(size, Image.LANCZOS)
        if alpha is not None:
            alpha = alpha.resize(size, Image.LANCZOS)
        if bw:
            # shrinking makes greys at the edges; keep it black and white the way
            # the print conversion would (half way)
            grey = grey.point(lambda v: 255 if v >= 128 else 0)
    if alpha is not None:
        return Image.merge("LA", (grey, alpha))
    if bw:
        return grey.convert("1", dither=Image.Dither.NONE)
    return grey


def encode(im: Image.Image) -> str:
    """Picture -> base64 PNG text for the .label file (see for_storing)."""
    buf = io.BytesIO()
    for_storing(im).save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def new_picture(im: Image.Image, name: str = "", **settings) -> dict:
    """A label picture dict for a normalised picture, with default settings."""
    pic = dict(DEFAULTS, png=encode(im), name=str(name)[:120])
    pic.update(settings)
    return clean(pic) or {}


_COMPACT: dict[str, str] = {}


def compact(pic: dict | None) -> dict | None:
    """A picture from an older file, stored the small way (see for_storing).

    Files made before 1.5.0 kept pictures in colour and up to 2000 pixels, which
    could make a .label file several megabytes. They still open as they are;
    this gives the same picture in greyscale (and smaller, if it was bigger
    than MAX_STORED_SIDE), so the next save is small. Pictures already stored
    the small way are returned unchanged. Remembered per picture, because
    labels are reloaded on every undo."""
    if not pic or not pic.get("png"):
        return pic
    key = digest(pic)
    hit = _COMPACT.get(key)
    if hit is None:
        hit = pic["png"]
        try:
            raw = base64.b64decode(pic["png"], validate=False)
            with Image.open(io.BytesIO(raw)) as im:
                mode, side = im.mode, max(im.size)
            if mode in ("RGB", "RGBA", "P", "PA", "CMYK") or side > MAX_STORED_SIDE_BW or (
                    mode not in ("1",) and side > MAX_STORED_SIDE):
                im2 = decode(pic)
                if im2 is not None:
                    smaller = encode(im2)
                    if len(smaller) < len(pic["png"]):
                        hit = smaller
        except Exception:  # noqa: BLE001 - leave anything odd exactly as it was
            log.warning("could not make an older picture smaller")
        if len(_COMPACT) > 32:
            _COMPACT.clear()
        _COMPACT[key] = hit
    return pic if hit is pic["png"] else dict(pic, png=hit)


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
    elif _light_shape(grey, alpha):
        return 254                         # the slider's darkest end (see _light_shape)
    return otsu(grey)


def _light_shape(grey: Image.Image, alpha: Image.Image) -> bool:
    """A white or very light logo on a see-through background.

    Over white paper it would disappear, so its shape prints in black instead
    (the see-through part stays paper). Only when the solid part is all about
    the same light shade: a logo with dark parts, or light lettering inside a
    dark shape, is turned into black and white as usual."""
    solid = alpha.point(lambda a: 255 if a >= 128 else 0)
    n_solid = solid.histogram()[255]
    if n_solid == 0 or n_solid == alpha.width * alpha.height:
        return False                       # nothing see-through (or nothing solid)
    hist = grey.histogram(solid)[:256]
    total = sum(hist)
    lo = hi = None
    seen = 0
    for v, c in enumerate(hist):           # the middle 90 % of the solid part
        seen += c
        if lo is None and seen >= total * 0.05:
            lo = v
        if seen >= total * 0.95:
            hi = v
            break
    return lo is not None and hi is not None and lo >= 200 and hi - lo <= 40


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
        if t is None and not pic.get("invert") and _light_shape(grey, alpha):
            t = 256                            # a white logo: its shape prints black
        elif t is None:
            # over the whole picture, transparent parts counting as white paper,
            # so a coloured logo on a see-through background turns solid black
            t = otsu(grey)
        # dark (below t) = black, light = paper; never the other way round
        out = grey.point(lambda v: 255 if v >= t else 0).convert("1", dither=Image.Dither.NONE)
    white = Image.new("1", (w, h), 1)
    return Image.composite(white, out, paper.convert("1", dither=Image.Dither.NONE))


# ---------------------------------------------------------------------------
# "This picture will print mostly black" (the Picture window only; nothing
# here changes what prints)
# ---------------------------------------------------------------------------

MOSTLY_BLACK = 0.65          # share of black dots above which the window warns


def black_share(dots: Image.Image) -> float:
    """The share (0..1) of a converted picture's dots that print black."""
    grey = dots.convert("L")
    n = grey.width * grey.height
    if not n:
        return 0.0
    return sum(grey.histogram()[:128]) / n


def mostly_black_warning(share: float, mode: str = "logo", invert: bool = False) -> str:
    """The gentle line under the Picture window's preview when more than
    MOSTLY_BLACK of the picture prints black ("" when it doesn't)."""
    if share <= MOSTLY_BLACK:
        return ""
    if mode == "photo":
        tip = ("This picture will print mostly black. Try moving the slider toward "
               "Brighter.")
    else:
        tip = ("This picture will print mostly black. Try moving the slider toward "
               "Lighter, or choose Photo (tiny dots).")
    if invert:
        return "\u201cSwap black and white\u201d is on: try turning it off first. " + tip
    return tip


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

    def _file(self, x: dict) -> Path | None:
        """The picture file of a pictures.json entry, always inside My pictures.

        pictures.json is only a list we wrote ourselves, but it is a file
        anyone could edit: only the bare file name is used, so an entry can
        never point at (and remove or read) a file somewhere else."""
        name = Path(str(x.get("file") or "")).name
        if name in ("", ".", "..") or "\x00" in name or "\\" in name:
            return None
        return self.dir / name

    def _write(self, items: list[dict]) -> None:
        from .model import atomic_write_text
        atomic_write_text(self.index_path, json.dumps(
            {"format": "food-labeler-pictures", "version": 1, "pictures": items}, indent=1,
            ensure_ascii=False))

    def items(self) -> list[dict]:
        """[{"id", "name", "file"}] for pictures whose file is still there."""
        return [x for x in self._read() if (f := self._file(x)) is not None and f.is_file()]

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
            if x.get("id") == pid and (f := self._file(x)) is not None:
                try:
                    if f.stat().st_size > MAX_FILE_BYTES:
                        raise _too_big()
                    data = f.read_bytes()
                except OSError:
                    break
                return open_bytes(data), x.get("name", "")
        raise PictureError("That picture isn't in My pictures any more.")

    def remove(self, pid: str) -> None:
        """Take a picture out of My pictures (labels that use it keep their copy)."""
        items = self._read()
        keep = [x for x in items if x.get("id") != pid]
        for x in items:
            f = self._file(x) if x.get("id") == pid else None
            if f is not None:
                try:
                    f.unlink()
                except OSError:
                    pass
        self._write(keep)
