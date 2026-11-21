"""Finding printers and sending print jobs to them.

Connections ("methods"):
  windows_raw     Windows printer, raw bytes through the spooler (normal on Windows)
  windows_driver  Windows printer, picture printed through the maker's driver (fallback)
  cups            Linux/Mac CUPS queue, sent with `lp -o raw`
  device          Linux device file such as /dev/usb/lp0
  network         host:port raw TCP (Advanced only)

All errors reaching the user are PrinterError with a plain-English message.
Set FOOD_LABELER_DRY_RUN=<folder> to write jobs to files instead of printing.

Printer identity
----------------
Settings (nickname, language, last label size) are stored per printer id, so
the id must survive reboots and re-plugging. Cheap LP610BT clones all report
the same USB vid:pid (0483:2025) *and* the same serial number, so neither can
tell two of them apart; /dev/usb/lpN numbers are handed out in detection
order and swap between boots. What is stable is the physical USB port path
(``1-1.4``), so on Linux the id is ``usb:<port path>`` (same printer in the
same socket = same id). On Windows the spooler already gives each unit its
own printer ("4B-LP610BT", "4B-LP610BT (Copy 1)") on its own port (USB001,
USB002), so the id is ``win:<printer name>|<port>``. CUPS queues that point
at a detected device are merged into that device's entry.

Windows: raw first, driver as a fallback
----------------------------------------
"windows_raw" hands our TSPL/ZPL bytes to the spooler as a RAW document; the
maker's driver only acts as a pipe, so the label prints exactly as rendered.
Some drivers don't pass RAW data through. For those, the per-printer
"Print through Windows driver" switch (Advanced) uses "windows_driver": the
1-bit picture is drawn on the printer's GDI device context and the driver
converts it, losing exact darkness/speed control but usually working.

Resolution
----------
The print head's resolution (203 or 300 dpi) belongs to the printer. Its
default comes from the matched model in known_printers.json, unless the 1284
model or the Windows printer/driver name says "300dpi" (Zebra names its
300 dpi models "ZD421-300dpi"); ``printer_dpi`` lets the user's own choice in
My printers / Advanced win. Unknown printers are 203 dpi.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import tspl, zpl
from .stocks import Stock

log = logging.getLogger("food_labeler.printers")

LABEL_RE = re.compile(r"LP610|Labelnize|Polono|label|4B-|Zebra|ZP450", re.I)
ZEBRA_RE = re.compile(r"Zebra|ZP450|ZPL", re.I)
DEVICE_GLOBS = ["/dev/usb/lp*", "/dev/lp610bt", "/dev/zebra"]

KINDS = {"tspl": "LP610BT / TSPL label printer", "zpl": "Zebra (ZPL)"}
METHODS = {
    "windows_raw": "Windows printer",
    "windows_driver": "Print through Windows driver (if raw doesn't work)",
    "cups": "Printer queue",
    "device": "USB cable (direct)",
    "network": "Network (address and port)",
}

MSG_NOT_ANSWERING = ("The printer isn't answering. Check it is switched on "
                     "and the cable is plugged in.")
MSG_NO_PRINTER = "No printer is set up yet. Click “Set up my printer”."
MSG_PERMISSION = ("This computer won't let Food Labeler use the printer yet. Ask your helper "
                  "to add you to the “lp” group, then log out and back in.")


class PrinterError(Exception):
    """Something went wrong printing. str(e) is safe to show to the user."""


@dataclass
class Printer:
    """One printer the user can pick. `id` is stable across reboots and re-plugs
    (USB port path on Linux, name+port on Windows) — never /dev/usb/lpN."""
    id: str
    kind: str = ""           # "tspl" | "zpl" | "" (unknown: treated as TSPL)
    model: str = ""          # e.g. "4B-LP610BT", "ZTC ZP 450-200dpi"
    method: str = ""         # how to send: cups | device | windows_raw | network
    target: str = ""         # queue / device path / printer name / host:port
    port: str = ""           # human-readable place: "USB port 1-1.4", "USB001"
    device: str = ""         # raw device path (Linux), if any
    queue: str = ""          # CUPS queue, if any
    detail: str = ""         # technical info for Advanced
    manual: bool = False     # added by hand (network)
    vidpid: str = ""         # USB vendor:product, e.g. "0483:2025"
    family: object = None    # known.Definition this printer matched, if any
    dpi: int = 203           # print head resolution as detected (see printer_dpi)

    def default_name(self) -> str:
        """A friendly name when the user hasn't given one."""
        if self.family is not None:
            return self.family.display_name
        m = self.model or ""
        if self.kind == "zpl" or ZEBRA_RE.search(m):
            mm = re.search(r"Z[A-Z]{1,2}\s?(\d{3,4})", m.replace("ZTC", ""))
            return f"Zebra {mm.group(0).replace(' ', '')}" if mm else "Zebra label printer"
        short = re.sub(r"^4B-", "", m.strip())
        if self.kind == "tspl" or TSPL_RE.search(m):
            return f"Label printer ({short})" if short else "Label printer"
        if m:
            return short
        return self.queue or self.target or "Printer"

    def display(self, nickname: str = "") -> str:
        """Name plus where it is ("… — USB port 1-1.4"), so identical units differ."""
        name = nickname or self.default_name()
        return f"{name} \u2014 {self.port}" if self.port else name

    @property
    def matches(self) -> bool:
        """Looks like a label printer (used to auto-pick the only one)."""
        text = " ".join([self.model, self.queue, self.target, self.detail])
        return bool(self.kind) or bool(LABEL_RE.search(text))

    def config(self, kind_override: str = "") -> dict:
        """What build_job/send need: language, method and target."""
        return {"kind": kind_override or self.kind or "tspl", "method": self.method,
                "target": self.target}


