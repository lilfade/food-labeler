"""Network printers: added by hand (address:port), kept in settings, listed and
removed; "Test the connection" never sends anything; they count as connected
for printing, test labels, setting up a roll, the darkness test and feeding.
Never touches a real network: connections are fakes."""
import socket

import pytest

from food_labeler import calibrate, known, printers, settings as settings_mod, stocks


class FakeSocket:
    def __init__(self):
        self.sent = b""
        self.closed = False

    def sendall(self, data):
        self.sent += data

    def close(self):
        self.closed = True


def fresh_settings():
    return settings_mod.Settings()


def test_add_list_remove_and_keep_after_restart():
    cfg = fresh_settings()
    k = known.KnownPrinters()
    p = printers.add_network_printer(cfg["printers"], " 192.0.2.42:9101 ", "tspl",
                                     "lp610bt-compatible", "White label printer")
    assert p.id == "net:192.0.2.42:9101" and p.target == "192.0.2.42:9101"
    cfg["selected"] = p.id
    printers.add_network_printer(cfg["printers"], "192.168.1.60", "zpl", "zebra-zpl")
    cfg.save()
    again = fresh_settings()                            # the program started again
    nets = printers.network_printers(again["printers"], k)
    assert [x.target for x in nets] == ["192.0.2.42:9101", "192.168.1.60:9100"]
    white, zebra = nets
    assert again.nickname(white.id) == "White label printer"
    assert white.method == "network" and white.kind == "tspl" and white.manual
    assert white.family.id == "lp610bt-compatible" and zebra.kind == "zpl"
    assert again["selected"] == white.id
    # adding the same address again updates it instead of adding another
    printers.add_network_printer(again["printers"], "192.0.2.42:9101", "tspl",
                                 "lp610bt-compatible")
    assert len(printers.network_printers(again["printers"], k)) == 2
    printers.remove_network_printer(again.data, white.id)
    again.save()
    last = fresh_settings()
    assert [x.target for x in printers.network_printers(last["printers"], k)] == \
        ["192.168.1.60:9100"]
    assert last["selected"] == ""                        # it was the chosen one


def test_remove_only_forgets_network_printers():
    cfg = fresh_settings()
    cfg["printers"]["usb:1-1.4"] = {"nickname": "Cable one"}
    printers.remove_network_printer(cfg.data, "usb:1-1.4")
    assert "usb:1-1.4" in cfg["printers"]


@pytest.mark.parametrize("bad", ["", "printer:abc", "printer:70000", ":9100"])
def test_bad_addresses_are_refused_plainly(bad):
    with pytest.raises(printers.PrinterError, match="192.168.1.50:9100"):
        printers.add_network_printer({}, bad)


def test_damaged_entries_are_skipped():
    got = printers.network_printers({"net:x": {"manual": True, "target": "x:notaport"},
                                     "net:y": "junk", "net:z": {"manual": True}})
    assert got == []


def test_lp610bt_over_the_network_is_tested_others_are_alpha():
    k = known.KnownPrinters()
    lp = k.get("lp610bt-compatible")
    assert lp.verified_on_paper and lp.verified_network
    tested = printers.network_printer("192.0.2.42:9101", "tspl", lp)
    assert not tested.alpha
    assert printers.network_printer("192.0.2.42:9101", "tspl").alpha       # unknown model
    zebra = k.get("zebra-zp450")
    assert zebra.verified_on_paper and not zebra.verified_network
    assert printers.network_printer("z:9100", "zpl", zebra).alpha          # USB only so far
    assert printers.alpha_notice_due(printers.network_printer("z:9100", "zpl", zebra), {})
    # the same LP610BT on its USB cable is unchanged
    usb = printers.Printer(id="usb:1-1.4", kind="tspl", method="device", family=lp)
    assert not usb.alpha


def test_verified_network_in_update_files():
    entry = {"id": "x-net", "name": "X", "language": "tspl", "verified_on_paper": True,
             "verified_network": True}
    d = known.validate_entry(entry)
    assert d.verified_network
    assert known._to_json(d)["verified_network"] is True
    with pytest.raises(known.DefinitionError, match="verified_network"):
        known.validate_entry(dict(entry, verified_network="yes"))


