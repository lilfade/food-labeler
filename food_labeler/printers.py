"""Finding printers and sending print jobs to them.

Connections ("methods"):
  windows_raw     Windows printer, raw bytes through the spooler (normal on Windows)
  windows_driver  Windows printer, picture printed through the maker's driver (fallback)
  cups            Linux/Mac CUPS queue, sent with `lp -o raw`
  device          Linux device file such as /dev/usb/lp0
  network         host:port raw TCP: a printer on the network, a print server or a
                  small network bridge in front of a USB printer ("Add a network
                  printer…"); tested on paper with an LP610BT behind a raw TCP bridge
  bluetooth       Bluetooth address, Classic SPP over an RFCOMM socket (Linux)
  serial          a serial port: the COM port Windows makes for a paired
                  Bluetooth printer ("COM5"), or a /dev/rfcommN-style device

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

Printers that only work through their maker's driver
------------------------------------------------------
Some cheap label printers don't take TSPL or ZPL at all; they only print
what the maker's own driver sends them. Their entry in known_printers.json
says ``"language": "driver"``. Unless the printer's IEEE 1284 id names a
language Food Labeler speaks, or the user picked a Type for it, such a
printer prints through the Windows driver ("windows_driver", as if the
"Print through Windows driver" switch were on). On Linux there is no such
path, so printing says plainly that it needs the maker's driver
(MSG_NEEDS_DRIVER) instead of sending something it can't print.

Tested and alpha printers
-------------------------
Only models with ``"verified_on_paper": true`` have been tried on real
labels. Every other printer, matched or not, is "alpha": its name carries
ALPHA_TAG wherever printers are listed, and the first print to it shows
ALPHA_NOTICE once (remembered per printer as ``"alpha_ok"``).

Bluetooth (alpha)
-----------------
LP610BT-type printers also speak Classic Bluetooth (the Serial Port Profile,
SPP), and take exactly the same TSPL bytes as over USB. Pairing is always
done by the person in the computer's own Bluetooth settings; Food Labeler
only lists printers that are already paired (btscan.py, which never
connects) and only connects when it prints.

* Linux: ``send_bluetooth`` opens an AF_BLUETOOTH/BTPROTO_RFCOMM socket to
  (address, channel). The channel is the one chosen in Advanced, else the
  one that worked last time, else 1, 2, 3 in turn (a wrong channel is
  refused at once, so trying the next is quick). The job goes out in
  chunks (``bt_chunk`` bytes, ``bt_delay_ms`` apart, per model in
  known_printers.json) because these printers have small buffers.
* Windows: a paired SPP printer gets an outgoing virtual COM port.
  ``send_serial`` writes to that port (``COM5``) in the same chunks. If the maker's
  driver is installed on that port, the printer is an ordinary Windows
  printer and ``windows_raw`` works as for USB.
* macOS is not supported.

The id is ``bt:<address>`` (``bt:COM5`` on Windows when the address can't be
read), so two printers that are both called "LP610BT" stay apart; the list
shows the last two bytes of the address ("Bluetooth (…44:01)").
Bluetooth is alpha even for a model tested over USB, until the model's entry
says ``"verified_bluetooth": true``.

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
import itertools
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

from . import tspl, values, zpl
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
    "bluetooth": "Bluetooth",
    "serial": "Bluetooth (COM port)",
}

MSG_NOT_ANSWERING = ("The printer isn't answering. Check it is switched on "
                     "and the cable is plugged in.")
MSG_NO_PRINTER = "No printer is set up yet. Click “Set up my printer”."
MSG_NEEDS_DRIVER = ("This printer only prints through its maker's own program (its "
                    "driver), so Food Labeler can't send labels to it directly. On Windows, "
                    "install the maker's driver and Food Labeler prints through it. On this "
                    "computer that isn't possible yet. If you'd like it to work, please tell "
                    "us: Settings → Get help with my printer → Ask for help on GitHub.")
ALPHA_TAG = "(alpha — not tested yet)"
ALPHA_NOTICE = ("This printer hasn't been tested with Food Labeler yet. It should work, but "
                "if it doesn't, please tell us on GitHub (Ask for help on GitHub).")
MSG_PERMISSION = ("This computer won't let Food Labeler use the printer yet. Ask your helper "
                  "to add you to the “lp” group, then log out and back in.")
ALPHA_NOTICE_BLUETOOTH = ("Printing over Bluetooth hasn't been tested with Food Labeler yet. It "
                          "should work, but if it doesn't, use the printer's USB cable instead, "
                          "and please tell us on GitHub (Ask for help on GitHub).")

MSG_BT_OFF = ("Bluetooth is switched off on this computer. Switch it on in the computer's "
              "Bluetooth settings, then try again.")
MSG_BT_UNAVAILABLE = ("Food Labeler can't use Bluetooth on this computer. Use the printer's "
                      "USB cable instead.")
MSG_BT_NOT_PAIRED = ("The printer isn't paired with this computer. Pair it in the computer's "
                     "Bluetooth settings (if it asks for a PIN, try 0000 or 1234), then press "
                     "“Look for printers again”.")
MSG_BT_AWAY = ("The printer isn't answering over Bluetooth. Check it is switched on and close "
               "to the computer, then try again.")
MSG_BT_PERMISSION = ("This computer won't let Food Labeler use Bluetooth. Ask your helper to "
                     "allow it, or use the printer's USB cable instead.")
MSG_BT_CHANNEL = ("The printer answered, but wouldn't take the label. Ask your helper to pick "
                  "its Bluetooth channel in Settings → Advanced.")
MSG_BT_BAD_ADDRESS = ("This printer's Bluetooth address doesn't look right, so nothing was "
                      "sent. Click “Set up my printer” to choose it again.")
MSG_SERIAL_MISSING = ("I can't find the printer's Bluetooth port. Check it is still paired in "
                      "the computer's Bluetooth settings, then press “Look for printers again”.")
MSG_SERIAL_BUSY = ("Another program is using the printer's Bluetooth port. Close it (the "
                   "printer maker's app, for example) and try again.")
BT_HELP = (
    "Printing over Bluetooth is new and hasn't been tested yet (alpha). The USB cable "
    "always works.\n\n"
    "1. Switch the printer on, close to the computer.\n"
    "2. Pair it in the computer's own Bluetooth settings. On Windows: Settings → "
    "Bluetooth & devices → Add device → Bluetooth, then pick the printer. On Linux: the "
    "Bluetooth settings of your desktop. If it asks for a PIN, try 0000 or 1234.\n"
    "3. Come back to Food Labeler and press “Look for printers again”. The printer "
    "shows up with “Bluetooth” and the end of its address after its name.\n\n"
    "Food Labeler never pairs by itself. Two printers with the same name? The end of "
    "the address tells them apart: in My printers, press “Which one is it?” and give "
    "each one a name.")


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
    bluetooth: bool = False  # reached over Bluetooth (its own "alpha" until tested)

    def __post_init__(self):
        # Names come from the printer itself or the system (USB strings, Windows
        # and CUPS names, Bluetooth names): one tidy line each, never a whole page.
        # ``target`` and ``queue`` stay exact: they are what the job is sent to.
        self.model = values.device_name(self.model)
        self.port = values.device_name(self.port)
        self.detail = values.device_name(self.detail, 400)

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

    def display(self, nickname: str = "", tag: bool = False) -> str:
        """Name plus where it is ("… — USB port 1-1.4"), so identical units differ.

        ``tag``: add "(alpha — not tested yet)" for a printer we haven't tested."""
        name = values.device_name(nickname or self.default_name()) or "Printer"
        if tag and self.alpha:
            name = f"{name} {ALPHA_TAG}"
        return f"{name} \u2014 {self.port}" if self.port else name

    @property
    def alpha(self) -> bool:
        """Not a model we have tested on paper (unknown printers included), or a
        tested model reached a way it hasn't been tested on paper yet (Bluetooth,
        or the network for models without ``verified_network``)."""
        if not getattr(self.family, "verified_on_paper", False):
            return True
        if self.method == "network" and not getattr(self.family, "verified_network", False):
            return True
        return self.bluetooth and not getattr(self.family, "verified_bluetooth", False)

    @property
    def driver_only(self) -> bool:
        """Matched a model that only prints through its maker's driver, and nothing
        (its 1284 id) says it speaks TSPL or ZPL."""
        return bool(getattr(self.family, "driver_only", False)) and not self.kind

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
            out[values.device_name(k, 40).upper()] = values.device_name(v, 200)
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
    if not p.kind and p.family is not None and p.family.language != "driver":
        p.kind = p.family.language
    if not p.kind and not getattr(p.family, "driver_only", False):
        p.kind = kind_from_text(text)


