import os

import pytest
from PIL import Image

from food_labeler import known, printers, stocks
from conftest import FakeRun, linux_only, make_fake_sysfs

K = known.KnownPrinters()


@linux_only
def test_linux_two_identical_clones_and_zebra(tmp_path):
    sysr, devr = make_fake_sysfs(tmp_path)
    found = printers.discover_linux(str(sysr), str(devr), run=FakeRun(), known=K)
    by_id = {p.id: p for p in found}
    assert set(by_id) == {"usb:1-1.2", "usb:1-1.3", "usb:1-1.4"}
    a, b, z = by_id["usb:1-1.3"], by_id["usb:1-1.4"], by_id["usb:1-1.2"]
    assert a.kind == b.kind == "tspl" and z.kind == "zpl"
    assert a.vidpid == "0483:2025" and z.vidpid == "0a5f:008c"
    assert a.family.id == "lp610bt-compatible" and z.family.id == "zebra-zp450"
    assert a.display() == ("LP610BT-compatible label printer (Labelnize / Flexyva / Polono…)"
                           " — USB port 1-1.3")
    assert z.display() == "Zebra ZP450 — USB port 1-1.2"
    # the udev nickname is preferred over the lpN node, which changes across boots
    assert b.target == str(devr / "lp610bt-white")
    assert a.target == str(devr / "usb" / "lp0")
    assert all(p.method == "device" for p in found)


@linux_only
def test_identity_stable_when_lp_numbers_change(tmp_path):
    sysr, devr = make_fake_sysfs(tmp_path)
    ids1 = {p.id: p.model for p in printers.discover_linux(str(sysr), str(devr), FakeRun(), K)}
    # swap lp numbering: rename class links
    cls = sysr / "class" / "usbmisc"
    t0, t1 = os.readlink(cls / "lp0"), os.readlink(cls / "lp1")
    os.unlink(cls / "lp0"); os.unlink(cls / "lp1")
    os.symlink(t1, cls / "lp0"); os.symlink(t0, cls / "lp1")
    ids2 = {p.id: p.model for p in printers.discover_linux(str(sysr), str(devr), FakeRun(), K)}
    assert ids1 == ids2


@linux_only
def test_cups_queue_merges_with_device(tmp_path):
    sysr, devr = make_fake_sysfs(tmp_path)
    run = FakeRun(lpstat_v=(f"device for white: tspl://{devr}/lp610bt-white\n"
                            "device for zebra: usb://Zebra%20Technologies/ZTC%20ZP%20450-200dpi?serial=41J1234\n"
                            "device for office: ipp://10.9.9.9/ipp/print\n"),
                  lpstat_e="white\nzebra\noffice\n")
    # paths in the uri are under the fake /dev root: rewrite to /dev/... form
    run.lpstat_v = run.lpstat_v.replace(f"tspl://{devr}", "tspl:///dev")
    found = printers.discover_linux(str(sysr), str(devr), run=run, known=K)
    by_id = {p.id: p for p in found}
    assert by_id["usb:1-1.4"].method == "cups" and by_id["usb:1-1.4"].target == "white"
    assert by_id["usb:1-1.2"].method == "cups" and by_id["usb:1-1.2"].target == "zebra"
    assert by_id["usb:1-1.3"].method == "device"
    assert "cups:office" in by_id and by_id["cups:office"].kind == ""
    assert len(found) == 4


class FakeWin:
    PRINTER_ENUM_LOCAL = 2
    PRINTER_ENUM_CONNECTIONS = 4

    def __init__(self, printers_):
        self._p = printers_
        self.calls = []

    def EnumPrinters(self, flags, name, level):
        assert level == 2
        return self._p

    def OpenPrinter(self, name):
        if name not in [p["pPrinterName"] for p in self._p]:
            raise OSError("no such printer")
        self.calls.append(("open", name))
        return 7

    def StartDocPrinter(self, h, level, info):
        self.calls.append(("doc", info))

    def StartPagePrinter(self, h):
        self.calls.append(("page",))

    def WritePrinter(self, h, data):
        self.calls.append(("write", data))

    def EndPagePrinter(self, h):
        self.calls.append(("endpage",))

    def EndDocPrinter(self, h):
        self.calls.append(("enddoc",))

    def ClosePrinter(self, h):
        self.calls.append(("close",))


