import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Tests that build a fake Linux /sys tree out of symlinks (Linux discovery,
# USB scan). They test Linux-only code and need POSIX symlinks.
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="fake sysfs tree: Linux only")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Keep tests away from the real user folders and from any real printer."""
    monkeypatch.setenv("FOOD_LABELER_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("FOOD_LABELER_LABELS", str(tmp_path / "labels"))
    monkeypatch.setenv("FOOD_LABELER_DRY_RUN", str(tmp_path / "jobs"))
    import socket

    def no_network(*a, **k):
        raise AssertionError("tests must never open a real network connection")
    monkeypatch.setattr(socket, "create_connection", no_network)
    yield


def make_fake_sysfs(root: Path):
    """Two identical LP610BT clones (ports 1-1.3 and 1-1.4) and a Zebra ZP450 (1-1.2)."""
    sysr = root / "sys"
    devr = root / "dev"
    (devr / "usb").mkdir(parents=True)
    hub = sysr / "devices" / "platform" / "usb1" / "1-1"
    units = [
        ("1-1.3", "lp0", "0483", "2025", "STMicroelectronics", "BAR PRINTER", "000000000004",
         "MFG:Polono;CMD:TSPL2;MDL:4B-LP610BT;CLS:PRINTER;"),
        ("1-1.4", "lp1", "0483", "2025", "STMicroelectronics", "BAR PRINTER", "000000000004",
         "MFG:Polono;CMD:TSPL2;MDL:4B-LP610BT;CLS:PRINTER;"),
        ("1-1.2", "lp2", "0a5f", "008c", "Zebra Technologies", "ZTC ZP 450-200dpi", "41J1234",
         "MANUFACTURER:Zebra Technologies;COMMAND SET:ZPL;MODEL:ZTC ZP 450-200dpi;"
         "CLASS:PRINTER;OPTIONS:INTPSRVR;"),
    ]
    (sysr / "class" / "usbmisc").mkdir(parents=True)
    (sysr / "bus" / "usb" / "devices").mkdir(parents=True)
    for port, lp, vid, pid, mfg, prod, serial, ident in units:
        d = hub / port
        intf = d / f"{port}:1.0"
        (intf / "usbmisc" / lp).mkdir(parents=True)
        for name, val in [("idVendor", vid), ("idProduct", pid), ("manufacturer", mfg),
                          ("product", prod), ("serial", serial), ("bDeviceClass", "00")]:
            (d / name).write_text(val + "\n")
        (intf / "bInterfaceClass").write_text("07\n")
        (intf / "ieee1284_id").write_text(ident)
        os.symlink(intf, intf / "usbmisc" / lp / "device")
        os.symlink(intf / "usbmisc" / lp, sysr / "class" / "usbmisc" / lp)
        os.symlink(d, sysr / "bus" / "usb" / "devices" / port)
        os.symlink(intf, sysr / "bus" / "usb" / "devices" / f"{port}:1.0")
        (devr / "usb" / lp).write_bytes(b"")
    # a non-printer (keyboard) and a hub
    kb = hub / "1-1.1"
    kb.mkdir()
    for name, val in [("idVendor", "046d"), ("idProduct", "c31c"), ("manufacturer", "Logitech"),
                      ("product", "USB Keyboard"), ("bDeviceClass", "00")]:
        (kb / name).write_text(val)
    os.symlink(kb, sysr / "bus" / "usb" / "devices" / "1-1.1")
    (hub / "idVendor").write_text("1d6b")
    (hub / "bDeviceClass").write_text("09")
    os.symlink(hub, sysr / "bus" / "usb" / "devices" / "1-1")
    # udev nickname for the white one (port 1-1.4)
    os.symlink("usb/lp1", devr / "lp610bt-white")
    return sysr, devr


class FakeRun:
    """Stands in for subprocess.run: answers lpstat, records lp."""

    def __init__(self, lpstat_v="", lpstat_e="", lp_rc=0, lp_err=""):
        self.lpstat_v, self.lpstat_e = lpstat_v, lpstat_e
        self.lp_rc, self.lp_err = lp_rc, lp_err
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))

        class R:
            pass
        r = R()
        r.returncode, r.stdout, r.stderr = 0, "", ""
        if cmd[:2] == ["lpstat", "-v"]:
            r.stdout = self.lpstat_v
        elif cmd[:2] == ["lpstat", "-e"]:
            r.stdout = self.lpstat_e
        elif cmd[0] == "lp":
            self.sent = Path(cmd[-1]).read_bytes()
            r.returncode, r.stderr = self.lp_rc, self.lp_err
        return r