def printer_config(p: "Printer", info: dict | None = None) -> dict:
    """Printer.config() with the user's choices for it (settings ``printers[id]``):
    language ("Type"), the Windows "print through driver" switch, and the
    driver path for printers that only work through their maker's driver."""
    info = info or {}
    cfg = p.config(info.get("kind") or "")
    if p.method == "windows_raw" and (info.get("via_driver")
                                      or (p.driver_only and not info.get("kind"))):
        cfg["method"] = "windows_driver"      # the picture through the maker's driver
    elif p.driver_only and not info.get("kind") and p.method in ("device", "cups",
                                                                  "bluetooth", "serial"):
        cfg["method"] = "needs_driver"        # send() says so plainly; nothing is sent
    if p.method in ("bluetooth", "serial"):
        chunk = getattr(p.family, "bt_chunk", 0) or BT_CHUNK
        delay = getattr(p.family, "bt_delay_ms", None)
        cfg["bt_chunk"] = chunk
        cfg["bt_delay_ms"] = BT_DELAY_MS if delay is None else delay
    if p.method == "bluetooth":
        cfg["channel"] = bt_channel_or_none(info.get("bt_channel"))
        cfg["channel_hint"] = bt_channel_or_none(info.get("bt_channel_found"))
    return cfg


def alpha_notice_due(p: "Printer | None", info: dict | None = None) -> bool:
    """True the first time something is printed to an untested ("alpha") printer."""
    return p is not None and p.alpha and not (info or {}).get("alpha_ok")


