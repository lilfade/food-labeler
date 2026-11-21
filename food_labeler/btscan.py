"""List the Bluetooth printers that are already paired with this computer.

Nothing here connects to, pairs with or sends anything to a device. Pairing
is done by the person in the computer's own Bluetooth settings; this only
reads what the system already knows:

* Linux: ``bluetoothctl devices Paired`` (``bluetoothctl paired-devices`` on
  older BlueZ), then ``bluetoothctl info <address>`` for each one: name,
  device class, the services it offers (UUIDs), paired and connected. Both
  read BlueZ's own records and never reach the device.
* Windows: PowerShell lists the Bluetooth devices Windows knows (PnP ids
  starting ``BTHENUM``). A paired Serial Port Profile printer has an
  outgoing virtual COM port ("Standard Serial over Bluetooth link (COM5)")
  whose id carries the printer's address; the device's own entry carries
  its name.
* macOS: not supported (an empty list).

A device counts as a printer if its device class says Imaging / Printer
(major class 0x06 with the printer bit, as LP610BT units report 0x040680),
or if it offers the Serial Port Profile (UUID 0x1101) and its name matches a
model in known_printers.json. Everything else (phones, headphones…) is never
shown as a printer, and the printer report only counts it.

Errors and missing tools give an empty list; every command has a short
timeout and never opens a window.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from . import values
from .printers import LABEL_RE, Printer, classify, short_address

log = logging.getLogger("food_labeler.btscan")

CREATE_NO_WINDOW = 0x08000000
SPP = "1101"                          # Serial Port Profile
CMD_TIMEOUT = 3.0                     # seconds for one bluetoothctl call
TOTAL_TIMEOUT = 8.0                   # seconds for a whole scan
MAX_DEVICES = 32
MAC_RE = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02")
UUID_RE = re.compile(r"\(?0000([0-9A-Fa-f]{4})-0000-1000-8000-00805[Ff]9[Bb]34[Ff][Bb]\)?")


@dataclass
class BtDevice:
    """One paired Bluetooth device, as the system describes it (no I/O with it)."""

    address: str = ""          # "AA:BB:CC:DD:EE:FF" ("" if Windows didn't say)
    name: str = ""
    device_class: int | None = None   # Class of Device, e.g. 0x040680
    uuids: list = field(default_factory=list)   # 16-bit service ids, "1101"
    paired: bool | None = None
    connected: bool | None = None
    com_port: str = ""         # Windows: the outgoing COM port ("COM5"), if any
    family: object = None      # known.Definition, if the name matches one

    @property
    def key(self) -> str:
        return self.address or self.com_port

    @property
    def printer_class(self) -> bool:
        """Class of Device says Imaging (major class 6) with the printer bit."""
        c = self.device_class
        return c is not None and (c >> 8) & 0x1F == 0x06 and bool(c & 0x80)

    @property
    def spp(self) -> bool:
        """Offers the Serial Port Profile (on Windows: has an SPP COM port)."""
        return SPP in self.uuids or bool(self.com_port)

    @property
    def is_printer(self) -> bool:
        """A label printer we can try: printer class, or SPP plus a known name."""
        if self.printer_class:
            return True
        return self.spp and (self.family is not None or bool(LABEL_RE.search(self.name or "")))

    @property
    def short(self) -> str:
        """"…44:01": the only part of the address ever shown or reported."""
        return short_address(self.address) if self.address else ""

    def class_text(self) -> str:
        if self.device_class is None:
            return "?"
        return f"0x{self.device_class:06x}" + (" (printer)" if self.printer_class else "")


# ---------------------------------------------------------------------------
# Linux: bluetoothctl
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def parse_devices(text: str) -> list[tuple[str, str]]:
    """``bluetoothctl devices`` lines ("Device AA:BB:… Name") -> [(address, name)]."""
    out, seen = [], set()
    for line in _clean(text).splitlines():
        if re.search(r"\[(CHG|DEL)\]", line):
            continue                  # a change notice, not a device line
        m = re.search(r"(?:^|[\s#])Device\s+(" + MAC_RE.pattern + r")\s*(.*)$", line)
        if m and m.group(1).upper() not in seen:
            seen.add(m.group(1).upper())
            out.append((m.group(1).upper(), values.device_name(m.group(2))))
    return out


def _yes(v: str) -> bool | None:
    v = (v or "").strip().lower()
    return True if v == "yes" else False if v == "no" else None


def parse_info(text: str, address: str = "") -> BtDevice | None:
    """``bluetoothctl info <address>`` -> BtDevice (None if it says the device isn't there)."""
    t = _clean(text)
    if not t.strip() or "not available" in t.lower():
        return None
    d = BtDevice(address=address.upper())
    m = re.search(r"Device\s+(" + MAC_RE.pattern + ")", t)
    if m and not d.address:
        d.address = m.group(1).upper()
    for line in t.splitlines():
        k, sep, v = line.strip().partition(":")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if k == "Name" or (k == "Alias" and not d.name):
            d.name = values.device_name(v)
        elif k == "Class":
            cm = re.match(r"0x([0-9A-Fa-f]{1,8})", v)
            if cm:
                d.device_class = int(cm.group(1), 16) & 0xFFFFFF
        elif k == "Paired":
            d.paired = _yes(v)
        elif k == "Connected":
            d.connected = _yes(v)
        elif k == "UUID":
            um = UUID_RE.search(v)
            if um and um.group(1).upper() not in d.uuids:
                d.uuids.append(um.group(1).upper())
    return d


def _run(cmd, run, timeout):
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return -1, ""


def scan_linux(run=subprocess.run, which=shutil.which, known=None,
               clock=time.monotonic) -> list[BtDevice]:
    """Every paired Bluetooth device BlueZ knows, with its details.

    ``run`` (subprocess.run), ``which`` and ``clock`` are replaceable for tests."""
    if not which("bluetoothctl"):
        return []
    start = clock()
    code, out = _run(["bluetoothctl", "devices", "Paired"], run, CMD_TIMEOUT)
    pairs = parse_devices(out) if code == 0 else []
    if code != 0 or (not pairs and "invalid" in out.lower()):
        code, out = _run(["bluetoothctl", "paired-devices"], run, CMD_TIMEOUT)   # BlueZ < 5.65
        pairs = parse_devices(out) if code == 0 else []
    found = []
    for addr, name in pairs[:MAX_DEVICES]:
        if clock() - start > TOTAL_TIMEOUT:
            log.warning("Bluetooth scan took too long; stopped after %d devices", len(found))
            break
        code, out = _run(["bluetoothctl", "info", addr], run, CMD_TIMEOUT)
        d = parse_info(out, addr) if code == 0 else None
        if d is None:
            continue
        if d.paired is False:          # old BlueZ lists every device it has seen
            continue
        d.name = d.name or name
        if known is not None:
            d.family = known.match({}, "", d.name)
        found.append(d)
    return found


# ---------------------------------------------------------------------------
# Windows: PowerShell / CIM
# ---------------------------------------------------------------------------

PS_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'BTHENUM*' } | "
    "Select-Object PNPDeviceID,Name,Status | ConvertTo-Json -Compress"
)
COM_NAME_RE = re.compile(r"\((COM[1-9][0-9]{0,2})\)", re.I)
SPP_GUID = "{00001101-0000-1000-8000-00805F9B34FB}"


