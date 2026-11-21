"""Get more fonts: fetch a Google Fonts family, or add a font file from the computer.

Google publishes every Google Fonts family in a public GitHub repository,
github.com/google/fonts, one folder per family under the folder of its
license: ``ofl/<name>/``, ``apache/<name>/`` or ``ufl/<name>/``, where
``<name>`` is the family name in lower case without spaces ("Dancing Script"
-> ``ofl/dancingscript/``). Each folder has a ``METADATA.pb`` (a small text
file) listing the font files and their weights, and the license file.

So, without any key or account:

1. ``METADATA.pb`` is read from raw.githubusercontent.com for each license
   folder in turn until one exists (not found in any -> "Couldn't find…").
2. The regular (400) style and, if there is one, bold (700) are picked from
   it. A family that only comes as a variable font (``Name[wght].ttf``)
   gets that one file; bold then comes from its weight axis.
3. If ``METADATA.pb`` lists no files, the folder is listed with the GitHub
   contents API (api.github.com, unauthenticated; its hourly limit gives a
   plain "try again later" message).
4. Every file is checked: https only, only GitHub hosts (redirects too),
   time-outs, at most ``MAX_FONT_BYTES`` each, and it must be a TrueType or
   OpenType font that Pillow can open.

Nothing is written until the user has seen a preview and pressed *Add this
font*: ``fetch_family()`` returns a ``Candidate`` in memory and ``install()``
writes it to ``<data folder>/fonts/<name>/`` with a ``font.json`` manifest.
That folder belongs to the user, like their other files: updates never touch
it. All of this runs on a worker thread; nothing here touches Tk.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import lettering

log = logging.getLogger("food_labeler.fontget")

RAW = "https://raw.githubusercontent.com/google/fonts/main/"
API = "https://api.github.com/repos/google/fonts/contents/"
LICENSE_DIRS = ("ofl", "apache", "ufl")
LICENSE_FILES = {"ofl": ("OFL.txt",), "apache": ("LICENSE.txt",), "ufl": ("UFL.txt",)}
LICENSE_NAMES = {"ofl": "SIL Open Font License 1.1", "apache": "Apache License 2.0",
                 "ufl": "Ubuntu Font License 1.0"}
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com", "api.github.com"}
MAX_FONT_BYTES = 5 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
TIMEOUT = 20
FONT_EXTS = (".ttf", ".otf")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9_\-\[\],.]+$")
_SAFE_FAMILY = re.compile(r"^[A-Za-z0-9 \-]+$")

NEEDS_INTERNET = ("Getting more fonts needs the internet. Check that this computer is "
                  "online and try again. (Everything else in Food Labeler works without it.)")
BUSY = ("The font library is busy right now (too many people asked in the last hour). "
        "Please try again later.")
NOT_A_FONT = "That file isn't a font Food Labeler can use. Please choose a .ttf or .otf file."
TOO_BIG = "That font file is too big (more than 5 MB), so Food Labeler won't use it."


class FontGetError(Exception):
    """Something went wrong; the message is friendly and can be shown as is."""


class NotFound(FontGetError):
    pass


class HttpStatus(Exception):
    """An HTTP answer other than 200 (internal; turned into a FontGetError)."""

    def __init__(self, status: int, headers=None):
        super().__init__(status)
        self.status = status
        self.headers = dict(headers or {})


def not_found_message(name: str) -> str:
    return (f"Couldn't find a font called “{name}”. Check the spelling on fonts.google.com "
            "(the name must match exactly, for example “Dancing Script”).")


# --------------------------------------------------------------------------
# names and URLs
# --------------------------------------------------------------------------

def clean_family(name: str) -> str:
    """Tidy a typed family name, or raise NotFound with a friendly message."""
    name = " ".join(str(name or "").split())
    if not name:
        raise NotFound("Please type the name of a font, for example “Dancing Script”.")
    if len(name) > 60 or not _SAFE_FAMILY.match(name):
        raise NotFound(not_found_message(name))
    return name


def folder_name(family: str) -> str:
    """The repository folder of a family: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", family.lower())