def alpha_notice(p: "Printer | None") -> str:
    """The one-time "not tested yet" message for this printer."""
    return ALPHA_NOTICE_BLUETOOTH if p is not None and p.bluetooth else ALPHA_NOTICE


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


def discover(known=None, bt_max_age: float = 0) -> list[Printer]:
    """All printers on this computer, paired Bluetooth printers included.

    Slow-ish: the app calls it off the UI thread. Windows that call it
    directly pass ``bt_max_age`` (seconds) to reuse a recent Bluetooth list
    instead of asking the system again."""
    found = discover_windows(known=known) if IS_WINDOWS else discover_linux(known=known)
    try:
        from . import btscan
        devs = btscan.scan_cached(known, bt_max_age) if bt_max_age else btscan.scan(known)
        found = btscan.merge(found, btscan.to_printers(devs, known))
    except Exception:  # noqa: BLE001 - never lose the USB printers over Bluetooth
        log.exception("Bluetooth discovery failed")
    return found


def network_printer(target: str, kind: str = "tspl", family=None) -> Printer:
    """A printer reached by raw TCP at "host:port" (added with "Add a network printer…").

    ``family`` is the kind of printer the person said it is (a known.Definition),
    which decides whether it counts as tested (see Printer.alpha)."""
    host, port = parse_hostport(target)
    p = Printer(id=f"net:{host}:{port}", kind=kind if kind in KINDS else "tspl", model="",
                method="network", target=f"{host}:{port}", port=f"network {host}:{port}",
                manual=True, family=family)
    if family is not None:
        p.dpi = family.dpi
    return p


# The choices in "Add a network printer…": (words, language, known model id).
NETWORK_TYPES = [
    ("Label printer like the LP610BT", "tspl", "lp610bt-compatible"),
    ("Zebra label printer", "zpl", "zebra-zpl"),
    ("Another label printer (TSPL)", "tspl", ""),
]
NETWORK_HELP = (
    "Use this for a label printer on your network: one with its own network "
    "socket, one plugged into a print server, or one behind a small network "
    "bridge. Type its address the way your helper or the print server's own page "
    "shows it, like 192.168.1.50:9100. The part before the colon is where the "
    "printer is on your network; the number after it is the port (often 9100). "
    "\u201cTest the connection\u201d only checks that something answers there; it "
    "never prints anything.")
NETWORK_TEST_TIMEOUT = 3.0          # seconds "Test the connection" waits


