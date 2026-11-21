"""Bluetooth printing (alpha): discovery from fake bluetoothctl / PowerShell output,
the RFCOMM and COM-port senders with fake sockets and files, and the new
known_printers.json fields.

Nothing here touches real Bluetooth: conftest removes socket.AF_BLUETOOTH and
replaces btscan.scan, and every test passes its own fakes."""
import errno
import json
import socket
import subprocess

import pytest

from food_labeler import btscan, known, printers

K = known.KnownPrinters()

A1, A2 = "00:11:22:33:44:01", "00:11:22:33:44:02"      # two printers, both "LP610BT"
PHONE, BUDS = "00:11:22:33:44:04", "00:11:22:33:44:03"
SPP_LINE = "\tUUID: Serial Port               (00001101-0000-1000-8000-00805f9b34fb)\n"


def info(addr, name, cls, uuids="", paired="yes", connected="no"):
    return (f"Device {addr} (public)\n\tName: {name}\n\tAlias: {name}\n\tClass: {cls}\n"
            f"\tPaired: {paired}\n\tBonded: {paired}\n\tTrusted: yes\n\tBlocked: no\n"
            f"\tConnected: {connected}\n\tLegacyPairing: no\n{uuids}")


PRINTER_UUIDS = (SPP_LINE + "\tUUID: PnP Information           "
                 "(00001200-0000-1000-8000-00805f9b34fb)\n")
INFO = {
    A1: info(A1, "LP610BT", "0x00040680 (263808)", PRINTER_UUIDS),
    A2: info(A2, "LP610BT", "0x00040680 (263808)", PRINTER_UUIDS, connected="yes"),
    PHONE: info(PHONE, "Sam's Pixel 8", "0x005a020c (5898764)",
                "\tUUID: Handsfree Audio Gateway   (0000111f-0000-1000-8000-00805f9b34fb)\n"),
    BUDS: info(BUDS, "Alex's Pixel Buds Pro", "0x00240418 (2360344)",
               "\tUUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)\n"),
}


class FakeBtRun:
    """Stands in for subprocess.run: answers bluetoothctl devices / info only."""

    def __init__(self, info_=None, devices_rc=0, devices_out=None, hang=False, legacy=False):
        self.info = dict(INFO if info_ is None else info_)
        self.devices_rc, self.hang, self.legacy = devices_rc, hang, legacy
        self.devices_out = devices_out if devices_out is not None else "".join(
            f"Device {a} {self.info[a].split('Name: ')[1].splitlines()[0]}\n" for a in self.info)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        assert kw.get("timeout") and kw["timeout"] <= 5
        if self.hang:
            raise subprocess.TimeoutExpired(cmd, kw["timeout"])

        class R:
            returncode, stdout, stderr = 0, "", ""
        r = R()
        if cmd[:3] == ["bluetoothctl", "devices", "Paired"]:
            if self.legacy:
                r.returncode, r.stdout = 1, "Invalid command\n"
            else:
                r.returncode, r.stdout = self.devices_rc, self.devices_out
        elif cmd[:2] == ["bluetoothctl", "paired-devices"]:
            r.stdout = self.devices_out
        elif cmd[:2] == ["bluetoothctl", "info"]:
            r.stdout = self.info.get(cmd[2], f"Device {cmd[2]} not available\n")
            r.returncode = 0 if cmd[2] in self.info else 1
        else:
            raise AssertionError(f"unexpected command {cmd}")
        return r


def which(name):
    return "/usr/bin/" + name


def linux_scan(**kw):
    run = FakeBtRun(**kw)
    return btscan.scan_linux(run=run, which=which, known=K), run


# -- discovery -------------------------------------------------------------------

def test_two_identical_printers_a_phone_and_headphones():
    devs, run = linux_scan()
    assert len(devs) == 4
    found = btscan.to_printers(devs, K, windows=False)
    assert [p.id for p in found] == [f"bt:{A1}", f"bt:{A2}"]
    a, b = found
    assert a.method == b.method == "bluetooth" and a.target == A1 and b.target == A2
    assert a.family.id == b.family.id == "lp610bt-compatible" and a.kind == "tspl"
    assert a.bluetooth and a.port == "Bluetooth (\u202644:01)"
    assert b.port == "Bluetooth (\u202644:02)"
    assert a.display() != b.display() and a.display().endswith("Bluetooth (\u202644:01)")
    assert printers.ALPHA_TAG in a.display(tag=True)
    # only ever reads: "devices" and "info", never pair / connect / trust / scan
    assert all(c[0] == "bluetoothctl" and c[1] in ("devices", "info") for c in run.calls)