TSPL_RE = re.compile(r"TSPL|LP610|Polono|Labelnize|4B-|BAR PRINTER", re.I)
ZPL_RE = re.compile(r"ZPL|Zebra|ZDesigner|ZP\s?450", re.I)


def parse_1284(text: str) -> dict:
    """'MFG:Polono;CMD:TSPL2;MDL:4B-LP610BT;' -> {'MFG': 'Polono', ...} (keys upper-case)."""
    out = {}
    for part in str(text or "").strip().strip("\x00").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().upper()] = v.strip()
    return out


def kind_from_1284(info: dict) -> str:
    """Printer language from the 1284 command set: "tspl", "zpl" or ""."""
    cmd = info.get("CMD") or info.get("COMMAND SET") or ""
    if "TSPL" in cmd.upper():
        return "tspl"
    if "ZPL" in cmd.upper():
        return "zpl"
    return ""


def model_from_1284(info: dict) -> str:
    """Model string from a 1284 id (MDL, or MODEL on Zebras)."""
    return info.get("MDL") or info.get("MODEL") or ""


DPI_CHOICES = (203, 300)
DPI_LABELS = {203: "Normal (203 dpi) — most label printers",
              300: "Sharp (300 dpi) — only if your printer says 300 dpi"}
DPI_300_RE = re.compile(r"300\s*-?\s*dpi|-300(?![0-9])", re.I)
DPI_203_RE = re.compile(r"20[03]\s*-?\s*dpi|-20[03](?![0-9])", re.I)


def dpi_from_text(text: str) -> int | None:
    """Resolution named in a model / printer / driver name: "ZD421-300dpi" -> 300,
    "ZTC ZP 450-200dpi" -> 203, nothing said -> None. Best effort only."""
    t = text or ""
    if DPI_300_RE.search(t):
        return 300
    if DPI_203_RE.search(t):
        return 203
    return None