def network_printers(cfg_printers: dict, known=None) -> list[Printer]:
    """The network printers the person added (settings ``printers[id]`` with
    ``"manual": true``), in the order they were added. Damaged entries are skipped."""
    out = []
    for pid, info in (cfg_printers or {}).items():
        if not (isinstance(info, dict) and info.get("manual") and info.get("target")):
            continue
        fam = known.get(info.get("model")) if known is not None and info.get("model") else None
        try:
            p = network_printer(str(info["target"]), info.get("kind") or "tspl", fam)
        except PrinterError:
            continue
        p.id = pid
        out.append(p)
    return out


def add_network_printer(cfg_printers: dict, target: str, kind: str = "tspl", model: str = "",
                        nickname: str = "") -> Printer:
    """Remember a network printer in settings (``printers`` dict). Returns it.

    The address is checked (PrinterError with a plain message if it doesn't
    look right). Adding the same address again updates it."""
    p = network_printer(target, kind)
    info = cfg_printers.setdefault(p.id, {})
    info.update({"manual": True, "method": "network", "target": p.target,
                 "kind": p.kind})
    if model:
        info["model"] = str(model)[:64]
    else:
        info.pop("model", None)
    if nickname.strip():
        info["nickname"] = nickname.strip()[:60]
    return p


def remove_network_printer(cfg: dict, pid: str) -> None:
    """Forget a network printer (and stop using it if it was chosen)."""
    info = cfg["printers"].get(pid)
    if isinstance(info, dict) and info.get("manual"):
        cfg["printers"].pop(pid, None)
        if cfg["selected"] == pid:
            cfg["selected"] = ""


def check_network(target: str, connect=None, timeout: float = NETWORK_TEST_TIMEOUT) -> str:
    """"Test the connection": open a connection to host:port and close it again.

    Nothing is sent, so nothing can print. Returns a plain sentence saying
    what happened; raises PrinterError only for an address that doesn't look
    right."""
    host, port = parse_hostport(target)
    if connect is None:
        connect = socket.create_connection
    try:
        s = connect((host, port), timeout=timeout)
    except socket.timeout:
        return (f"Nothing answered at {host}:{port}. Check the printer (and its print "
                "server or bridge) is switched on and on the same network as this "
                "computer, and that the address is right.")
    except ConnectionRefusedError:
        return (f"{host} answered, but not on port {port}. Check the number after the "
                "colon (it is often 9100).")
    except OSError:
        return (f"I couldn't reach {host}. Check the address, and that this computer "
                "is on the same network as the printer.")
    try:
        s.close()
    except OSError:
        pass
    return f"\u2714 Something answered at {host}:{port}. Nothing was printed."


def auto_pick(found: list[Printer]) -> Printer | None:
    """Pick a label printer only if there is exactly one that looks like one.

    A cable beats Bluetooth: a printer that is both plugged in and paired is
    picked on its cable, and a Bluetooth printer is only picked by itself
    when it is the only label printer there is."""
    matches = [p for p in found if p.matches and not p.bluetooth]
    if not matches:
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


_DRY_RUN_COUNT = itertools.count(1)


def send(cfg: dict, data: bytes, image=None, copies: int = 1) -> str:
    """Send a job. Returns an optional reply line (network). Raises PrinterError."""
    method, target = cfg.get("method", ""), cfg.get("target", "")
    if not method or not target:
        raise PrinterError(MSG_NO_PRINTER)
    if method == "needs_driver":
        raise PrinterError(MSG_NEEDS_DRIVER)
    dry = os.environ.get("FOOD_LABELER_DRY_RUN")
    if dry:
        p = Path(dry)
        p.mkdir(parents=True, exist_ok=True)
        # a number after the time, so jobs sent in the same millisecond each get a file
        f = p / f"job-{int(time.time() * 1000)}-{next(_DRY_RUN_COUNT):04d}-{method}.bin"
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
        elif method == "bluetooth":
            send_bluetooth(target, data, channel=cfg.get("channel"),
                           hint=cfg.get("channel_hint"),
                           chunk=cfg.get("bt_chunk") or BT_CHUNK,
                           delay_ms=cfg.get("bt_delay_ms", BT_DELAY_MS))
        elif method == "serial":
            send_serial(target, data, chunk=cfg.get("bt_chunk") or BT_CHUNK,
                        delay_ms=cfg.get("bt_delay_ms", BT_DELAY_MS))
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
        raise PrinterError("This printer prints through its Windows driver, which can only "
                           "print labels. Use the printer's own feed button instead.")
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


MSG_NOT_A_DEVICE = ("This printer's settings point somewhere that isn't a printer, so "
                    "nothing was sent. Click “Set up my printer” to choose it again.")