WIN_PRINTERS = [
    {"pPrinterName": "4B-LP610BT", "pDriverName": "4BARCODE 4B-LP610BT", "pPortName": "USB001"},
    {"pPrinterName": "4B-LP610BT (Copy 1)", "pDriverName": "4BARCODE 4B-LP610BT",
     "pPortName": "USB002"},
    {"pPrinterName": "ZDesigner ZP 450-200dpi", "pDriverName": "ZDesigner ZP 450-200dpi",
     "pPortName": "USB003"},
    {"pPrinterName": "Microsoft Print to PDF", "pDriverName": "Microsoft Print To PDF",
     "pPortName": "PORTPROMPT:"},
]


def test_windows_discovery():
    found = printers.discover_windows(FakeWin(WIN_PRINTERS), known=K)
    by_name = {p.target: p for p in found}
    a, b = by_name["4B-LP610BT"], by_name["4B-LP610BT (Copy 1)"]
    z, pdf = by_name["ZDesigner ZP 450-200dpi"], by_name["Microsoft Print to PDF"]
    assert a.id == "win:4B-LP610BT|USB001" and b.id == "win:4B-LP610BT (Copy 1)|USB002"
    assert a.port == "USB port 1" and b.port == "USB port 2"
    assert a.kind == b.kind == "tspl" and z.kind == "zpl" and pdf.kind == ""
    assert a.family.id == "lp610bt-compatible" and z.family.id == "zebra-zp450"
    assert pdf.family is None
    assert printers.auto_pick(found) is None          # three label printers: ask the user


def test_auto_pick():
    one = [printers.Printer(id="usb:1-1", kind="tspl"),
           printers.Printer(id="cups:pdf", model="PDF")]
    assert printers.auto_pick(one).id == "usb:1-1"
    assert printers.auto_pick([]) is None


def test_send_windows_raw():
    w = FakeWin(WIN_PRINTERS)
    printers.send_windows_raw("4B-LP610BT", b"DATA", win32print=w)
    assert ("doc", ("Food Labeler", None, "RAW")) in w.calls
    assert ("write", b"DATA") in w.calls and w.calls[-1] == ("close",)
    with pytest.raises(printers.PrinterError, match="can't find"):
        printers.send_windows_raw("Nope", b"x", win32print=w)


def test_send_cups(tmp_path):
    run = FakeRun()
    printers.send_cups("white", b"JOB", run=run)
    lp = [c for c in run.calls if c[0] == "lp"][0]
    assert lp[:7] == ["lp", "-d", "white", "-o", "raw", "-n", "1"]
    assert run.sent == b"JOB" and not os.path.exists(lp[-1])
    with pytest.raises(printers.PrinterError, match="isn't answering"):
        printers.send_cups("white", b"JOB", run=FakeRun(lp_rc=1, lp_err="printer stopped"))
    with pytest.raises(printers.PrinterError, match="can't find"):
        printers.send_cups("x", b"J", run=FakeRun(lp_rc=1, lp_err="Unknown destination"))


def test_send_device(tmp_path):
    root = tmp_path / "dev"
    (root / "usb").mkdir(parents=True)
    dev = root / "usb" / "lp0"
    printers.send_device(str(dev), b"ABC", dev_root=str(root))
    assert dev.read_bytes() == b"ABC"

    def denied(*a, **k):
        raise PermissionError(13, "denied")
    with pytest.raises(printers.PrinterError, match="lp"):
        printers.send_device("/dev/usb/lp0", b"x", opener=denied)
    with pytest.raises(printers.PrinterError, match="isn't answering"):
        printers.send_device(str(root / "nodir" / "lp9"), b"x", dev_root=str(root))