def test_device_details_are_read():
    devs, _ = linux_scan()
    d = {x.address: x for x in devs}
    assert d[A1].device_class == 0x040680 and d[A1].printer_class and d[A1].spp
    assert d[A1].paired is True and d[A1].connected is False and d[A2].connected is True
    assert d[A1].short == "\u202644:01" and "1101" in d[A1].uuids
    assert not d[PHONE].is_printer and not d[BUDS].is_printer and not d[BUDS].spp


def test_older_bluez_falls_back_and_unpaired_devices_are_dropped():
    inf = dict(INFO)
    inf[PHONE] = info(PHONE, "LP610BT", "0x00040680", PRINTER_UUIDS, paired="no")
    devs, run = linux_scan(info_=inf, legacy=True)
    assert ["bluetoothctl", "paired-devices"] in run.calls
    assert PHONE not in {d.address for d in devs}          # seen once, never paired
    assert len(btscan.to_printers(devs, K, windows=False)) == 2


def test_which_devices_count_as_printers():
    inf = {
        "00:11:22:33:44:01": info("00:11:22:33:44:01", "Thermal-X", "0x00040680"),  # class only
        "00:11:22:33:44:02": info("00:11:22:33:44:02", "HC-05", "0x00001f00", SPP_LINE),
        "00:11:22:33:44:03": info("00:11:22:33:44:03", "MUNBYN RW941B", "0x00001f00",
                                  SPP_LINE),
        "00:11:22:33:44:04": info("00:11:22:33:44:04", "MUNBYN keyboard", "0x00002540"),
    }
    devs, _ = linux_scan(info_=inf)
    got = {p.target: p for p in btscan.to_printers(devs, K, windows=False)}
    assert set(got) == {"00:11:22:33:44:01", "00:11:22:33:44:03"}
    assert got["00:11:22:33:44:01"].family is None and got["00:11:22:33:44:01"].kind == ""
    assert got["00:11:22:33:44:03"].family.id.startswith("munbyn")


@pytest.mark.parametrize("kw", [dict(hang=True), dict(devices_rc=1, devices_out="")])
def test_scan_never_fails(kw):
    assert linux_scan(**kw)[0] == []
    assert btscan.scan_linux(run=FakeBtRun(), which=lambda n: None) == []   # no bluetoothctl


def test_scan_stops_when_it_takes_too_long():
    t = iter(range(0, 1000, 5))
    devs = btscan.scan_linux(run=FakeBtRun(), which=which, known=K, clock=lambda: next(t))
    assert 0 < len(devs) < 4


def test_parse_handles_colour_codes_and_junk():
    out = ("\x1b[0;94m[bluetooth]\x1b[0m# Device 00:11:22:33:44:01 LP610BT\r\nnoise\n"
           "[CHG] Device 00:11:22:33:44:02 RSSI: -82\n")
    assert btscan.parse_devices(out) == [("00:11:22:33:44:01", "LP610BT")]
    assert btscan.parse_info("Device 00:00:00:00:00:01 not available") is None
    assert btscan.parse_devices("") == [] and btscan.parse_info("") is None


WIN_JSON = json.dumps([
    {"PNPDeviceID": "BTHENUM\\DEV_001122334401\\7&2A1F&0&BLUETOOTHDEVICE_001122334401",
     "Name": "LP610BT", "Status": "OK"},
    {"PNPDeviceID": "BTHENUM\\DEV_001122334402\\7&2A1F&0&BLUETOOTHDEVICE_001122334402",
     "Name": "LP610BT", "Status": "OK"},
    {"PNPDeviceID": "BTHENUM\\DEV_001122334403\\7&2A1F&0&BLUETOOTHDEVICE_001122334403",
     "Name": "Pixel Buds Pro", "Status": "OK"},
    {"PNPDeviceID": "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0002\\7&1D80ECD3&"
                    "0&001122334401_C00000000",
     "Name": "Standard Serial over Bluetooth link (COM5)", "Status": "OK"},
    {"PNPDeviceID": "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0002\\7&1D80ECD3&"
                    "0&001122334402_C00000000",
     "Name": "Standard Serial over Bluetooth link (COM7)", "Status": "OK"},
    {"PNPDeviceID": "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\\7&1D80ECD3&"
                    "0&000000000000_00000000",
     "Name": "Standard Serial over Bluetooth link (COM6)", "Status": "OK"},
])