def printer_dpi(p: "Printer | None", info: dict | None = None) -> int:
    """The resolution to lay labels out for: the user's choice for this printer
    (settings ``"dpi"``), else what was detected, else 203. No printer: 203."""
    want = (info or {}).get("dpi")
    if want in DPI_CHOICES and not isinstance(want, bool):
        return int(want)
    if p is None:
        return 203
    return p.dpi if p.dpi in DPI_CHOICES else 203


def classify(p: "Printer", known=None, info: dict | None = None, text: str = "") -> None:
    """Fill in family (known model), kind (printer language) and dpi for a printer."""
    text = text or f"{p.model} {p.target} {p.detail}"
    if known is not None:
        p.family = known.match(info or {}, p.vidpid, text)
    named = dpi_from_text(" ".join([model_from_1284(info or {}), p.model, text]))
    if named is not None:
        p.dpi = named
    elif p.family is not None:
        p.dpi = p.family.dpi
    if not p.kind and info:
        p.kind = kind_from_1284(info)
    if not p.kind and p.family is not None:
        p.kind = p.family.language
    if not p.kind:
        p.kind = kind_from_text(text)


def kind_from_text(text: str) -> str:
    """Guess the language from a printer/driver/queue name ("" if no idea)."""
    if ZPL_RE.search(text or ""):
        return "zpl"
    if TSPL_RE.search(text or ""):
        return "tspl"
    return ""


IS_WINDOWS = sys.platform.startswith("win")


def _win32print():
    try:
        import win32print  # type: ignore
        return win32print
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def discover_windows(win32print=None, known=None) -> list[Printer]:
    """Installed Windows printers (local + connections). win32print is injectable for tests."""
    w = win32print or _win32print()
    if w is None:
        return []
    flags = w.PRINTER_ENUM_LOCAL | w.PRINTER_ENUM_CONNECTIONS
    out = []
    try:
        for p in w.EnumPrinters(flags, None, 2):
            name = p.get("pPrinterName", "")
            driver = p.get("pDriverName", "") or ""
            port = p.get("pPortName", "") or ""
            kind = kind_from_text(f"{name} {driver}")
            model = name if kind else driver
            if kind == "tspl":
                mm = re.search(r"4B-\w+|LP\d+\w*", f"{name} {driver}", re.I)
                model = mm.group(0) if mm else name
            pr = Printer(id=f"win:{name}|{port}", kind="", model=model,
                         method="windows_raw", target=name,
                         port=port, detail=f"driver {driver}, port {port}")
            classify(pr, known, None, f"{name} {driver}")
            out.append(pr)
    except Exception:  # noqa: BLE001
        log.exception("EnumPrinters failed")
    # identical units: "4B-LP610BT" and "4B-LP610BT (Copy 1)" — the port tells them apart
    for p in out:
        if p.port.upper().startswith("USB"):
            p.port = f"USB port {p.port.upper().replace('USB', '').lstrip('0') or '0'}"
    return out


def _run(cmd, run=subprocess.run, timeout=5):
    """Run a command; (returncode, stdout, stderr), with -1 if it couldn't start."""
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def _read(path) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(4096).decode("utf-8", "replace")
    except OSError:
        return ""


PORT_RE = re.compile(r"^\d+-[\d.]+$")


def usb_port_of(sys_device_path: str) -> str:
    """'/sys/devices/.../usb1/1-1/1-1.4/1-1.4:1.0' -> '1-1.4'.

    The deepest "bus-port.port…" component of the resolved sysfs path is the
    physical socket the printer is plugged into; this is what makes printer
    ids stable (see the module docstring).
    """
    real = os.path.realpath(sys_device_path)
    for part in reversed(real.split(os.sep)):
        cand = part.split(":")[0]
        if PORT_RE.match(cand):
            return cand
    return ""


def cups_queues(run=subprocess.run) -> dict:
    """{queue: device uri} for queues that exist (empty if CUPS isn't there)."""
    code, out, _ = _run(["lpstat", "-v"], run)
    queues = {}
    if code == 0:
        for line in out.splitlines():
            m = re.match(r"device for (.+?):\s*(\S+)", line.strip())
            if m:
                queues[m.group(1)] = m.group(2)
    code, out, _ = _run(["lpstat", "-e"], run)
    if code == 0:
        for q in out.split():
            queues.setdefault(q.strip(), "")
    return queues