def device_path_ok(path: str, dev_root: str = "/dev") -> bool:
    """True if ``path`` is a device file under /dev (also after following links).

    The target comes from settings.json, so it is checked before anything is
    written: a direct USB printer is always /dev/usb/lpN or a udev link in /dev."""
    if not path or "\x00" in path or not os.path.isabs(path):
        return False
    root = os.path.normpath(dev_root) + os.sep
    if ".." in Path(path).parts:
        return False
    return (os.path.normpath(path).startswith(root)
            and os.path.realpath(path).startswith(os.path.realpath(dev_root) + os.sep))


def send_device(path: str, data: bytes, opener=open, dev_root: str = "/dev") -> None:
    """Write straight to a device file such as /dev/usb/lp0 (needs the "lp" group).

    Anything that isn't under /dev is refused without being opened."""
    if not device_path_ok(path, dev_root):
        log.error("refusing to print to %r: not a device under %s", path, dev_root)
        raise PrinterError(MSG_NOT_A_DEVICE)
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


MSG_NET_NOT_ANSWERING = ("The printer isn't answering at {addr}. Check it (and its print "
                         "server or bridge) is switched on and on the same network as this "
                         "computer. My printers \u2192 Add a network printer\u2026 can test "
                         "the connection.")


def send_network(target: str, data: bytes, connect=socket.create_connection,
                 reply_timeout: float = 1.5, clock=time.monotonic) -> str:
    """Send over raw TCP; return the first reply line if the printer sends one quickly.

    ``reply_timeout`` is the whole time spent waiting for a reply, however it
    arrives: something that sends one byte at a time can't hold the print up."""
    host, port = parse_hostport(target)
    try:
        s = connect((host, port), timeout=5)
    except OSError as e:
        raise PrinterError(MSG_NET_NOT_ANSWERING.format(addr=f"{host}:{port}")) from e
    reply = b""
    try:
        s.sendall(data)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        deadline = clock() + reply_timeout
        try:
            while b"\n" not in reply and len(reply) < 512:
                left = deadline - clock()
                if left <= 0:
                    break
                s.settimeout(left)
                chunk = s.recv(256)
                if not chunk:
                    break
                reply += chunk
        except (socket.timeout, OSError):
            pass                       # a reply is optional; never wait for one
    except OSError as e:
        raise PrinterError(MSG_NET_NOT_ANSWERING.format(addr=f"{host}:{port}")) from e
    finally:
        try:
            s.close()
        except OSError:
            pass
    return reply.decode("utf-8", "replace").splitlines()[0].strip() if reply.strip() else ""


# ---------------------------------------------------------------------------
# Bluetooth (alpha): RFCOMM socket (Linux) and serial / COM port (Windows)
# ---------------------------------------------------------------------------

BT_CHUNK = 4096            # bytes per write unless the model says otherwise
BT_DELAY_MS = 20           # pause between writes unless the model says otherwise
BT_CONNECT_TIMEOUT = 8.0   # seconds to reach the printer
BT_SEND_TIMEOUT = 30.0     # seconds for one chunk to go out
BT_SETTLE_S = 0.5          # let the last bytes leave before closing
BT_CHANNELS = (1, 2, 3)    # RFCOMM channels tried when none is known
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
COM_RE = re.compile(r"^COM[1-9][0-9]{0,2}$", re.I)

# The RFCOMM channel that worked, per address, while the program runs; the
# window copies it into the printer's settings ("bt_channel_found").
LEARNED_CHANNELS: dict[str, int] = {}

# errno / Windows socket error numbers, by what they mean to the person
_BT_OFF_ERRNOS = {19, 99, 100, 113, 10050, 10065}         # ENODEV EADDRNOTAVAIL ENETDOWN
                                                         # EHOSTUNREACH, WSAENETDOWN/UNREACH
_BT_AWAY_ERRNOS = {104, 103, 110, 112, 10053, 10054, 10060, 10064}  # reset, timeout, host down
_BT_PAIR_ERRNOS = {13, 52, 10013}                         # EACCES / EBADE: no or bad pairing
_BT_REFUSED_ERRNOS = {111, 10061}


def bt_channel_or_none(v) -> int | None:
    """A valid RFCOMM channel (1-30) from settings, else None."""
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 30 else None