def test_windows_bluetooth_com_ports():
    devs = btscan.parse_windows(WIN_JSON, K)
    by = {d.address: d for d in devs}
    assert by[A1].com_port == "COM5" and by[A2].com_port == "COM7"
    assert by["00:11:22:33:44:03"].com_port == "" and not by["00:11:22:33:44:03"].is_printer
    found = btscan.to_printers(devs, K, windows=True)
    assert [(p.id, p.method, p.target) for p in found] == [
        (f"bt:{A1}", "serial", "COM5"), (f"bt:{A2}", "serial", "COM7")]
    assert found[0].port == "Bluetooth COM5 (\u202644:01)" and found[0].alpha
    assert btscan.parse_windows("not json") == [] and btscan.parse_windows("") == []
    one = btscan.parse_windows(json.dumps(json.loads(WIN_JSON)[0]))
    assert len(one) == 1 and one[0].name == "LP610BT"


def test_windows_scan_is_quiet_and_never_crashes():
    seen = {}

    def run(cmd, **kw):
        seen.update(kw)
        raise OSError("no powershell")
    assert btscan.scan_windows(K, run=run) == []
    assert seen["timeout"] <= 15 and "creationflags" in seen


def test_driver_installed_on_the_com_port_is_one_printer():
    win = printers.Printer(id="win:LP610BT|COM5:", method="windows_raw", target="LP610BT",
                           port="COM5:", family=K.defs["lp610bt-compatible"])
    bt = btscan.to_printers(btscan.parse_windows(WIN_JSON, K), K, windows=True)
    merged = btscan.merge([win], bt)
    assert [p.id for p in merged] == ["win:LP610BT|COM5:", f"bt:{A2}"]
    assert win.bluetooth and win.alpha and "Bluetooth COM5" in win.port


def test_discover_adds_bluetooth_and_survives_its_failure(monkeypatch):
    usb = printers.Printer(id="usb:1-1.3", method="device", target="/dev/usb/lp0",
                           family=K.defs["lp610bt-compatible"], kind="tspl")
    monkeypatch.setattr(printers, "discover_linux", lambda known=None: [usb])
    monkeypatch.setattr(printers, "discover_windows", lambda known=None: [usb])
    dev = btscan.BtDevice(address=A1, name="LP610BT", paired=True, com_port="COM5",
                          family=K.defs["lp610bt-compatible"])
    monkeypatch.setattr(btscan, "scan", lambda known=None: [dev])
    found = printers.discover(K)
    assert [p.id for p in found] == ["usb:1-1.3", f"bt:{A1}"]
    assert printers.auto_pick(found) is usb             # the cable wins over Bluetooth
    assert printers.auto_pick(found[1:]) is found[1]   # a lone Bluetooth printer is picked

    def boom(known=None):
        raise RuntimeError("bluetoothd went away")
    monkeypatch.setattr(btscan, "scan", boom)
    assert [p.id for p in printers.discover(K)] == ["usb:1-1.3"]


def test_scan_cached_reuses_a_recent_list(monkeypatch):
    calls = []

    def fake_scan(known=None):
        calls.append(1)
        return btscan._remember([btscan.BtDevice(address=A1, name="LP610BT")])
    monkeypatch.setattr(btscan, "scan", fake_scan)
    assert btscan.scan_cached(K, 60)[0].address == A1 and len(calls) == 1
    assert btscan.scan_cached(K, 60)[0].address == A1 and len(calls) == 1
    btscan._cache = (btscan._cache[0] - 120, btscan._cache[1])   # two minutes later
    btscan.scan_cached(K, 60)
    assert len(calls) == 2


# -- RFCOMM sender ---------------------------------------------------------------