def _vidpid_of(sys_device_path: str) -> str:
    """Vendor:product of the USB device that owns an interface directory."""
    real = os.path.realpath(sys_device_path)
    for d in (real, os.path.dirname(real)):
        v, p = _read(os.path.join(d, "idVendor")).strip(), _read(os.path.join(d, "idProduct")).strip()
        if v and p:
            return f"{v}:{p}".lower()
    return ""


def discover_linux(sys_root="/sys", dev_root="/dev", run=subprocess.run,
                   known=None) -> list[Printer]:
    """USB printers bound to the usblp driver (/sys/class/usbmisc/lpN) plus CUPS queues.

    sys_root, dev_root and run are replaceable so tests can use a fake sysfs.
    A queue whose device URI points at one of the found devices takes over
    that entry (method "cups", same id); other queues are listed separately.
    """
    usb: list[Printer] = []
    base = os.path.join(sys_root, "class", "usbmisc")
    try:
        names = sorted(n for n in os.listdir(base) if n.startswith("lp"))
    except OSError:
        names = []
    # udev symlinks in /dev (e.g. /dev/lp610bt-white -> usb/lp0)
    links: dict[str, list[str]] = {}
    try:
        for n in sorted(os.listdir(dev_root)):
            p = os.path.join(dev_root, n)
            if os.path.islink(p):
                links.setdefault(os.path.realpath(p), []).append(p)
    except OSError:
        pass
    for n in names:
        devdir = os.path.join(base, n, "device")
        info = parse_1284(_read(os.path.join(devdir, "ieee1284_id")))
        port = usb_port_of(devdir)
        node = os.path.join(dev_root, "usb", n)
        syms = links.get(os.path.realpath(node), [])
        target = syms[0] if syms else node
        pid = f"usb:{port}" if port else f"dev:{node}"
        pr = Printer(id=pid, kind="", model=model_from_1284(info), method="device",
                     target=target, device=target, vidpid=_vidpid_of(devdir),
                     port=f"USB port {port}" if port else "USB",
                     detail=" ".join([node] + syms))
        classify(pr, known, info, f"{pr.model} {info.get('MFG') or info.get('MANUFACTURER') or ''}")
        usb.append(pr)
    # Without sysfs info (unusual), fall back to whatever device files exist.
    if not usb:
        for pattern in DEVICE_GLOBS:
            for path in sorted(glob.glob(os.path.join(dev_root, pattern[len("/dev/"):]))):
                pr = Printer(id=f"dev:{path}", method="device", target=path, device=path,
                             port="USB", model=os.path.basename(path))
                classify(pr, known, None, path)
                usb.append(pr)

    # CUPS: a queue that points at one of these devices becomes the same entry.
    out = list(usb)
    for q, uri in cups_queues(run).items():
        owner = None
        m = re.search(r"(/dev/[^\s?#]+)", uri or "")
        if m:
            path = m.group(1)
            local = os.path.join(dev_root, path[len("/dev/"):])
            rl = os.path.realpath(local)
            for p in usb:
                if p.device and os.path.realpath(p.device) == rl:
                    owner = p
                    break
        elif uri.startswith("usb://"):
            from urllib.parse import unquote
            u = unquote(uri)
            cands = [p for p in usb if p.model and p.model.replace(" ", "").lower()
                     in u.replace(" ", "").lower()]
            if len(cands) == 1:
                owner = cands[0]
        if owner is not None and not owner.queue:
            owner.queue = q
            owner.method, owner.target = "cups", q
            owner.detail = f"queue {q} ({uri}); {owner.detail}"
            continue
        if owner is not None:
            continue
        pr = Printer(id=f"cups:{q}", model=q, method="cups", target=q,
                     queue=q, port="printer queue", detail=uri)
        classify(pr, known, None, f"{q} {uri}")
        out.append(pr)
    return out