def _mac(hex12: str) -> str:
    h = hex12.upper()
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


def parse_windows(text: str, known=None) -> list[BtDevice]:
    """Parse PS_SCRIPT's JSON (a list, or a bare object when there is only one).

    Device entries (``BTHENUM\\DEV_<address>\\…``) give names; SPP COM port
    entries (``BTHENUM\\{00001101-…}_…\\…&<address>_C00000000``, named
    "… (COM5)") give the port. Incoming ports carry the address 000000000000
    and are skipped. The two are joined by address."""
    try:
        data = json.loads(text) if (text or "").strip() else []
    except (ValueError, RecursionError):
        return []
    if isinstance(data, dict):
        data = [data]
    names: dict[str, str] = {}
    ports: dict[str, str] = {}
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        did = str(e.get("PNPDeviceID") or e.get("DeviceID") or "").upper()
        name = str(e.get("Name") or "")
        m = re.match(r"BTHENUM\\DEV_([0-9A-F]{12})\b", did)
        if m:
            names.setdefault(_mac(m.group(1)), values.device_name(name))
            continue
        cm = COM_NAME_RE.search(name)
        if not cm or SPP_GUID not in did:
            continue
        am = re.search(r"&([0-9A-F]{12})_", did)
        if not am or am.group(1) == "000000000000":
            continue                  # an incoming port: nothing to print to
        ports.setdefault(_mac(am.group(1)), cm.group(1).upper())
    out = []
    for addr in list(dict.fromkeys(list(names) + list(ports))):
        d = BtDevice(address=addr, name=names.get(addr, ""), paired=True,
                     com_port=ports.get(addr, ""))
        if known is not None:
            d.family = known.match({}, "", d.name)
        out.append(d)
    return out