class FakeBtSocket:
    def __init__(self, world, refuse=(), connect_error=None, send_error_after=None):
        self.world = world
        self.refuse, self.connect_error = refuse, connect_error
        self.send_error_after = send_error_after
        self.sent, self.closed, self.timeouts = [], False, []
        world.sockets.append(self)

    def settimeout(self, t):
        self.timeouts.append(t)

    def connect(self, addr):
        self.world.connects.append(addr)
        if addr[1] in self.refuse:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
        if self.connect_error is not None:
            raise self.connect_error

    def sendall(self, d):
        if self.send_error_after is not None and len(self.sent) >= self.send_error_after:
            raise ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
        self.sent.append(bytes(d))

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class World:
    def __init__(self, **kw):
        self.kw, self.sockets, self.connects, self.sleeps = kw, [], [], []

    def make(self):
        return FakeBtSocket(self, **self.kw)

    def sleep(self, s):
        self.sleeps.append(s)


def bt_send(world, target=A1, data=b"x", **kw):
    return printers.send_bluetooth(target, data, make_socket=world.make, sleep=world.sleep, **kw)


def test_rfcomm_sends_the_job_in_chunks_with_pauses():
    w = World()
    job = bytes(range(256)) * 40                         # 10240 bytes
    assert bt_send(w, data=job, chunk=4096, delay_ms=20) == 1
    s = w.sockets[0]
    assert [len(x) for x in s.sent] == [4096, 4096, 2048] and b"".join(s.sent) == job
    assert w.connects == [(A1, 1)] and s.closed
    assert w.sleeps[:2] == [0.02, 0.02] and len(w.sleeps) == 3   # + the settle pause
    assert s.timeouts[0] == printers.BT_CONNECT_TIMEOUT


def test_rfcomm_tries_the_next_channel_when_refused_and_remembers_it():
    w = World(refuse=(1, 2))
    assert bt_send(w, target=A1.lower()) == 3
    assert [c[1] for c in w.connects] == [1, 2, 3] and all(s.closed for s in w.sockets)
    assert printers.LEARNED_CHANNELS[A1] == 3
    w2 = World()
    bt_send(w2)
    assert w2.connects == [(A1, 3)]                       # the one that worked, first
    w3 = World()
    bt_send(w3, target=A2, hint=2)
    assert w3.connects == [(A2, 2)]


def test_rfcomm_chosen_channel_is_the_only_one_tried():
    w = World(refuse=(1,))
    with pytest.raises(printers.PrinterError) as e:
        bt_send(w, channel=1)
    assert str(e.value) == printers.MSG_BT_CHANNEL and w.connects == [(A1, 1)]
    w = World()
    assert bt_send(w, target=A1 + "/4") == 4 and w.connects == [(A1, 4)]
    with pytest.raises(printers.PrinterError) as e:
        bt_send(World(refuse=(1, 2, 3)), target=A2)
    assert str(e.value) == printers.MSG_BT_CHANNEL


@pytest.mark.parametrize("error, message", [
    (socket.timeout("timed out"), printers.MSG_BT_AWAY),
    (OSError(errno.EHOSTDOWN, "Host is down"), printers.MSG_BT_AWAY),
    (OSError(errno.EHOSTUNREACH, "No route to host"), printers.MSG_BT_OFF),
    (OSError(errno.ENETDOWN, "Network is down"), printers.MSG_BT_OFF),
    (PermissionError(errno.EACCES, "Permission denied"), printers.MSG_BT_NOT_PAIRED),
    (OSError(52, "Invalid exchange"), printers.MSG_BT_NOT_PAIRED),
    (OSError(errno.EIO, "weird"), printers.MSG_BT_AWAY),
])
def test_rfcomm_errors_in_plain_words(error, message):
    w = World(connect_error=error)
    with pytest.raises(printers.PrinterError) as e:
        bt_send(w)
    assert str(e.value) == message and w.sockets[0].closed and len(w.connects) == 1


def test_rfcomm_failure_while_sending_closes_the_socket():
    w = World(send_error_after=1)
    with pytest.raises(printers.PrinterError) as e:
        bt_send(w, data=b"x" * 9000, chunk=4096)
    assert str(e.value) == printers.MSG_BT_AWAY and w.sockets[0].closed
    assert A1 not in printers.LEARNED_CHANNELS


@pytest.mark.parametrize("target", ["", "LP610BT", "00:11:22:33:44", "00:11:22:33:44:01/0",
                                    "00:11:22:33:44:01/99", "../../etc/passwd",
                                    "00:11:22:33:44:01;rm"])
def test_rfcomm_refuses_a_bad_address(target):
    w = World()
    with pytest.raises(printers.PrinterError) as e:
        bt_send(w, target=target)
    assert str(e.value) == printers.MSG_BT_BAD_ADDRESS and not w.sockets


