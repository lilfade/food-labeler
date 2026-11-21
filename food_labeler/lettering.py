"""Lettering: the fonts a label can be printed in.

A *face* is one font family with a regular and (if it has one) a bold style.
The registry holds the fonts bundled with the program (``BUNDLED``, files in
``food_labeler/fonts``) plus the ones the user added with *Get more fonts…*
or *Add a font file from my computer…*, which live in ``<data folder>/fonts``
so program updates never touch them (see ``fontget``).

Each label has two lettering choices, stored in the ``.label`` file as
``{"lettering": {"name": "<family>", "other": "<family>"}}`` (both optional):

* ``name``  — the big line: name of the food (product, lot or free text).
  Any font may be used.
* ``other`` — everything else. Only easy-to-read sans fonts (``readable``).

Required wording (ingredients, allergens, address, the state's statements…,
``LEGAL_KEYS``) is always drawn in a readable sans: ``apply()`` enforces that
whatever the file says, so a hand-edited or newer file can never put the law
in a script font.

Script and display fonts look smaller than DejaVu Sans at the same size and
fall apart sooner on a 203 dpi printer, so every face has ``min_scale``: the
template's minimum size is multiplied by it, and auto-shrink stops there.

A family that a label asks for but this computer doesn't have is drawn in
the standard lettering (DejaVu Sans); ``missing()`` names it so the window
can say so.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import values

log = logging.getLogger("food_labeler.lettering")

FONT_DIR = Path(__file__).resolve().parent / "fonts"
DEFAULT = "DejaVu Sans"
USER_DIR_NAME = "fonts"
MANIFEST = "font.json"
MANIFEST_FORMAT = "food-labeler-font"

# Which block is "the name of the food" on each kind of label.
NAME_KEYS = {"simple": "food", "package": "product", "cottage": "product",
             "sticker": "lot", "free": "text", "picture": "text"}
# What the two choices are called on each kind of label (plain words).
ROLE_TITLES = {
    "simple": ("Name of the food", "Everything else"),
    "package": ("Name of the food", "Everything else"),
    "cottage": ("Name of the food", "Everything else"),
    "sticker": ("Lot number", "Everything else"),
    "free": ("Your words", None),
    "picture": ("Words under the picture", None),
}
# Wording the law asks for: always a readable sans, never a script/display font.
LEGAL_KEYS = {"ingredients", "contains", "cross_contact", "address", "business", "brand",
              "produced", "contact", "permit", "net", "disclaimer", "storage", "dates"}
LEGAL_PREFIXES = ("statement:",)

# How much bigger than the template minimum a font may get by category, for
# fonts we didn't measure ourselves (user fonts).
_CATEGORY_SCALE = {"SANS_SERIF": 1.0, "SERIF": 1.05, "MONOSPACE": 1.0, "DISPLAY": 1.15,
                   "HANDWRITING": 1.3}
_REF_X_HEIGHT = 55     # DejaVu Sans' x-height at size 100


@dataclass(frozen=True)
class Face:
    """One font family as the label engine uses it."""
    name: str                   # family name, shown to the user and stored in .label files
    regular: str                # file path
    bold: str = ""              # file path; "" = none (variable fonts use their wght axis)
    variable: bool = False      # has a weight axis: regular = 400, bold = 700
    readable: bool = False      # allowed for "Everything else" and required wording
    min_scale: float = 1.0      # multiply the template's minimum sizes by this
    bundled: bool = True
    license: str = ""
    category: str = ""
    folder: str = ""            # user fonts: their folder (for Remove)

    @property
    def key(self) -> str:
        return self.name.casefold()

    @property
    def has_bold(self) -> bool:
        return bool(self.bold) or self.variable


def _b(*parts) -> str:
    return str(FONT_DIR.joinpath(*parts))


# The bundled fonts. To add one, see CONTRIBUTING.md ("Adding a bundled font").
BUNDLED = [
    Face("DejaVu Sans", _b("DejaVuSans.ttf"), _b("DejaVuSans-Bold.ttf"), readable=True,
         license="Bitstream Vera / DejaVu", category="SANS_SERIF"),
    Face("Atkinson Hyperlegible", _b("atkinsonhyperlegible", "AtkinsonHyperlegible-Regular.ttf"),
         _b("atkinsonhyperlegible", "AtkinsonHyperlegible-Bold.ttf"), readable=True,
         min_scale=1.1, license="OFL-1.1", category="SANS_SERIF"),
    Face("Roboto", _b("roboto", "Roboto[wdth,wght].ttf"), variable=True, readable=True,
         min_scale=1.05, license="OFL-1.1", category="SANS_SERIF"),
    Face("Open Sans", _b("opensans", "OpenSans[wdth,wght].ttf"), variable=True, readable=True,
         min_scale=1.0, license="OFL-1.1", category="SANS_SERIF"),
    Face("Lato", _b("lato", "Lato-Regular.ttf"), _b("lato", "Lato-Bold.ttf"), readable=True,
         min_scale=1.08, license="OFL-1.1", category="SANS_SERIF"),
    Face("Playfair Display", _b("playfairdisplay", "PlayfairDisplay[wght].ttf"), variable=True,
         min_scale=1.15, license="OFL-1.1", category="SERIF"),
    Face("Pacifico", _b("pacifico", "Pacifico-Regular.ttf"), min_scale=1.4,
         license="OFL-1.1", category="HANDWRITING"),
    Face("Lobster", _b("lobster", "Lobster-Regular.ttf"), min_scale=1.3,
         license="OFL-1.1", category="DISPLAY"),
    Face("Caveat", _b("caveat", "Caveat[wght].ttf"), variable=True, min_scale=1.6,
         license="OFL-1.1", category="HANDWRITING"),
]

# The registry currently in use (refreshed by registry()). Hot paths
# (text_width, line_height) look faces up here without touching the disk.
_faces: dict[str, Face] = {f.key: f for f in BUNDLED}
_loaded_for: str | None = None


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def user_dir() -> Path:
    """<data folder>/fonts: fonts the user added (kept across updates)."""
    from . import settings
    p = settings.data_dir() / USER_DIR_NAME
    return p


def _scan_user(folder: Path) -> list[Face]:
    out = []
    if not folder.is_dir():
        return out
    for sub in sorted(folder.iterdir()):
        man = sub / MANIFEST
        if not man.is_file():
            continue
        try:
            from .model import MB, read_text_limited
            m = json.loads(read_text_limited(man, MB))
            if m.get("format") != MANIFEST_FORMAT:
                continue
            name = str(m["name"]).strip()
            reg = sub / Path(str(m["regular"])).name
            bold = sub / Path(str(m["bold"])).name if m.get("bold") else None
            if not name or not reg.is_file():
                continue
            scale = float(m.get("min_scale") or 1.3)
            out.append(Face(name, str(reg), str(bold) if bold and bold.is_file() else "",
                            variable=bool(m.get("variable")), readable=False,
                            min_scale=max(1.0, min(2.0, scale)), bundled=False,
                            license=str(m.get("license") or ""),
                            category=str(m.get("category") or ""), folder=str(sub)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            log.warning("skipping unreadable font folder %s", sub)
    return out


def registry(refresh: bool = False) -> dict[str, Face]:
    """All fonts on this computer, by casefolded family name. Bundled fonts win
    over a user font of the same name. Re-scans the user folder when the data
    folder changed (tests) or ``refresh`` is set (after add/remove)."""
    global _faces, _loaded_for
    where = os.environ.get("FOOD_LABELER_DATA", "")
    if refresh or _loaded_for != where:
        faces = {}
        try:
            for f in _scan_user(user_dir()):
                faces[f.key] = f
        except OSError:
            log.exception("could not read the fonts folder")
        for f in BUNDLED:
            faces[f.key] = f
        _faces = faces
        _loaded_for = where
        _font_bytes.cache_clear()
        _load.cache_clear()
    return _faces


def reload() -> dict[str, Face]:
    """Re-read the user's fonts (after adding or removing one)."""
    return registry(refresh=True)