@pytest.mark.parametrize("target", [
    "/home/someone/.bashrc", "/etc/passwd", "relative/lp0", "lp0", "",
    "/dev/../etc/passwd", "/dev/usb/../../tmp/x", "/devices/lp0", "C:\\Windows\\x",
    "/dev/usb/lp0\x00",
])
def test_send_device_refuses_anything_outside_dev(target):
    opened = []

    def opener(*a, **k):
        opened.append(a)
        raise AssertionError("must not be opened")
    with pytest.raises(printers.PrinterError, match="isn't a printer"):
        printers.send_device(target, b"x", opener=opener)
    assert not opened


def test_send_device_refuses_a_link_out_of_dev(tmp_path):
    root = tmp_path / "dev"
    root.mkdir()
    outside = tmp_path / "victim.txt"
    outside.write_text("keep me")
    (root / "lp-link").symlink_to(outside)
    (root / "usb").mkdir()
    (root / "usb" / "lp0").write_bytes(b"")
    (root / "lp610bt-white").symlink_to(root / "usb" / "lp0")
    with pytest.raises(printers.PrinterError, match="isn't a printer"):
        printers.send_device(str(root / "lp-link"), b"x", dev_root=str(root))
    assert outside.read_text() == "keep me"
    printers.send_device(str(root / "lp610bt-white"), b"OK", dev_root=str(root))
    assert (root / "usb" / "lp0").read_bytes() == b"OK"
    assert printers.device_path_ok("/dev/usb/lp0") and printers.device_path_ok("/dev/lp610")


class FakeSock:
    def __init__(self, reply=b"", hang=False):
        self.reply, self.hang = reply, hang
        self.sent = b""
        self.shut = False
        self.timeout = None

    def sendall(self, d):
        self.sent += d

    def shutdown(self, how):
        self.shut = True

    def settimeout(self, t):
        self.timeout = t

    def recv(self, n):
        import socket
        if self.hang:
            raise socket.timeout()
        r, self.reply = self.reply, b""
        return r

    def close(self):
        pass


def test_send_network():
    s = FakeSock(b"OK printed\nmore")
    got = printers.send_network("label-printer.example:9100", b"JOB", connect=lambda a, timeout: s)
    assert got == "OK printed" and s.sent == b"JOB" and s.shut and s.timeout <= 2
    s2 = FakeSock(hang=True)
    assert printers.send_network("h:1", b"J", connect=lambda a, timeout: s2) == ""

    def refuse(a, timeout):
        raise ConnectionRefusedError()
    with pytest.raises(printers.PrinterError, match="isn't answering"):
        printers.send_network("h:9100", b"J", connect=refuse)
    with pytest.raises(printers.PrinterError):
        printers.parse_hostport("h:notaport")
    assert printers.parse_hostport("h") == ("h", 9100)
    assert printers.parse_hostport("[::1]:9101") == ("::1", 9101)


class DripSock(FakeSock):
    """Sends its reply one byte at a time, each byte taking ``step`` (pretend) seconds,
    and never a newline."""

    def __init__(self, clock, step=0.4):
        super().__init__()
        self.clock, self.step, self.timeouts = clock, step, []

    def settimeout(self, t):
        self.timeouts.append(t)

    def recv(self, n):
        import socket
        if self.timeouts[-1] < self.step:
            self.clock.now += self.timeouts[-1]
            raise socket.timeout()
        self.clock.now += self.step
        return b"x"


class FakeClock:
    now = 100.0

    def __call__(self):
        return self.now


def test_send_network_slow_reply_has_one_deadline():
    clock = FakeClock()
    s = DripSock(clock)
    got = printers.send_network("h:9100", b"JOB", connect=lambda a, timeout: s,
                                reply_timeout=1.5, clock=clock)
    assert got == "xxx" and s.sent == b"JOB"
    # all the waiting together stays within the one reply time
    assert clock.now - 100.0 <= 1.5 + 1e-9
    assert s.timeouts == sorted(s.timeouts, reverse=True) and all(t > 0 for t in s.timeouts)