def test_test_connection_sends_nothing():
    s = FakeSocket()
    seen = []

    def connect(addr, timeout):
        seen.append((addr, timeout))
        return s
    msg = printers.check_network("192.0.2.42:9101", connect=connect)
    assert msg.startswith("✔") and "Nothing was printed" in msg
    assert seen == [(("192.0.2.42", 9101), printers.NETWORK_TEST_TIMEOUT)]
    assert s.sent == b"" and s.closed
    assert printers.NETWORK_TEST_TIMEOUT <= 5


@pytest.mark.parametrize("err,words", [(socket.timeout(), "Nothing answered"),
                                       (ConnectionRefusedError(), "not on port 9101"),
                                       (OSError("unreachable"), "couldn't reach")])
def test_test_connection_failures_in_plain_words(err, words):
    def connect(addr, timeout):
        raise err
    assert words in printers.check_network("192.0.2.42:9101", connect=connect)


def test_test_connection_bad_address():
    with pytest.raises(printers.PrinterError):
        printers.check_network("192.0.2.42:port")


def test_not_answering_message_names_the_address():
    def refuse(addr, timeout):
        raise OSError("refused")
    with pytest.raises(printers.PrinterError, match="192.0.2.42:9101"):
        printers.send_network("192.0.2.42:9101", b"JOB", connect=refuse)


def test_network_printers_are_ready_without_connecting():
    p = printers.network_printer("192.0.2.42:9101")
    state, text = printers.status(p, "White")
    assert state == "ready" and "network" in text


def test_everything_works_on_a_network_printer(tmp_path, monkeypatch):
    """Roll set-up, the line-up label, the darkness test, feeding and test labels
    all go to a network printer like to any other (written to files here)."""
    monkeypatch.setenv("FOOD_LABELER_DRY_RUN", str(tmp_path / "jobs"))
    k = known.KnownPrinters()
    p = printers.network_printer("192.0.2.42:9101", "tspl", k.get("lp610bt-compatible"))
    cfgp = printers.printer_config(p, {"kind": "tspl"})
    assert cfgp == {"kind": "tspl", "method": "network", "target": "192.0.2.42:9101"}
    st = stocks.get("large")
    job = calibrate.setup_job_for(st, cfgp, {}, "gap")
    assert calibrate.send_setup(cfgp, job, lambda: True) is True
    printers.send(cfgp, calibrate.lineup_label_job(st, cfgp, {}, p.family))
    data, _levels = printers.darkness_test_job(st, cfgp, {}, p.family)
    printers.send(cfgp, data)
    printers.send(cfgp, printers.feed_job(st, cfgp, {}))
    from food_labeler import render
    printers.send(cfgp, printers.build_job(render.render_text_label(["This is:", "White"], st),
                                           st, cfgp, {}, 1, family=p.family))
    files = sorted((tmp_path / "jobs").glob("job-*-network.bin"))
    assert len(files) == 5
    assert files[0].read_bytes().endswith(b"GAPDETECT\r\n")


def test_main_window_lists_network_printers_as_connected():
    """App.set_found adds the network printers to what was found, so choosing one
    makes it the current printer (print settings, roll set-up, Which one is it?)."""
    from types import SimpleNamespace
    from food_labeler.app import App
    cfg = fresh_settings()
    p = printers.add_network_printer(cfg["printers"], "192.0.2.42:9101", "tspl",
                                     "lp610bt-compatible")
    cfg["selected"] = p.id
    fake = SimpleNamespace(cfg=cfg, known=known.KnownPrinters(), found=[],
                           refresh_printer_combo=lambda: None)
    App.set_found(fake, [])
    assert [x.id for x in fake.found] == [p.id]
    fake.found_ok = App.current_printer(fake)
    assert fake.found_ok is not None and fake.found_ok.target == "192.0.2.42:9101"
    assert not fake.found_ok.alpha