def discover(known=None) -> list[Printer]:
    """All printers on this computer. Slow-ish: the app calls it off the UI thread."""
    if IS_WINDOWS:
        return discover_windows(known=known)
    return discover_linux(known=known)


def network_printer(target: str, kind: str = "tspl") -> Printer:
    """A printer reached by raw TCP at "host:port" (added by hand under Advanced)."""
    host, port = parse_hostport(target)
    return Printer(id=f"net:{host}:{port}", kind=kind, model="", method="network",
                   target=f"{host}:{port}", port=f"network {host}:{port}", manual=True)


def auto_pick(found: list[Printer]) -> Printer | None:
    """Pick a label printer only if there is exactly one that looks like one."""
    matches = [p for p in found if p.matches]
    if len(matches) == 1:
        return matches[0]
    if not matches and len(found) == 1 and not IS_WINDOWS:
        return found[0]
    return None


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def too_wide_message(stock: Stock, family) -> str:
    """Friendly refusal when a label is wider than the printer can print ("" if it fits)."""
    if family is None or family.fits(stock):
        return ""
    mm = family.max_width_mm
    return (f"“{stock.name}” labels are wider than this printer can print "
            f"(it prints up to {mm:.0f} mm, about {mm / 25.4:.1f} inches, across). "
            "Pick a narrower label size.")


def build_job(img, stock: Stock, printer_cfg: dict, advanced: dict, copies: int,
              family=None, print_settings: dict | None = None) -> bytes:
    """printer_cfg: {"kind", "method", "target"} (see Printer.config).

    ``img`` and ``stock`` must be at the printer's resolution, and ``img``
    already nudged/turned (printsettings.adjust_image). Darkness/speed/gap:
    this printer's print settings, else the Advanced setting for this size,
    else the printer model's default from known_printers.json, else the label
    size default. Raises PrinterError if the label is wider than the model's
    print head.
    """
    from . import printsettings
    wide = too_wide_message(stock, family)
    if wide:
        raise PrinterError(wide)
    advanced = advanced or {}
    if printer_cfg.get("kind") == "zpl":
        return zpl.build_job(img, stock, copies,
                             **printsettings.zpl_values(stock, print_settings, advanced))
    v = printsettings.tspl_values(stock, print_settings, advanced, family)
    return tspl.build_job(img, stock, copies, invert=bool(advanced.get("invert")), **v)


def darkness_test_job(stock: Stock, printer_cfg: dict, advanced: dict, family=None,
                      print_settings: dict | None = None) -> tuple[bytes, list]:
    """One job printing three labels at three darknesses, each saying which it is.

    Returns (job, [(word, value)]). Only sent from the "Darkness test" button.
    """
    from . import printsettings, render
    kind = printer_cfg.get("kind") or "tspl"
    now = printsettings.effective_darkness(kind, stock, print_settings, advanced, family)
    levels = printsettings.darkness_levels(kind, now)
    out = b""
    for word, value in levels:
        img = render.render_text_label([f"{word}: {value}", "Darkness test"], stock)
        img = printsettings.adjust_image(img, stock, print_settings)
        ps = dict(printsettings.clean(print_settings))
        ps["zpl_darkness" if kind == "zpl" else "darkness"] = value
        out += build_job(img, stock, printer_cfg, advanced, 1, family, ps)
    return out, levels


def feed_job(stock: Stock, printer_cfg: dict, advanced: dict,
             print_settings: dict | None = None) -> bytes:
    """Feed one blank label. Only sent from the "Feed one blank label" button."""
    from . import printsettings
    if printer_cfg.get("kind") == "zpl":
        return zpl.feed_job()
    v = printsettings.tspl_values(stock, print_settings, advanced or {})
    return tspl.feed_job(stock, v["gap_mm"], v["media"])