def test_send_network_endless_reply_stops():
    clock = FakeClock()
    s = DripSock(clock, step=0.0)              # bytes as fast as asked, forever
    got = printers.send_network("h:9100", b"J", connect=lambda a, timeout: s, clock=clock)
    assert got == "x" * 512


def test_send_dispatch_dry_run(tmp_path):
    # conftest sets FOOD_LABELER_DRY_RUN: nothing reaches a transport
    printers.send({"method": "network", "target": "192.0.2.10:9100", "kind": "tspl"}, b"JOB")
    jobs = list((tmp_path / "jobs").iterdir())
    assert len(jobs) == 1 and jobs[0].read_bytes() == b"JOB"
    with pytest.raises(printers.PrinterError, match="No printer"):
        printers.send({}, b"x")


def test_send_dispatch_selects_transport(monkeypatch):
    monkeypatch.delenv("FOOD_LABELER_DRY_RUN")
    seen = []
    monkeypatch.setattr(printers, "send_cups", lambda t, d: seen.append(("cups", t)))
    monkeypatch.setattr(printers, "send_device", lambda t, d: seen.append(("device", t)))
    monkeypatch.setattr(printers, "send_windows_raw", lambda t, d: seen.append(("raw", t)))
    monkeypatch.setattr(printers, "send_network", lambda t, d: seen.append(("net", t)) or "")
    monkeypatch.setattr(printers, "send_windows_driver",
                        lambda t, i, c: seen.append(("gdi", t)))
    for m in ["cups", "device", "windows_raw", "network", "windows_driver"]:
        printers.send({"method": m, "target": "T"}, b"x", image=Image.new("1", (8, 8)))
    assert [s[0] for s in seen] == ["cups", "device", "raw", "net", "gdi"]

    def boom(t, d):
        raise OSError("weird")
    monkeypatch.setattr(printers, "send_cups", boom)
    with pytest.raises(printers.PrinterError, match="isn't answering"):
        printers.send({"method": "cups", "target": "T"}, b"x")


def test_build_job_language_and_family_defaults():
    img = Image.new("1", (256, 200), 1)
    st = stocks.get("small")
    lp = K.defs["lp610bt-compatible"]
    j = printers.build_job(img, st, {"kind": "tspl"}, {"density": {}, "speed": {}, "gap": {}},
                           1, family=lp)
    assert b"DENSITY 9\r\n" in j and b"SPEED 3\r\n" in j
    j = printers.build_job(img, st, {"kind": "tspl"}, {"density": {"small": 12}, "speed": {},
                                                       "gap": {"small": 2.5}}, 1, family=lp)
    assert b"DENSITY 12\r\n" in j and b"GAP 2.5 mm,0 mm" in j
    z = printers.build_job(img, st, {"kind": "zpl"}, {}, 2)
    assert z.startswith(b"^XA") and b"^PQ2,0,0,N" in z


def test_status_never_connects(tmp_path):
    p = printers.network_printer("192.0.2.10:9100")
    state, text = printers.status(p, "Shop printer")
    assert state == "ready" and "network" in text      # conftest would fail any connect
    d = printers.Printer(id="usb:1", method="device", target=str(tmp_path / "missing"))
    assert printers.status(d, "X")[0] == "problem"
    assert printers.status(None)[0] == "none"


def test_parse_1284():
    info = printers.parse_1284("MFG:Polono;CMD:TSPL2;MDL:4B-LP610BT;CLS:PRINTER;")
    assert printers.kind_from_1284(info) == "tspl" and printers.model_from_1284(info) == "4B-LP610BT"
    z = printers.parse_1284("MANUFACTURER:Zebra Technologies;COMMAND SET:ZPL;MODEL:ZTC ZP 450-200dpi;")
    assert printers.kind_from_1284(z) == "zpl"
    assert printers.kind_from_1284(printers.parse_1284("MFG:X;CMD:ESC/POS;")) == ""