def get(name: str | None) -> Face | None:
    """The face called ``name`` (any case), or None if it isn't on this computer."""
    if not name:
        return None
    return _faces.get(str(name).casefold())


def default_face() -> Face:
    return _faces.get(DEFAULT.casefold()) or BUNDLED[0]


def name_choices() -> list[Face]:
    """Fonts for the name of the food: every font, bundled first, then the user's."""
    reg = registry()
    bundled = list(BUNDLED)
    mine = sorted((f for f in reg.values() if not f.bundled), key=lambda f: f.key)
    return bundled + mine


def other_choices() -> list[Face]:
    """Fonts for everything else: only the easy-to-read sans fonts."""
    return [f for f in BUNDLED if f.readable]


def is_default(lettering: dict | None) -> bool:
    """True if a lettering choice is the standard look (nothing to store)."""
    lt = clean(lettering)
    return all(lt.get(k, DEFAULT).casefold() == DEFAULT.casefold() for k in ("name", "other"))


def clean(lettering) -> dict:
    """Keep only well-formed choices: {"name": str, "other": str}, short strings."""
    out = {}
    if isinstance(lettering, dict):
        for k in ("name", "other"):
            v = lettering.get(k)
            if isinstance(v, str) and v.strip() and len(v) <= 100:
                out[k] = values.text(v.strip())
    return out


def missing(lettering) -> list[str]:
    """Family names a label asks for that aren't on this computer."""
    registry()
    out = []
    for k in ("name", "other"):
        v = clean(lettering).get(k)
        if v and get(v) is None and v not in out:
            out.append(v)
    return out


def roles(template: str, lettering) -> tuple[Face, Face]:
    """(face for the name of the food, face for everything else), with fallbacks:
    a missing font becomes the default; "everything else" must be readable."""
    registry()
    lt = clean(lettering)
    name = get(lt.get("name")) or default_face()
    other = get(lt.get("other"))
    if other is None or not other.readable:
        other = default_face()
    return name, other