def send(cfg: dict, data: bytes, image=None, copies: int = 1) -> str:
    """Send a job. Returns an optional reply line (network). Raises PrinterError."""
    method, target = cfg.get("method", ""), cfg.get("target", "")
    if not method or not target:
        raise PrinterError(MSG_NO_PRINTER)
    dry = os.environ.get("FOOD_LABELER_DRY_RUN")
    if dry:
        p = Path(dry)
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"job-{int(time.time() * 1000)}-{method}.bin"
        f.write_bytes(data)
        log.info("dry run: wrote %s (%d bytes) instead of printing to %s", f, len(data), target)
        return ""
    log.info("printing %d bytes via %s to %s", len(data), method, target)
    try:
        if method == "windows_raw":
            send_windows_raw(target, data)
        elif method == "windows_driver":
            send_windows_driver(target, image, copies)
        elif method == "cups":
            send_cups(target, data)
        elif method == "device":
            send_device(target, data)
        elif method == "network":
            return send_network(target, data)
        else:
            raise PrinterError(MSG_NO_PRINTER)
    except PrinterError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("print failed")
        raise PrinterError(MSG_NOT_ANSWERING) from e
    return ""


def send_windows_raw(name: str, data: bytes, win32print=None) -> None:
    """Spool ``data`` as a RAW document: the driver passes our TSPL/ZPL through untouched."""
    w = win32print or _win32print()
    if w is None:
        raise PrinterError("Printing on Windows needs a part that is missing (pywin32). "
                           "Please ask your helper to reinstall Food Labeler.")
    try:
        h = w.OpenPrinter(name)
    except Exception as e:  # noqa: BLE001
        raise PrinterError(f"I can't find the printer “{name}”. Click "
                           "“Set up my printer” to choose it again.") from e
    try:
        w.StartDocPrinter(h, 1, ("Food Labeler", None, "RAW"))
        try:
            w.StartPagePrinter(h)
            w.WritePrinter(h, data)
            w.EndPagePrinter(h)
        finally:
            w.EndDocPrinter(h)
    finally:
        w.ClosePrinter(h)


def send_windows_driver(name: str, image, copies: int = 1) -> None:
    """Fallback: print the picture through the normal Windows driver (GDI)."""
    if image is None:
        raise PrinterError("There is nothing to print.")
    try:
        import win32con  # type: ignore
        import win32ui  # type: ignore
        from PIL import ImageWin
    except ImportError as e:
        raise PrinterError("Printing through the Windows driver isn't available "
                           "on this computer.") from e
    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(name)
    except Exception as e:  # noqa: BLE001
        raise PrinterError(f"I can't find the printer “{name}”.") from e
    try:
        pw, ph = hdc.GetDeviceCaps(win32con.HORZRES), hdc.GetDeviceCaps(win32con.VERTRES)
        img = image.convert("RGB")
        scale = min(pw / img.width, ph / img.height)
        w, h = int(img.width * scale), int(img.height * scale)
        x0, y0 = (pw - w) // 2, (ph - h) // 2
        hdc.StartDoc("Food Labeler")
        try:
            for _ in range(max(1, min(200, copies))):
                hdc.StartPage()
                ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (x0, y0, x0 + w, y0 + h))
                hdc.EndPage()
        except Exception:
            # Without this a failed job stays stuck in the Windows print queue.
            try:
                hdc.AbortDoc()
            except Exception:  # noqa: BLE001
                pass
            raise
        hdc.EndDoc()
    finally:
        hdc.DeleteDC()