def test_without_bluetooth_support_in_python():
    # conftest removed socket.AF_BLUETOOTH, like a Python built without it
    assert not hasattr(socket, "AF_BLUETOOTH")
    with pytest.raises(printers.PrinterError) as e:
        printers.send_bluetooth(A1, b"x", sleep=lambda s: None, sys_root="/nonexistent")
    assert str(e.value) == printers.MSG_BT_UNAVAILABLE


def test_real_socket_factory_asks_for_rfcomm(monkeypatch):
    made = []

    class Sock:
        def __init__(self, *a):
            made.append(a)
    monkeypatch.setattr(socket, "AF_BLUETOOTH", 31, raising=False)
    monkeypatch.setattr(socket, "BTPROTO_RFCOMM", 3, raising=False)
    monkeypatch.setattr(socket, "socket", Sock)
    printers._bt_socket()
    assert made == [(31, socket.SOCK_STREAM, 3)]

    def denied(*a):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(socket, "socket", denied)
    with pytest.raises(printers.PrinterError) as e:
        printers._bt_socket()
    assert str(e.value) == printers.MSG_BT_PERMISSION


def rfkill(tmp_path, soft="0", hard="0", hci=True):
    root = tmp_path / "sys"
    (root / "class" / "bluetooth").mkdir(parents=True)
    if hci:
        (root / "class" / "bluetooth" / "hci0").mkdir()
    r = root / "class" / "rfkill" / "rfkill1"
    r.mkdir(parents=True)
    (r / "type").write_text("bluetooth\n")
    (r / "soft").write_text(soft + "\n")
    (r / "hard").write_text(hard + "\n")
    w = root / "class" / "rfkill" / "rfkill0"
    w.mkdir()
    (w / "type").write_text("wlan\n")
    (w / "soft").write_text("1\n")
    (w / "hard").write_text("0\n")
    return str(root)


def test_switched_off_is_read_from_sysfs(tmp_path):
    assert printers.bluetooth_switched_off(rfkill(tmp_path / "a")) is False
    assert printers.bluetooth_switched_off(rfkill(tmp_path / "b", soft="1")) is True
    assert printers.bluetooth_switched_off(rfkill(tmp_path / "c", hard="1")) is True
    empty = tmp_path / "d" / "sys"
    (empty / "class").mkdir(parents=True)
    assert printers.bluetooth_switched_off(str(empty)) is True       # no adapter at all
    made = []
    with pytest.raises(printers.PrinterError) as e:
        printers.send_bluetooth(A1, b"x", sys_root=rfkill(tmp_path / "e", soft="1"))
    assert str(e.value) == printers.MSG_BT_OFF and not made


# -- COM port sender ---------------------------------------------------------------

class FakeFile:
    def __init__(self, store, path, error=None):
        self.store, self.path, self.error = store, path, error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.store["closed"] = True

    def write(self, d):
        self.store.setdefault("writes", []).append(bytes(d))

    def flush(self):
        pass


def com_opener(store, error=None):
    def opener(path, mode, buffering=-1):
        store["path"], store["mode"], store["buffering"] = path, mode, buffering
        if error is not None:
            raise error
        return FakeFile(store, path)
    return opener


def test_windows_com_port_gets_the_job_in_chunks():
    st, sleeps = {}, []
    printers.send_serial("com5", b"A" * 5000, chunk=2048, delay_ms=30,
                         opener=com_opener(st), sleep=sleeps.append, windows=True)
    assert st["path"] == "\\\\.\\COM5" and st["mode"] == "r+b" and st["buffering"] == 0
    assert [len(x) for x in st["writes"]] == [2048, 2048, 904] and st["closed"]
    assert sleeps == [0.03, 0.03]


@pytest.mark.parametrize("target", ["", "COM0", "COM5; del x", "C:\\Windows\\x", "LPT1",
                                    "\\\\.\\PhysicalDrive0", "COM12345", "/dev/rfcomm0"])
def test_windows_com_port_refuses_anything_else(target):
    st = {}
    with pytest.raises(printers.PrinterError) as e:
        printers.send_serial(target, b"x", opener=com_opener(st), windows=True)
    assert str(e.value) == printers.MSG_NOT_A_DEVICE and "path" not in st