def scan_windows(known=None, run=subprocess.run) -> list[BtDevice]:
    """Ask PowerShell/CIM for paired Bluetooth devices (no console window flashes up)."""
    try:
        r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
                capture_output=True, text=True, timeout=15,
                creationflags=CREATE_NO_WINDOW if sys.platform.startswith("win") else 0)
        return parse_windows(r.stdout or "", known)
    except (OSError, subprocess.SubprocessError, ValueError):
        log.exception("Bluetooth scan failed")
        return []


# ---------------------------------------------------------------------------
# both
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache: tuple[float, list] | None = None


def scan(known=None) -> list[BtDevice]:
    """Every paired Bluetooth device on this computer ([] on macOS or on any error)."""
    try:
        if sys.platform.startswith("win"):
            devs = scan_windows(known)
        elif sys.platform.startswith("linux"):
            devs = scan_linux(known=known)
        else:
            devs = []
    except Exception:  # noqa: BLE001 - never crash the app over a scan
        log.exception("Bluetooth scan failed")
        devs = []
    return _remember(devs)


def _remember(devs: list) -> list:
    """Keep a scan result for scan_cached() and hand it back."""
    global _cache
    with _cache_lock:
        _cache = (time.monotonic(), list(devs))
    return devs


def scan_cached(known=None, max_age: float = 60.0) -> list[BtDevice]:
    """The last scan if it is at most ``max_age`` seconds old, else a new one."""
    with _cache_lock:
        c = _cache
    if c is not None and time.monotonic() - c[0] <= max_age:
        return list(c[1])
    return scan(known)


def to_printers(devs, known=None, windows: bool | None = None) -> list[Printer]:
    """Printers for the paired devices that are label printers.

    Linux: method "bluetooth" to the address. Windows: method "serial" to the
    device's COM port (a printer without one can't be reached yet and is left
    out). The id is ``bt:<address>`` (``bt:<COM port>`` if Windows gave no
    address). ``windows`` defaults to this computer's system (for tests)."""
    win = sys.platform.startswith("win") if windows is None else windows
    out = []
    for d in devs:
        if not d.is_printer:
            continue
        where = f"Bluetooth ({d.short})" if d.short else "Bluetooth"
        if d.com_port:
            pr = Printer(id=f"bt:{d.address or d.com_port}", model=d.name, method="serial",
                         target=d.com_port, port=f"Bluetooth {d.com_port} ({d.short})"
                         if d.short else f"Bluetooth {d.com_port}",
                         detail=f"Bluetooth COM port {d.com_port}", bluetooth=True)
        elif win or not d.address:
            continue
        else:
            pr = Printer(id=f"bt:{d.address}", model=d.name, method="bluetooth",
                         target=d.address, port=where, bluetooth=True,
                         detail=f"Bluetooth class {d.class_text()}, "
                                f"SPP {'yes' if d.spp else 'not listed'}")
        classify(pr, known, None, d.name)
        out.append(pr)
    return out


def merge(found: list[Printer], bt: list[Printer]) -> list[Printer]:
    """Add Bluetooth printers to the others. On Windows, a spooler printer on a
    Bluetooth COM port (the maker's driver installed on it) is the same
    printer: it keeps its entry (printing raw through Windows), is marked
    as Bluetooth, and the bare COM port entry is dropped."""
    out = list(found)
    have = {p.id for p in out}
    for b in bt:
        same = [p for p in out if b.method == "serial" and p.method.startswith("windows")
                and p.port.rstrip(":").upper() == b.target.upper()]
        if same:
            for p in same:
                p.bluetooth = True
                p.port = b.port
            continue
        if b.id not in have:
            out.append(b)
            have.add(b.id)
    return out


__all__ = ["BtDevice", "scan", "scan_cached", "scan_linux", "scan_windows", "parse_devices",
           "parse_info", "parse_windows", "to_printers", "merge"]
