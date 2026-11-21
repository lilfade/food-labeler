"""A plain-text "printer help" report the user can share when asking for help.

Help goes through the project's GitHub issues: ``issue_link`` builds the
"new issue" address (always https://github.com/…, from app_config.json's
``issues_url`` or the built-in one) with only a fixed template name and a
short title in it. The report itself is never put in the address; it is
copied to the clipboard for the person to paste. E-mail (``mailto``) stays
as a quiet fallback.

It contains only technical facts (program version, system, USB devices,
printers, recent error lines) — never what is written on labels. Paths are
shortened and the user name is hidden.

USB devices: by default only printers are listed (a USB printer-class
interface, Windows class "Printer", or a USB id / name of a known printer
model). Everything else plugged in (phones, keyboards, storage…) is only
counted, unless the person ticks "Also list everything else plugged in";
even then their serial numbers are never included.

Bluetooth devices follow the same rule: paired printers are listed (name,
device class, Serial Port Profile yes/no, paired/connected), everything
else (phones, headphones…) is only counted, and with the tick box listed
by class only, never by name. A Bluetooth address is never written out in
full: only its last two bytes ("…44:01"), anywhere in the report.
"""
from __future__ import annotations

import getpass
import platform
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

from . import APP_NAME, __version__

SUBJECT = "Food Labeler — new printer"
MAILTO_MAX = 1800

# Where help is asked for. app_config.json's "issues_url" may change the
# repository, but only to another https://github.com/<owner>/<repo>/issues.
ISSUES_URL = "https://github.com/lilfade/food-labeler/issues"
ISSUES_RE = re.compile(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}"
                       r"/issues")
PRINTER_TEMPLATE = "printer-not-working.yml"   # .github/ISSUE_TEMPLATE/<this>
ISSUE_TITLE = "My printer isn't working"


MAC_RE = re.compile(r"(?<![0-9A-Fa-f])(?<![0-9A-Fa-f][:-])(?:[0-9A-Fa-f]{2}[:-]){4}"
                    r"([0-9A-Fa-f]{2})[:-]([0-9A-Fa-f]{2})(?![:-]?[0-9A-Fa-f])")
# Windows Bluetooth PnP ids carry the address as 12 hex digits ("DEV_001122334401",
# "…&001122334401_C00000000"): keep the last 4.
PNP_ADDR_RE = re.compile(r"(?i)(?<=DEV_)[0-9A-F]{8}(?=[0-9A-F]{4}(?![0-9A-F]))"
                         r"|(?<=&)[0-9A-F]{8}(?=[0-9A-F]{4}_)")


def hide_addresses(text: str) -> str:
    """Bluetooth (and other MAC-style) addresses down to their last two bytes."""
    text = MAC_RE.sub(lambda m: f"\u2026{m.group(1)}:{m.group(2)}".upper(), text)
    return PNP_ADDR_RE.sub("\u2026", text)


def _scrub(text: str) -> str:
    """Replace the home folder with ~, hide the login name and Bluetooth addresses."""
    text = hide_addresses(text)
    home = str(Path.home())
    if home and len(home) > 3:
        text = text.replace(home, "~")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = ""
    if user and len(user) >= 3:
        # Whole words only: a user called "lab" must not turn "Labeler" into
        # "<user>eler" (which would also hide real information).
        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])",
                      "<user>", text, flags=re.I)
    return text