def parse_bt_target(target: str) -> tuple[str, int | None]:
    """"AA:BB:CC:DD:EE:FF" or "AA:BB:CC:DD:EE:FF/2" -> (address upper-case, channel)."""
    t = str(target or "").strip()
    addr, _, ch = t.partition("/")
    if not MAC_RE.match(addr):
        raise PrinterError(MSG_BT_BAD_ADDRESS)
    channel = None
    if ch:
        channel = bt_channel_or_none(ch)
        if channel is None:
            raise PrinterError(MSG_BT_BAD_ADDRESS)
    return addr.upper(), channel


def short_address(addr: str) -> str:
    """The last two bytes of a Bluetooth address, "…44:01" (all the list shows)."""
    parts = str(addr or "").upper().replace("-", ":").split(":")
    if len(parts) == 6:
        return "…" + ":".join(parts[-2:])
    hexes = re.sub(r"[^0-9A-F]", "", str(addr or "").upper())
    return f"…{hexes[-4:-2]}:{hexes[-2:]}" if len(hexes) == 12 else ""


def bluetooth_switched_off(sys_root: str = "/sys") -> bool:
    """True if Linux says plainly that Bluetooth is off: there is no adapter, or
    every Bluetooth radio is blocked (rfkill). Only reads /sys; False if unsure."""
    if not sys.platform.startswith("linux") and sys_root == "/sys":
        return False
    try:
        adapters = [n for n in os.listdir(os.path.join(sys_root, "class", "bluetooth"))
                    if re.fullmatch(r"hci\d+", n)]
    except OSError:
        adapters = []
    radios = []
    base = os.path.join(sys_root, "class", "rfkill")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    for n in names:
        d = os.path.join(base, n)
        if _read(os.path.join(d, "type")).strip() != "bluetooth":
            continue
        blocked = (_read(os.path.join(d, "soft")).strip() == "1"
                   or _read(os.path.join(d, "hard")).strip() == "1")
        radios.append(blocked)
    if radios and all(radios):
        return True
    return not adapters and not radios and os.path.isdir(os.path.join(sys_root, "class"))


def _bt_socket():
    """A new RFCOMM socket. Raises PrinterError if this Python has no Bluetooth."""
    fam = getattr(socket, "AF_BLUETOOTH", None)
    proto = getattr(socket, "BTPROTO_RFCOMM", None)
    if fam is None or proto is None:
        raise PrinterError(MSG_BT_UNAVAILABLE)
    try:
        return socket.socket(fam, socket.SOCK_STREAM, proto)
    except PermissionError as e:
        raise PrinterError(MSG_BT_PERMISSION) from e
    except OSError as e:
        # EAFNOSUPPORT: no Bluetooth in this system at all
        raise PrinterError(MSG_BT_OFF if bluetooth_switched_off() else MSG_BT_UNAVAILABLE) from e


def _errno_of(e: BaseException) -> int | None:
    return getattr(e, "winerror", None) or getattr(e, "errno", None)


def _bt_message(e: BaseException) -> str:
    """The plain message for a failed Bluetooth connect or send."""
    if isinstance(e, socket.timeout) or isinstance(e, TimeoutError):
        return MSG_BT_AWAY
    n = _errno_of(e)
    if n in _BT_OFF_ERRNOS:
        return MSG_BT_OFF
    if n in _BT_PAIR_ERRNOS:
        return MSG_BT_NOT_PAIRED
    if n in _BT_REFUSED_ERRNOS:
        return MSG_BT_CHANNEL
    return MSG_BT_AWAY


def _close(s) -> None:
    try:
        s.close()
    except OSError:
        pass


def _send_chunks(write, data: bytes, chunk: int, delay_ms: int, sleep) -> None:
    """write(piece) for each ``chunk``-byte piece, with ``delay_ms`` between them."""
    chunk = max(1, int(chunk or BT_CHUNK))
    pause = max(0, int(delay_ms or 0)) / 1000.0
    for i in range(0, len(data), chunk):
        if i and pause:
            sleep(pause)
        write(data[i:i + chunk])