@pytest.mark.parametrize("error, message", [
    (FileNotFoundError(2, "The system cannot find the file specified"),
     printers.MSG_SERIAL_MISSING),
    (PermissionError(13, "Access is denied"), printers.MSG_SERIAL_BUSY),
    (OSError(121, "The semaphore timeout period has expired"), printers.MSG_BT_AWAY),
])
def test_windows_com_port_errors(error, message):
    with pytest.raises(printers.PrinterError) as e:
        printers.send_serial("COM5", b"x", opener=com_opener({}, error), windows=True)
    assert str(e.value) == message


def test_serial_device_elsewhere_must_be_under_dev(tmp_path):
    root = tmp_path / "dev"
    root.mkdir()
    (root / "rfcomm0").write_bytes(b"")
    printers.send_serial(str(root / "rfcomm0"), b"JOB", dev_root=str(root), windows=False,
                         sleep=lambda s: None)
    assert (root / "rfcomm0").read_bytes() == b"JOB"
    with pytest.raises(printers.PrinterError):
        printers.send_serial(str(tmp_path / "x"), b"J", dev_root=str(root), windows=False)


# -- dispatch, config, alpha, status ----------------------------------------------

def bt_printer(**kw):
    kw.setdefault("family", K.defs["lp610bt-compatible"])
    return printers.Printer(id=f"bt:{A1}", kind="tspl", model="LP610BT", method="bluetooth",
                            target=A1, port="Bluetooth (\u202644:01)", bluetooth=True, **kw)


def test_dispatch_and_config(monkeypatch):
    monkeypatch.delenv("FOOD_LABELER_DRY_RUN")
    seen = []
    monkeypatch.setattr(printers, "send_bluetooth", lambda t, d, **kw: seen.append((t, kw)))
    monkeypatch.setattr(printers, "send_serial", lambda t, d, **kw: seen.append((t, kw)))
    p = bt_printer()
    cfg = printers.printer_config(p, {"bt_channel": 2, "bt_channel_found": 3})
    assert cfg["bt_chunk"] == 2048 and cfg["bt_delay_ms"] == 30       # from known_printers.json
    assert cfg["channel"] == 2 and cfg["channel_hint"] == 3
    printers.send(cfg, b"JOB")
    assert seen[0] == (A1, {"channel": 2, "hint": 3, "chunk": 2048, "delay_ms": 30})
    cfg = printers.printer_config(bt_printer(family=None), {"bt_channel": "nope"})
    assert cfg["bt_chunk"] == printers.BT_CHUNK and cfg["bt_delay_ms"] == printers.BT_DELAY_MS
    assert cfg["channel"] is None
    serial = printers.Printer(id="bt:COM5", method="serial", target="COM5", bluetooth=True)
    printers.send(printers.printer_config(serial, {}), b"J")
    assert seen[1][0] == "COM5" and seen[1][1]["chunk"] == printers.BT_CHUNK


def test_driver_only_printer_over_bluetooth_sends_nothing(tmp_path):
    from test_alpha_driver import driver_known
    fam = driver_known(tmp_path).defs["acme-app-only"]
    p = bt_printer(family=fam)
    p.kind = ""
    assert printers.printer_config(p, {})["method"] == "needs_driver"


def test_dry_run_writes_the_bluetooth_job_unchanged(tmp_path):
    job = b"SIZE 50 mm,30 mm\r\nCLS\r\nPRINT 1\r\n"
    printers.send(printers.printer_config(bt_printer(), {}), job)
    files = list((tmp_path / "jobs").iterdir())
    assert len(files) == 1 and files[0].read_bytes() == job and "bluetooth" in files[0].name


def test_tested_model_is_alpha_over_bluetooth_until_verified(tmp_path):
    lp = K.defs["lp610bt-compatible"]
    assert lp.verified_on_paper and not lp.verified_bluetooth
    usb = printers.Printer(id="usb:1-1.3", family=lp)
    assert not usb.alpha and printers.alpha_notice(usb) == printers.ALPHA_NOTICE
    bt = bt_printer()
    assert bt.alpha and printers.alpha_notice_due(bt, {})
    assert printers.alpha_notice(bt) == printers.ALPHA_NOTICE_BLUETOOTH
    assert "Ask for help on GitHub" in printers.ALPHA_NOTICE_BLUETOOTH
    assert "USB" in printers.ALPHA_NOTICE_BLUETOOTH
    f = tmp_path / "u.json"
    entry = {"id": "lp610bt-compatible", "name": "LP610BT", "language": "tspl",
             "verified_on_paper": True, "verified_bluetooth": True}
    f.write_text(json.dumps({"format": known.FORMAT, "version": 1, "printers": [entry]}))
    k = known.KnownPrinters(tmp_path / "data")
    k.import_file(f)
    assert not bt_printer(family=k.defs["lp610bt-compatible"]).alpha
    entry["verified_on_paper"] = False                  # Bluetooth alone isn't enough
    d = known.validate_entry(entry)
    assert bt_printer(family=d).alpha