def check_url(url: str) -> str:
    """Allow only https URLs on GitHub's hosts; raise FontGetError otherwise."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS or u.username \
            or u.password or (u.port not in (None, 443)):
        raise FontGetError("Food Labeler only gets fonts from the Google Fonts library "
                           "on GitHub.")
    return url


def file_url(licdir: str, folder: str, filename: str) -> str:
    """raw.githubusercontent.com URL of one file in a family folder."""
    if licdir not in LICENSE_DIRS or not re.fullmatch(r"[a-z0-9]+", folder):
        raise FontGetError("That isn't a font folder Food Labeler knows.")
    if not safe_filename(filename):
        raise FontGetError("That font has a file name Food Labeler won't use.")
    return check_url(RAW + f"{licdir}/{folder}/" + urllib.parse.quote(filename))


def api_url(licdir: str, folder: str) -> str:
    if licdir not in LICENSE_DIRS or not re.fullmatch(r"[a-z0-9]+", folder):
        raise FontGetError("That isn't a font folder Food Labeler knows.")
    return check_url(API + f"{licdir}/{folder}")


def safe_filename(name: str) -> bool:
    """A plain file name (no folders, no ..) that we are willing to save."""
    return bool(name) and len(name) <= 120 and bool(_SAFE_FILE.match(name)) \
        and ".." not in name and not name.startswith(".")


# --------------------------------------------------------------------------
# HTTP (the only part that touches the network)
# --------------------------------------------------------------------------

class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to allowed hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_limited(resp, limit: int) -> bytes:
    """Read a response body, refusing anything larger than ``limit`` bytes."""
    length = resp.headers.get("Content-Length") if getattr(resp, "headers", None) else None
    if length and length.isdigit() and int(length) > limit:
        raise FontGetError(TOO_BIG)
    buf = io.BytesIO()
    while True:
        chunk = resp.read(64 * 1024)
        if not chunk:
            break
        buf.write(chunk)
        if buf.tell() > limit:
            raise FontGetError(TOO_BIG)
    return buf.getvalue()


def http_get(url: str, limit: int = MAX_FONT_BYTES) -> bytes:
    """GET an allowed URL. Raises HttpStatus for non-200 answers, FontGetError
    (friendly) for no internet, time-outs and oversized answers."""
    check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": "FoodLabeler-fonts",
                                               "Accept": "*/*"})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise HttpStatus(status, resp.headers)
            return read_limited(resp, limit)
    except urllib.error.HTTPError as e:
        raise HttpStatus(e.code, e.headers) from None
    except (socket.timeout, TimeoutError):
        raise FontGetError("The font library didn't answer in time. Please try again "
                           "in a moment.") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, FontGetError):
            raise e.reason from None
        log.info("font download failed: %s", e)
        raise FontGetError(NEEDS_INTERNET) from None
    except OSError as e:
        log.info("font download failed: %s", e)
        raise FontGetError(NEEDS_INTERNET) from None


def _get(get, url, limit):
    """Call ``get`` and turn HTTP statuses into friendly errors (404 -> None)."""
    try:
        return get(url, limit)
    except HttpStatus as e:
        if e.status == 404:
            return None
        if e.status in (403, 429):
            raise FontGetError(BUSY) from None
        log.info("font library answered %s for %s", e.status, url)
        raise FontGetError("The font library had a problem. Please try again later.") from None


# --------------------------------------------------------------------------
# METADATA.pb
# --------------------------------------------------------------------------

def parse_metadata(text: str) -> dict:
    """The parts of a Google Fonts METADATA.pb (protobuf text format) we need:
    name, license, category, fonts [{style, weight, filename}], axes [{tag, min, max}]."""
    out = {"name": "", "license": "", "category": "", "fonts": [], "axes": []}
    stack: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\w+)\s*\{$", line)
        if m:
            stack.append({"_kind": m.group(1)})
            continue
        if line == "}":
            if stack:
                blk = stack.pop()
                if not stack and blk["_kind"] == "fonts":
                    out["fonts"].append(blk)
                elif not stack and blk["_kind"] == "axes":
                    out["axes"].append(blk)
            continue
        m = re.match(r'^(\w+)\s*:\s*(?:"((?:[^"\\]|\\.)*)"|(\S+))$', line)
        if not m:
            continue
        key, sval, bare = m.group(1), m.group(2), m.group(3)
        val = sval if sval is not None else bare
        if stack:
            if len(stack) == 1:
                stack[-1][key] = val
        elif key in ("name", "license", "category") and not out[key]:
            out[key] = val
    for f in out["fonts"]:
        try:
            f["weight"] = int(float(f.get("weight", 400)))
        except ValueError:
            f["weight"] = 400
    return out


def pick_files(meta: dict) -> tuple[str, str, bool, bool]:
    """(regular file, bold file or "", variable?, can be bold?) from METADATA."""
    normal = [f for f in meta.get("fonts", []) if f.get("style", "normal") == "normal"
              and str(f.get("filename", "")).lower().endswith(FONT_EXTS)]
    if not normal:
        return "", "", False, False
    regular = min(normal, key=lambda f: abs(f["weight"] - 400))["filename"]
    variable = "[" in regular
    if variable:
        wght = [a for a in meta.get("axes", []) if a.get("tag") == "wght"]
        try:
            can_bold = bool(wght) and float(wght[0].get("max_value", 0)) >= 600
        except ValueError:
            can_bold = False
        return regular, "", True, can_bold
    bold = [f["filename"] for f in normal if f["weight"] == 700 and f["filename"] != regular]
    return regular, (bold[0] if bold else ""), False, bool(bold)


def pick_from_listing(entries: list) -> tuple[str, str, bool, bool]:
    """Same as pick_files, from a GitHub contents API folder listing."""
    names = [e.get("name", "") for e in entries if isinstance(e, dict)
             and e.get("type") == "file" and str(e.get("name", "")).lower().endswith(FONT_EXTS)]
    names = [n for n in names if "italic" not in n.lower()]
    var = [n for n in names if "[" in n]
    if var:
        return var[0], "", True, "wght" in var[0]
    reg = [n for n in names if re.search(r"-regular\.", n, re.I)] or names[:1]
    bold = [n for n in names if re.search(r"-bold\.", n, re.I)]
    if not reg:
        return "", "", False, False
    return reg[0], (bold[0] if bold else ""), False, bool(bold)


# --------------------------------------------------------------------------
# checking font files
# --------------------------------------------------------------------------

def check_font_bytes(data: bytes, limit: int = MAX_FONT_BYTES) -> tuple[str, str]:
    """Is this a TrueType/OpenType font Pillow can draw with? Returns (family, style)."""
    if data is None or len(data) < 12:
        raise FontGetError(NOT_A_FONT)
    if len(data) > limit:
        raise FontGetError(TOO_BIG)
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise FontGetError(NOT_A_FONT)
    try:
        ft = lettering.font_from_bytes(data, 24)
        family, style = ft.getname()
        if ft.getlength("Abc") <= 0:
            raise OSError("no glyphs")
    except Exception:  # noqa: BLE001 - Pillow raises several kinds for broken fonts
        raise FontGetError(NOT_A_FONT) from None
    return str(family or "").strip(), str(style or "").strip()


def min_scale_for(data: bytes, category: str = "", variable: bool = False) -> float:
    """How much bigger than DejaVu Sans this font must print to stay readable:
    from its measured x-height and its category (handwriting needs more)."""
    try:
        ft = lettering.font_from_bytes(data, 100, variable)
        l, t, r, b = ft.getbbox("x")
        xh = max(1, b - t)
        base = max(1.0, lettering._REF_X_HEIGHT / xh)
    except Exception:  # noqa: BLE001
        base = 1.2
    scale = base * lettering._CATEGORY_SCALE.get(category.upper(), 1.2)
    return round(max(1.0, min(2.0, scale)), 2)


# --------------------------------------------------------------------------
# fetching and installing
# --------------------------------------------------------------------------

@dataclass
class Candidate:
    """A font ready to preview and add (nothing is on disk yet)."""
    name: str
    regular_name: str
    regular: bytes
    bold_name: str = ""
    bold: bytes = b""
    variable: bool = False
    can_bold: bool = False
    category: str = ""
    license: str = ""
    license_name: str = ""
    license_text: bytes = b""
    source: str = ""
    extra: dict = field(default_factory=dict)


def fetch_family(name: str, get=None) -> Candidate:
    """Find a Google Fonts family by name and download it into memory.

    ``get(url, limit) -> bytes`` does the HTTP (``http_get``; tests pass a
    fake). Raises FontGetError/NotFound with a friendly message."""
    get = get or http_get
    family = clean_family(name)
    if lettering.get(family) is not None and lettering.get(family).bundled:
        raise FontGetError(f"You already have {lettering.get(family).name}: it comes with "
                           "Food Labeler.")
    folder = folder_name(family)
    if not folder:
        raise NotFound(not_found_message(family))
    for licdir in LICENSE_DIRS:
        meta_bytes = _get(get, file_url(licdir, folder, "METADATA.pb"), MAX_TEXT_BYTES)
        if meta_bytes is None:
            continue
        meta = parse_metadata(meta_bytes.decode("utf-8", "replace"))
        regular, bold, variable, can_bold = pick_files(meta)
        if not regular:
            listing = _get(get, api_url(licdir, folder), MAX_TEXT_BYTES)
            try:
                entries = json.loads(listing.decode("utf-8")) if listing else []
            except (ValueError, RecursionError):
                entries = []
            regular, bold, variable, can_bold = pick_from_listing(
                entries if isinstance(entries, list) else [])
        if not regular:
            raise NotFound(not_found_message(family))
        reg_data = _get(get, file_url(licdir, folder, regular), MAX_FONT_BYTES)
        if reg_data is None:
            raise NotFound(not_found_message(family))
        fam, _style = check_font_bytes(reg_data)
        bold_data = b""
        if bold:
            bold_data = _get(get, file_url(licdir, folder, bold), MAX_FONT_BYTES) or b""
            if bold_data:
                check_font_bytes(bold_data)
            else:
                bold, can_bold = "", False
        lic_text = b""
        for lf in LICENSE_FILES[licdir]:
            lic_text = _get(get, file_url(licdir, folder, lf), MAX_TEXT_BYTES) or b""
            if lic_text:
                break
        return Candidate(
            name=meta.get("name") or fam or family, regular_name=regular, regular=reg_data,
            bold_name=bold, bold=bold_data, variable=variable, can_bold=can_bold,
            category=(meta.get("category") or "").upper(),
            license=(meta.get("license") or licdir).upper(),
            license_name=LICENSE_NAMES[licdir], license_text=lic_text,
            source=f"https://github.com/google/fonts/tree/main/{licdir}/{folder}")
    raise NotFound(not_found_message(family))


def from_file(path) -> Candidate:
    """A font file the user picked on their computer (checked, not copied yet)."""
    p = Path(path)
    if p.suffix.lower() not in FONT_EXTS:
        raise FontGetError(NOT_A_FONT)
    try:
        if p.stat().st_size > MAX_FONT_BYTES:
            raise FontGetError(TOO_BIG)
        data = p.read_bytes()
    except OSError:
        raise FontGetError("That file couldn't be opened.") from None
    family, _style = check_font_bytes(data)
    if not family:
        raise FontGetError(NOT_A_FONT)
    variable = False
    try:
        variable = bool(lettering.font_from_bytes(data, 24).get_variation_axes())
    except Exception:  # noqa: BLE001 - not a variable font
        variable = False
    return Candidate(name=family, regular_name=_plain_name(p.name, p.suffix.lower()),
                     regular=data, variable=variable, can_bold=variable,
                     source="Added from my computer")


def _plain_name(name: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_\-\[\],.]", "-", Path(name).stem).strip(".-") or "font"
    return stem[:100] + ext


def _write_bytes(path: Path, data: bytes) -> None:
    """Atomic write (temp file + fsync + rename), like model.atomic_write_text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install(c: Candidate, folder: Path | None = None) -> lettering.Face:
    """Save a Candidate in <data folder>/fonts/<name>/ and return its Face."""
    existing = lettering.get(c.name)
    if existing is not None and existing.bundled:
        raise FontGetError(f"You already have {existing.name}: it comes with Food Labeler.")
    base = Path(folder) if folder else lettering.user_dir()
    slug = folder_name(c.name) or "font"
    target = base / slug
    for name in (c.regular_name, c.bold_name):
        if name and not safe_filename(name):
            raise FontGetError("That font has a file name Food Labeler won't use.")
    check_font_bytes(c.regular)
    if c.bold:
        check_font_bytes(c.bold)
    try:
        if target.exists():
            _remove_folder(target, base)
        _write_bytes(target / c.regular_name, c.regular)
        if c.bold and c.bold_name:
            _write_bytes(target / c.bold_name, c.bold)
        lic_file = ""
        if c.license_text:
            lic_file = {"OFL": "OFL.txt", "UFL": "UFL.txt"}.get(c.license, "LICENSE.txt")
            _write_bytes(target / lic_file, c.license_text)
        manifest = {"format": lettering.MANIFEST_FORMAT, "version": 1, "name": c.name,
                    "regular": c.regular_name, "bold": c.bold_name if c.bold else "",
                    "variable": bool(c.variable and c.can_bold),
                    "category": c.category, "license": c.license_name or c.license,
                    "license_file": lic_file, "source": c.source,
                    "min_scale": min_scale_for(c.regular, c.category, c.variable)}
        _write_bytes(target / lettering.MANIFEST,
                     json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    except OSError:
        log.exception("could not save font %s", c.name)
        raise FontGetError("Food Labeler couldn't save the font on this computer.") from None
    lettering.reload()
    face = lettering.get(c.name)
    if face is None:
        raise FontGetError("Food Labeler couldn't save the font on this computer.")
    return face


def _remove_folder(target: Path, base: Path) -> None:
    target, base = target.resolve(), base.resolve()
    if base not in target.parents:
        raise FontGetError("That font isn't one you added.")
    shutil.rmtree(target)


def remove(name: str) -> None:
    """Remove a font the user added (bundled fonts can't be removed)."""
    face = lettering.get(name)
    if face is None:
        return
    if face.bundled or not face.folder:
        raise FontGetError(f"{face.name} comes with Food Labeler and can't be removed.")
    try:
        _remove_folder(Path(face.folder), lettering.user_dir())
    except OSError:
        log.exception("could not remove font %s", name)
        raise FontGetError("Food Labeler couldn't remove that font. Please try again.") \
            from None
    finally:
        lettering.reload()