def send_bluetooth(target: str, data: bytes, channel: int | None = None,
                   hint: int | None = None, chunk: int = BT_CHUNK,
                   delay_ms: int = BT_DELAY_MS, make_socket=None, sleep=time.sleep,
                   sys_root: str = "/sys") -> int:
    """Send a job over Classic Bluetooth (SPP, RFCOMM). Returns the channel used.

    ``channel`` (from Advanced, or "/N" in the target) is the only one tried
    when given. Otherwise ``hint`` (the channel that worked last time) is
    tried first, then 1, 2, 3; a refused channel moves on to the next at
    once, anything else stops with a plain message. ``make_socket`` and
    ``sleep`` are replaceable for tests."""
    addr, fixed = parse_bt_target(target)
    fixed = fixed or bt_channel_or_none(channel)
    if fixed:
        order = [fixed]
    else:
        first = bt_channel_or_none(hint) or LEARNED_CHANNELS.get(addr)
        order = ([first] if first else []) + [c for c in BT_CHANNELS if c != first]
    if make_socket is None:
        make_socket = _bt_socket
        if bluetooth_switched_off(sys_root):
            raise PrinterError(MSG_BT_OFF)
    last: BaseException | None = None
    for ch in order:
        s = make_socket()
        try:
            s.settimeout(BT_CONNECT_TIMEOUT)
            s.connect((addr, ch))
        except OSError as e:
            _close(s)
            last = e
            if isinstance(e, ConnectionRefusedError) or _errno_of(e) in _BT_REFUSED_ERRNOS:
                log.info("Bluetooth channel %s refused, trying the next", ch)
                continue
            log.warning("Bluetooth connect failed: %s", e)
            raise PrinterError(_bt_message(e)) from e
        try:
            s.settimeout(BT_SEND_TIMEOUT)
            _send_chunks(s.sendall, data, chunk, delay_ms, sleep)
            sleep(BT_SETTLE_S)
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        except OSError as e:
            log.warning("Bluetooth send failed: %s", e)
            raise PrinterError(_bt_message(e)) from e
        finally:
            _close(s)
        LEARNED_CHANNELS[addr] = ch
        log.info("sent %d bytes over Bluetooth channel %s", len(data), ch)
        return ch
    log.warning("Bluetooth: every channel refused (%s)", last)
    raise PrinterError(MSG_BT_CHANNEL) from last


def serial_path(target: str, dev_root: str = "/dev", windows: bool | None = None) -> str:
    """Where to write for method "serial": "\\\\.\\COM5" on Windows (COM1-COM999
    only), a device under /dev elsewhere. Raises PrinterError for anything else."""
    t = str(target or "").strip()
    win = IS_WINDOWS if windows is None else windows
    if win:
        if not COM_RE.match(t):
            raise PrinterError(MSG_NOT_A_DEVICE)
        return "\\\\.\\" + t.upper()
    if not device_path_ok(t, dev_root):
        raise PrinterError(MSG_NOT_A_DEVICE)
    return t


def send_serial(target: str, data: bytes, chunk: int = BT_CHUNK, delay_ms: int = BT_DELAY_MS,
                opener=open, sleep=time.sleep, dev_root: str = "/dev",
                windows: bool | None = None) -> None:
    """Write a job to a serial port, in chunks: the COM port Windows made for a
    paired Bluetooth printer (baud rate doesn't matter on those), or a
    /dev/rfcommN-style device. Opening the port is what connects to the printer."""
    path = serial_path(target, dev_root, windows)
    try:
        # "r+b", not "wb": Windows only opens a COM port as an existing file
        # (OPEN_EXISTING); "wb" would ask to create or empty it.
        with opener(path, "r+b", buffering=0) as f:
            _send_chunks(f.write, data, chunk, delay_ms, sleep)
            f.flush()
    except FileNotFoundError as e:
        raise PrinterError(MSG_SERIAL_MISSING) from e
    except PermissionError as e:
        raise PrinterError(MSG_SERIAL_BUSY if (IS_WINDOWS if windows is None else windows)
                           else MSG_PERMISSION) from e
    except OSError as e:
        log.warning("serial send failed: %s", e)
        raise PrinterError(MSG_BT_AWAY) from e


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
        elif p.method in ("bluetooth", "serial"):
            # Never connect just to look: it would wake the printer.
            if p.method == "bluetooth" and bluetooth_switched_off():
                return "problem", f"{name} — Bluetooth is switched off on this computer"
            return "ready", f"{name} (Bluetooth)"
    except Exception:  # noqa: BLE001
        log.exception("status check failed")
    return "ready", f"{name} \u2014 ready"