def test_status_never_connects(monkeypatch):
    monkeypatch.setattr(printers, "bluetooth_switched_off", lambda sys_root="/sys": False)
    assert printers.status(bt_printer(), "White") == ("ready", "White (Bluetooth)")
    monkeypatch.setattr(printers, "bluetooth_switched_off", lambda sys_root="/sys": True)
    state, text = printers.status(bt_printer(), "White")
    assert state == "problem" and "switched off" in text


def test_help_text_says_pair_in_the_system_settings():
    h = printers.BT_HELP
    assert "Bluetooth & devices" in h and "0000" in h and "1234" in h
    assert "Look for printers again" in h and "never pairs" in h and "alpha" in h


# -- known_printers.json fields -----------------------------------------------------

@pytest.mark.parametrize("field, value, ok", [
    ("bt_chunk", 2048, True), ("bt_chunk", 64, True), ("bt_chunk", 65536, True),
    ("bt_chunk", 0, True), ("bt_chunk", 63, False), ("bt_chunk", 70000, False),
    ("bt_chunk", True, False), ("bt_chunk", "2048", False), ("bt_chunk", 20.5, False),
    ("bt_delay_ms", 0, True), ("bt_delay_ms", 1000, True), ("bt_delay_ms", -1, False),
    ("bt_delay_ms", 1001, False), ("bt_delay_ms", False, False), ("bt_delay_ms", "5", False),
    ("verified_bluetooth", True, True), ("verified_bluetooth", "yes", False),
    ("verified_bluetooth", 1, False),
])
def test_bluetooth_fields_are_validated(field, value, ok):
    e = {"id": "x", "name": "X", "language": "tspl", field: value}
    if ok:
        d = known.validate_entry(e)
        assert getattr(d, field) == value
    else:
        with pytest.raises(known.DefinitionError, match=field):
            known.validate_entry(e)


def test_bluetooth_fields_survive_an_update_file(tmp_path):
    f = tmp_path / "u.json"
    f.write_text(json.dumps({"format": known.FORMAT, "version": 1, "printers": [
        {"id": "acme-bt", "name": "Acme BT", "language": "tspl", "windows": ["ACME-BT"],
         "bt_chunk": 512, "bt_delay_ms": 0}]}))
    k = known.KnownPrinters(tmp_path / "data")
    k.import_file(f)
    k2 = known.KnownPrinters(tmp_path / "data")
    d = k2.defs["acme-bt"]
    assert d.bt_chunk == 512 and d.bt_delay_ms == 0 and not d.verified_bluetooth
    saved = json.loads((tmp_path / "data" / "known_printers.json").read_text())
    assert saved["printers"][0]["bt_delay_ms"] == 0 and "verified_bluetooth" not in saved[
        "printers"][0]
    plain = known.validate_entry({"id": "y", "name": "Y", "language": "tspl"})
    assert plain.bt_chunk == 0 and plain.bt_delay_ms is None


def test_bluetooth_names_are_one_tidy_line():
    odd = "LP610BT\x1b[31m‮   evil\t" + "z" * 300
    devs = btscan.parse_devices(f"Device {A1} {odd}\n")
    assert devs[0][1].startswith("LP610BT evil z") and len(devs[0][1]) <= 80
    d = btscan.parse_info(info(A1, odd, "0x00040680", PRINTER_UUIDS), A1)
    assert "\x1b" not in d.name and "‮" not in d.name and len(d.name) <= 80
    win = json.dumps([{"PNPDeviceID": "BTHENUM\\DEV_001122334401\\7&2A1F&0&X",
                       "Name": "LP610BT\r\nFake line", "Status": "OK"}])
    (w,) = btscan.parse_windows(win, K)
    assert w.name == "LP610BT Fake line"