def recent_log_problems(log_path, max_lines: int = 40) -> list[str]:
    """WARNING/ERROR lines and tracebacks from the end of the log (INFO lines are
    skipped: they can mention file names)."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    keep = []
    for ln in lines[-2000:]:
        if (" ERROR " in ln or " WARNING " in ln or ln.startswith("Traceback")
                or re.match(r"\s+File \"", ln) or re.match(r"^\w+(Error|Exception)\b", ln)):
            keep.append(ln[:300])
    return keep[-max_lines:]


def is_printer_device(d) -> bool:
    """True for a USB device that is (or looks like) a printer."""
    return bool(d.is_printer or d.family is not None
                or str(getattr(d, "pnp_class", "") or "").lower() == "printer")


def build(printers_found=(), usb_devices=(), nicknames: dict | None = None,
          log_path=None, known=None, everything: bool = False, bt_devices=()) -> str:
    """Build the report. Pass only printer/USB/Bluetooth facts — never the label document.

    ``everything``: also list USB devices that aren't printers (without their
    serial numbers) and Bluetooth devices that aren't printers (by class
    only, without their names); by default they are only counted."""
    out = [f"{APP_NAME} printer report", "=" * 30,
           f"Program: {APP_NAME} {__version__}" + (" (installed)" if getattr(sys, "frozen", False)
                                                   else " (from source)"),
           f"System: {platform.system()} {platform.release()} ({platform.machine()})",
           f"Python: {platform.python_version()}", ""]
    if known is not None:
        out.append("Known printer models: " + ", ".join(d.id for d in known.all()))
        out.append("")
    printer_devs = [d for d in usb_devices if is_printer_device(d)]
    others = [d for d in usb_devices if not is_printer_device(d)]
    out.append("USB printers:" if not everything else "USB devices:")
    shown = list(printer_devs) + (others if everything else [])
    if not shown:
        out.append("  (none found)")
    for d in shown:
        printer = is_printer_device(d)
        out.append(f"  - {d.title()}")
        line = (f"      id {d.vidpid or '?'}  port {d.port or '?'}  printer-class "
                f"{'yes' if d.is_printer else 'no'}")
        if printer:
            line += f"  serial {d.serial or '-'}"
        out.append(line)
        if not printer:
            continue                    # nothing more about devices that aren't printers
        if d.manufacturer or d.product:
            out.append(f"      says: {d.manufacturer} / {d.product}")
        if d.pnp_class:
            out.append(f"      Windows class: {d.pnp_class}")
        if d.ieee1284:
            out.append("      1284 id: " + ";".join(f"{k}:{v}" for k, v in d.ieee1284.items()))
        if d.lp:
            out.append(f"      driver node: {d.lp}")
    if others and not everything:
        n = len(others)
        out.append(f"  ({n} other USB device{'s' if n != 1 else ''} plugged in, not listed)")
    out.append("")
    out.extend(_bluetooth_lines(bt_devices, everything))
    out.append("")
    out.append("Printers:")
    if not printers_found:
        out.append("  (none found)")
    nick = nicknames or {}
    for p in printers_found:
        out.append(f"  - {p.display(nick.get(p.id, ''))}")
        out.append(f"      id {p.id}  language {p.kind or '?'}  dpi {p.dpi}  "
                   f"via {p.method} {p.target}")
        out.append(f"      model {p.model or '?'}  usb {p.vidpid or '?'}  "
                   f"matched {getattr(p.family, 'id', '-')}  "
                   f"{'alpha (not tested yet)' if p.alpha else 'tested'}"
                   + ("  driver only" if p.driver_only else ""))
        if p.detail:
            out.append(f"      detail: {p.detail}")
    out.append("")
    probs = recent_log_problems(log_path) if log_path else []
    out.append("Recent problems from the log:")
    out.extend(f"  {x}" for x in probs) if probs else out.append("  (none)")
    return _scrub("\n".join(out)) + "\n"


def _yn(v) -> str:
    return "yes" if v else "?" if v is None else "no"


def _bluetooth_lines(devs, everything: bool) -> list[str]:
    """The "Bluetooth printers" part: printers in full (address shortened),
    other devices only counted, or with the tick box listed without names."""
    devs = list(devs or ())
    printers_ = [d for d in devs if d.is_printer]
    others = [d for d in devs if not d.is_printer]
    out = ["Bluetooth printers (paired):" if not everything else "Bluetooth devices (paired):"]
    if not printers_ and not (everything and others):
        out.append("  (none found)")
    for d in printers_:
        title = getattr(d.family, "display_name", "") or d.name or "Unnamed Bluetooth printer"
        out.append(f"  - {title}")
        out.append(f"      says: {d.name or '-'}  address {d.short or '?'}  class "
                   f"{d.class_text()}  SPP {'yes' if d.spp else 'no'}")
        line = f"      paired {_yn(d.paired)}  connected {_yn(d.connected)}"
        if d.com_port:
            line += f"  port {d.com_port}"
        out.append(line + f"  matched {getattr(d.family, 'id', '-')}")
    if everything:
        for d in others:
            out.append(f"  - (not a printer; name not shown)  class {d.class_text()}  "
                       f"SPP {'yes' if d.spp else 'no'}")
    elif others:
        n = len(others)
        out.append(f"  ({n} other Bluetooth device{'s' if n != 1 else ''} paired, not listed)")
    return out


def mailto(report: str, to: str = "") -> str:
    """A mailto: link with the report as the body.

    Mail programs truncate or refuse very long mailto URLs, so the body is
    cut at MAILTO_MAX characters (the full report is on the clipboard).
    """
    body = report
    if len(body) > MAILTO_MAX:
        body = (body[:MAILTO_MAX] + "\n...\n(The report was too long for email. "
                "It has been copied — please paste the rest here.)")
    return f"mailto:{quote(to)}?subject={quote(SUBJECT)}&body={quote(body)}"


def issues_url(config: dict | None = None) -> str:
    """The issues page: app_config's "issues_url" if it is a GitHub issues page, else ours."""
    if config is None:
        from . import known
        config = known.app_config()
    url = str((config or {}).get("issues_url") or "").strip().rstrip("/")
    return url if ISSUES_RE.fullmatch(url) else ISSUES_URL


def issue_link(title: str = ISSUE_TITLE, template: str = PRINTER_TEMPLATE,
               config: dict | None = None) -> str:
    """The "new issue" address for the printer help form, with a filled-in title.

    Only the template name and a short title go into the address (url-encoded),
    never the report: it can be long and it is the person's to paste or not."""
    if not re.fullmatch(r"[a-z0-9-]{1,60}\.ya?ml", template or ""):
        template = PRINTER_TEMPLATE
    title = " ".join(str(title or "").split())[:120] or ISSUE_TITLE
    return issues_url(config) + "/new?" + urlencode({"template": template, "title": title},
                                                    quote_via=quote)


def ask_on_github(report: str, copy, opener=None, title: str = ISSUE_TITLE,
                  config: dict | None = None) -> bool:
    """Copy the report (``copy(text)``) and open the new-issue page in the browser.

    Returns True if the browser was asked to open the page. Only ever opens
    an https://github.com/ address built by issue_link."""
    copy(report)
    url = issue_link(title, config=config)
    if not url.startswith("https://github.com/"):     # belt and braces: never anything else
        return False
    if opener is None:
        import webbrowser
        opener = webbrowser.open
    try:
        return bool(opener(url))
    except Exception:  # noqa: BLE001
        return False


def desktop_dir() -> Path:
    """The user's Desktop (CSIDL_DESKTOPDIRECTORY on Windows), else home."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.home()


def save_to_desktop(report: str) -> Path:
    """Write the report as a .txt file on the Desktop and return its path."""
    p = desktop_dir() / "Food Labeler printer report.txt"
    p.write_text(report, encoding="utf-8")
    return p


__all__ = ["build", "mailto", "issue_link", "issues_url", "ask_on_github",
           "save_to_desktop", "SUBJECT"]