def is_legal(key: str) -> bool:
    """Is this block wording that must stay easy to read (ingredients, allergens…)?"""
    return key in LEGAL_KEYS or key.startswith(LEGAL_PREFIXES)


def apply(blocks, template: str, lettering) -> None:
    """Give every Block its face, and raise its minimum size by the face's
    ``min_scale`` (script fonts need to stay bigger to be read).

    Required wording never gets a script or display font, even if the name
    font was asked for or the file was edited by hand."""
    name_face, other_face = roles(template, lettering)
    name_key = NAME_KEYS.get(template)
    for b in blocks:
        face = name_face if b.key == name_key else other_face
        if is_legal(b.key) and not face.readable:
            face = default_face()
        b.font = "" if face.key == DEFAULT.casefold() else face.name
        if face.min_scale > 1.0:
            b.min = int(math.ceil(b.min * face.min_scale))
            b.pref = max(float(b.pref), float(b.min))


# --------------------------------------------------------------------------
# loading fonts
# --------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _font_bytes(path: str) -> bytes:
    # Fonts are read into memory once: FreeType then never keeps the file open,
    # so a user font can be removed (Windows refuses to delete open files).
    return Path(path).read_bytes()


def set_weight(ft: ImageFont.FreeTypeFont, weight: int) -> None:
    """Set a variable font's weight axis (other axes at their defaults)."""
    try:
        axes = ft.get_variation_axes()
    except (OSError, AttributeError):
        return
    vals = []
    for ax in axes:
        name = ax.get("name")
        name = name.decode("ascii", "replace") if isinstance(name, bytes) else str(name)
        if name.lower() in ("weight", "wght"):
            vals.append(max(ax["minimum"], min(ax["maximum"], weight)))
        else:
            vals.append(ax["default"])
    if vals:
        ft.set_variation_by_axes(vals)


def font_from_bytes(data: bytes, size: int, variable: bool = False,
                    bold: bool = False) -> ImageFont.FreeTypeFont:
    """A Pillow font from file contents (used for previews before a font is added too)."""
    ft = ImageFont.truetype(io.BytesIO(data), max(4, int(size)))
    if variable:
        set_weight(ft, 700 if bold else 400)
    return ft


@lru_cache(maxsize=1024)
def _load(regular: str, bold_file: str, variable: bool, size: int,
          bold: bool) -> ImageFont.FreeTypeFont:
    if bold and bold_file:
        return font_from_bytes(_font_bytes(bold_file), size)
    return font_from_bytes(_font_bytes(regular), size, variable, bold)


def face_for(name: str | None) -> Face:
    """The face to draw with: ``name`` if it is on this computer, else the default."""
    return (get(name) if name else None) or default_face()


def font(name: str | None, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """The font for a face at ``size`` dots. Faces without a bold style use regular."""
    f = face_for(name)
    try:
        return _load(f.regular, f.bold, f.variable, max(4, int(size)), bool(bold))
    except OSError:
        log.exception("font %s unreadable; using the standard lettering", f.name)
        d = default_face()
        return _load(d.regular, d.bold, d.variable, max(4, int(size)), bool(bold))


def ink(name: str | None, size: int, bold: bool = False, text: str = "Soup Hamburg") -> int:
    """Black pixels when ``text`` is drawn: bold must give more than regular
    (used by tests and --selftest to prove variable-font bold really works)."""
    ft = font(name, size, bold)
    l, t, r, b = ft.getbbox(text)
    img = Image.new("1", (int(r - l) + 4, int(b - t) + 4), 1)
    ImageDraw.Draw(img).text((2 - l, 2 - t), text, font=ft, fill=0)
    return img.histogram()[0]


# --------------------------------------------------------------------------
# preview pictures (the picker draws each font's name in that font)
# --------------------------------------------------------------------------

def preview_image(text: str, height: int, name: str | None = None, data: bytes | None = None,
                  variable: bool = False, bg=(255, 255, 255), fg=(30, 30, 30),
                  max_width: int = 900) -> Image.Image:
    """``text`` drawn in a font, ``height`` pixels tall, as an RGB picture.

    Tk doesn't know fonts that aren't installed on the computer, so the
    picker shows these pictures instead of Tk text. Pass ``name`` for a
    registered font, or ``data`` (file contents) for one not added yet."""
    size = max(8, int(height * 0.62))
    for _ in range(12):
        ft = font_from_bytes(data, size, variable) if data else font(name, size)
        l, t, r, b = ft.getbbox(text)
        if r - l <= max_width - 8 or size <= 8:
            break
        size = int(size * 0.88)
    asc, desc = ft.getmetrics()
    w = max(1, min(max_width, int(r - l) + 8))
    h = max(height, asc + desc + 4)
    img = Image.new("RGB", (w, h), bg)
    ImageDraw.Draw(img).text((4 - l, (h - (asc + desc)) // 2), text, font=ft, fill=fg)
    return img
