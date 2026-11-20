"""List the USB devices plugged into this computer (for "My printer isn't in the list").

Linux reads /sys/bus/usb/devices. Windows asks PowerShell (no extra parts needed).
Nothing here ever sends anything to a device. Errors give an empty list.

This is a wider net than printers.discover(): it lists every USB device, not
just ones the system already treats as printers, so the user can unplug and
re-plug a printer and see which entry "just appeared", and so the report can
tell us the ids of a model we don't know yet.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

from .printers import parse_1284

log = logging.getLogger("food_labeler.usbscan")

CREATE_NO_WINDOW = 0x08000000


@dataclass
class UsbDevice:
    """One USB device as seen by the OS (no I/O with the device itself)."""

    key: str                  # stable while plugged in (port path / PnP instance id)
    vid: str = ""
    pid: str = ""
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    port: str = ""            # Linux port path such as 1-1.4
    is_printer: bool = False  # has a USB printer-class interface (07)
    ieee1284: dict = field(default_factory=dict)
    lp: str = ""              # Linux usbmisc node name (lp0) if bound to the printer driver
    pnp_class: str = ""       # Windows device class (Printer, USB, ...)
    family: object = None     # known.Definition, if it matches

    @property
    def vidpid(self) -> str:
        """USB id as lower-case "vvvv:pppp", or "" if unknown."""
        return f"{self.vid}:{self.pid}".lower() if self.vid and self.pid else ""

    def title(self) -> str:
        """Known model name if recognised, else what the device calls itself."""
        if self.family is not None:
            return self.family.display_name
        name = " ".join(x for x in [self.manufacturer, self.product] if x).strip()
        return name or "Unknown USB device"

    def describe(self) -> str:
        """Short technical line: printer-class, USB id, port."""
        bits = []
        if self.is_printer:
            bits.append("printer")
        if self.vidpid:
            bits.append(f"id {self.vidpid}")
        if self.port:
            bits.append(f"USB port {self.port}")
        return ", ".join(bits)


def _read(path) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(4096).decode("utf-8", "replace").strip().strip("\x00")
    except OSError:
        return ""


def scan_linux(sys_root: str = "/sys", known=None) -> list[UsbDevice]:
    """Read /sys/bus/usb/devices (sys_root is replaceable for tests)."""
    out = []
    base = os.path.join(sys_root, "bus", "usb", "devices")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    for n in names:
        if ":" in n or n.startswith("usb"):
            continue                     # interfaces and root hubs
        d = os.path.join(base, n)
        vid = _read(os.path.join(d, "idVendor"))
        if not vid:
            continue
        if _read(os.path.join(d, "bDeviceClass")) == "09":
            continue                     # hubs
        dev = UsbDevice(key=f"usb:{n}", vid=vid.lower(),
                        pid=_read(os.path.join(d, "idProduct")).lower(),
                        manufacturer=_read(os.path.join(d, "manufacturer")),
                        product=_read(os.path.join(d, "product")),
                        serial=_read(os.path.join(d, "serial")), port=n)
        for intf in sorted(glob.glob(os.path.join(d, f"{n}:*"))):
            if _read(os.path.join(intf, "bInterfaceClass")) == "07":
                dev.is_printer = True
            ident = _read(os.path.join(intf, "ieee1284_id"))
            if ident:
                dev.ieee1284 = parse_1284(ident)
            lps = glob.glob(os.path.join(intf, "usbmisc", "lp*"))
            if lps:
                dev.lp = os.path.basename(sorted(lps)[0])
        if known is not None:
            dev.family = known.match(dev.ieee1284, dev.vidpid,
                                     f"{dev.manufacturer} {dev.product}")
        out.append(dev)
    return out


PS_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -like 'USB\\VID_*' } | "
    "Select-Object DeviceID,Name,PNPClass,Manufacturer,Status | ConvertTo-Json -Compress"
)


def parse_windows_pnp(text: str, known=None) -> list[UsbDevice]:
    """Parse PS_SCRIPT's JSON (a list, or a bare object when there is only one)."""
    try:
        data = json.loads(text) if text.strip() else []
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        did = str(e.get("DeviceID") or "")
        m = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", did)
        if not m:
            continue
        if "&MI_" in did.upper():
            continue                     # interface of a composite device; parent is listed
        cls = str(e.get("PNPClass") or "")
        dev = UsbDevice(key=did, vid=m.group(1).lower(), pid=m.group(2).lower(),
                        manufacturer=str(e.get("Manufacturer") or ""),
                        product=str(e.get("Name") or ""),
                        serial=did.rsplit("\\", 1)[-1], pnp_class=cls,
                        is_printer=cls.lower() == "printer")
        if known is not None:
            dev.family = known.match({}, dev.vidpid, f"{dev.manufacturer} {dev.product}")
        out.append(dev)
    return out


def scan_windows(known=None, run=subprocess.run) -> list[UsbDevice]:
    """Ask PowerShell/CIM for USB PnP devices (no console window flashes up)."""
    try:
        r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
                capture_output=True, text=True, timeout=15,
                creationflags=CREATE_NO_WINDOW if sys.platform.startswith("win") else 0)
        return parse_windows_pnp(r.stdout or "", known)
    except (OSError, subprocess.SubprocessError, ValueError):
        log.exception("USB scan failed")
        return []


def scan(known=None) -> list[UsbDevice]:
    """All USB devices on this computer, matched against known models."""
    try:
        if sys.platform.startswith("win"):
            return scan_windows(known)
        return scan_linux(known=known)
    except Exception:  # noqa: BLE001 - never crash the app over a scan
        log.exception("USB scan failed")
        return []