def send_cups(queue: str, data: bytes, run=subprocess.run) -> None:
    """``lp -o raw`` through a temporary file (removed afterwards)."""
    fd, tmp = tempfile.mkstemp(prefix="food-labeler-", suffix=".prn")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        code, out, err = _run(["lp", "-d", queue, "-o", "raw", "-n", "1", tmp], run, timeout=30)
        if code != 0:
            log.error("lp failed (%s): %s %s", code, out, err)
            if "not exist" in err or "Unknown destination" in err or "No such" in err:
                raise PrinterError(f"I can't find the printer “{queue}”. Click "
                                   "“Set up my printer” to choose it again.")
            raise PrinterError(MSG_NOT_ANSWERING)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def send_device(path: str, data: bytes, opener=open) -> None:
    """Write straight to a device file such as /dev/usb/lp0 (needs the "lp" group)."""
    try:
        with opener(path, "wb", buffering=0) as f:
            f.write(data)
            f.flush()
    except PermissionError as e:
        raise PrinterError(MSG_PERMISSION) from e
    except FileNotFoundError as e:
        raise PrinterError(MSG_NOT_ANSWERING) from e
    except OSError as e:
        raise PrinterError(MSG_NOT_ANSWERING) from e


def parse_hostport(target: str, default_port: int = 9100) -> tuple[str, int]:
    """Split "host", "host:port" or "[ipv6]:port" into (host, port); 9100 is the raw-print port."""
    t = target.strip()
    if t.startswith("[") and "]" in t:          # [ipv6]:port
        host, _, rest = t[1:].partition("]")
        port = rest.lstrip(":")
    elif t.count(":") == 1:
        host, port = t.split(":")
    else:
        host, port = t, ""
    try:
        p = int(port) if port else default_port
    except ValueError:
        raise PrinterError("The printer address doesn't look right. "
                           "It should look like 192.168.1.50:9100") from None
    if not host or not (0 < p < 65536):
        raise PrinterError("The printer address doesn't look right. "
                           "It should look like 192.168.1.50:9100")
    return host, p


def send_network(target: str, data: bytes, connect=socket.create_connection,
                 reply_timeout: float = 1.5) -> str:
    """Send over raw TCP; return the first reply line if the printer sends one quickly."""
    host, port = parse_hostport(target)
    try:
        s = connect((host, port), timeout=5)
    except OSError as e:
        raise PrinterError(MSG_NOT_ANSWERING) from e
    reply = b""
    try:
        s.sendall(data)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        s.settimeout(reply_timeout)
        try:
            while b"\n" not in reply and len(reply) < 512:
                chunk = s.recv(256)
                if not chunk:
                    break
                reply += chunk
        except (socket.timeout, OSError):
            pass                       # a reply is optional; never wait for one
    except OSError as e:
        raise PrinterError(MSG_NOT_ANSWERING) from e
    finally:
        try:
            s.close()
        except OSError:
            pass
    return reply.decode("utf-8", "replace").splitlines()[0].strip() if reply.strip() else ""


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def status(p: Printer | None, name: str = "") -> tuple[str, str]:
    """('ready'|'problem'|'none', short text). Only looks; never prints or connects."""
    if p is None:
        return "none", "No printer found \u2014 click here to set it up"
    name = name or p.default_name()
    try:
        if p.method == "device":
            if not os.path.exists(p.target):
                return "problem", f"{name} \u2014 not plugged in or switched off"
            if not os.access(p.target, os.W_OK):
                return "problem", f"{name} \u2014 needs permission. Click here for help"
        elif p.method == "cups":
            code, out, _ = _run(["lpstat", "-p", p.target])
            if code == 0 and "disabled" in out:
                return "problem", f"{name} \u2014 paused. Click here for help"
        elif p.method in ("windows_raw", "windows_driver"):
            w = _win32print()
            if w is not None:
                h = w.OpenPrinter(p.target)
                try:
                    info = w.GetPrinter(h, 2)
                finally:
                    w.ClosePrinter(h)
                if (info.get("Status", 0) & 0x80) or (info.get("Attributes", 0) & 0x400):
                    return "problem", f"{name} \u2014 offline. Is it switched on?"
        elif p.method == "network":
            return "ready", f"{name} (network)"
    except Exception:  # noqa: BLE001
        log.exception("status check failed")
    return "ready", f"{name} \u2014 ready"
