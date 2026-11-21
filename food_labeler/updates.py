"""Check for updates: is there a newer Food Labeler on GitHub?

Only when the person presses *Check for updates…* (Settings → About). Never
at start-up and never by itself: Food Labeler works offline and only goes
online when asked.

``check()`` asks the GitHub API, without any key or account, for the newest
published release of the project (owner/repository from app_config.json's
``issues_url``, see report.issues_url):

1. ``GET https://api.github.com/repos/<owner>/<repo>/releases/latest``. Its
   ``tag_name`` ("v1.6.0") is compared with ``__version__`` as numbers.
2. Only if that one is newer: ``GET …/releases?per_page=10``, for the notes
   of every version between this one and the newest (newest first). If that
   second answer fails, the newest version's own notes are shown anyway.

Nothing about the person is sent: the requests carry only
``User-Agent: FoodLabeler/<version>`` and ``Accept: application/vnd.github+json``.
Every address is checked (https only, api.github.com for the API, redirects
only within the allow-list), answers are capped at ``MAX_BYTES`` and the
time-out is short. The release page that *Download the new version* opens
must be on https://github.com/<owner>/<repo>/releases/, otherwise our own
releases page is opened instead. Nothing is ever downloaded or installed by
Food Labeler itself; the person downloads the new program from that page.

Drafts and pre-releases are ignored. A tag that isn't a version number is
shown as it is ("unknown": we can't tell whether it is newer).

All of this runs on a worker thread; nothing here touches Tk. The words the
update window shows are made here too (``window_text``), so they are tested
without a window.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import __version__, fontget, report

log = logging.getLogger("food_labeler.updates")

API_HOST = "api.github.com"
WEB_HOST = "github.com"
ALLOWED_HOSTS = {API_HOST, WEB_HOST}
TIMEOUT = 10
MAX_BYTES = 1024 * 1024
PER_PAGE = 10
MAX_NOTES_CHARS = 20000          # per release, after turning it into plain text
DEFAULT_REPO = ("lilfade", "food-labeler")

OFFLINE = "Couldn't reach GitHub — check the internet and try again."
BUSY = "GitHub is busy — try again in a while."
NO_RELEASES = "No versions of Food Labeler have been published on GitHub yet."
BAD_ANSWER = "GitHub's answer couldn't be read. Please try again in a while."
PROBLEM = "GitHub had a problem. Please try again in a while."
ONLY_GITHUB = "Food Labeler only checks for updates on GitHub."

PRIVACY = ("Food Labeler only goes online when you press “Check for updates”. It asks "
           "GitHub which version is the newest and sends nothing about you or your labels.")
HOW_TO = ("Download FoodLabeler.exe from that page and run it. Your labels, products and "
          "settings are kept.")


class UpdateError(Exception):
    """Something went wrong; the message is friendly and can be shown as is."""


class HttpStatus(Exception):
    """An HTTP answer other than 200 (internal; turned into an UpdateError)."""

    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


# --------------------------------------------------------------------------
# version numbers
# --------------------------------------------------------------------------

_VERSION = re.compile(r"[vV]?\s*(\d{1,6}(?:\.\d{1,6}){0,3})(?:[-+ ].*)?")


def parse_version(text) -> tuple[int, ...] | None:
    """(1, 6, 0) from "v1.6.0", "1.6.0", "1.6" or "V1.6.0-beta"; None for anything
    that isn't a version number. Missing parts count as 0 ("1.6" is 1.6.0)."""
    if not isinstance(text, str):
        return None
    m = _VERSION.fullmatch(text.strip()[:64])
    if not m:
        return None
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def compare(a, b) -> int | None:
    """-1, 0 or 1 as version ``a`` is older, the same or newer than ``b``;
    None if either isn't a version number."""
    va, vb = parse_version(a), parse_version(b)
    if va is None or vb is None:
        return None
    n = max(len(va), len(vb))
    va, vb = va + (0,) * (n - len(va)), vb + (0,) * (n - len(vb))
    return (va > vb) - (va < vb)


def version_words(tag: str) -> str:
    """"1.6.0" for "v1.6.0"; an unparsable tag is shown as it is (tidied)."""
    v = parse_version(tag)
    if v is None:
        return " ".join(str(tag or "").split())[:40] or "?"
    return ".".join(str(x) for x in v)


# --------------------------------------------------------------------------
# addresses
# --------------------------------------------------------------------------

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")


def repo_from_config(config: dict | None = None) -> tuple[str, str]:
    """(owner, repository) from app_config.json's issues_url (checked by
    report.issues_url: an https://github.com/<owner>/<repo>/issues page)."""
    url = report.issues_url(config)
    parts = urllib.parse.urlsplit(url).path.strip("/").split("/")
    if len(parts) == 3 and parts[2] == "issues" and _NAME.fullmatch(parts[0]) \
            and _REPO.fullmatch(parts[1]) and parts[1] not in (".", ".."):
        return parts[0], parts[1]
    return DEFAULT_REPO


def check_url(url: str, hosts=ALLOWED_HOSTS) -> str:
    """Allow only https addresses on ``hosts``; raise UpdateError otherwise."""
    try:
        u = urllib.parse.urlsplit(str(url))
        port = u.port
    except ValueError:
        raise UpdateError(ONLY_GITHUB) from None
    if u.scheme != "https" or (u.hostname or "").lower() not in hosts or u.username \
            or u.password or port not in (None, 443):
        raise UpdateError(ONLY_GITHUB)
    return url


def latest_url(owner: str, repo: str) -> str:
    return check_url(f"https://{API_HOST}/repos/{owner}/{repo}/releases/latest", {API_HOST})


def list_url(owner: str, repo: str) -> str:
    return check_url(f"https://{API_HOST}/repos/{owner}/{repo}/releases?per_page={PER_PAGE}",
                     {API_HOST})


def releases_page(owner: str, repo: str) -> str:
    """Our own page with every version (always safe to open)."""
    return f"https://{WEB_HOST}/{owner}/{repo}/releases"


def release_page(html_url, owner: str, repo: str) -> str:
    """The release's own page if it really is one of ours
    (https://github.com/<owner>/<repo>/releases/…), else our releases page."""
    url = str(html_url or "")
    prefix = f"https://{WEB_HOST}/{owner}/{repo}/releases/"
    ok = (url[:len(prefix)].lower() == prefix.lower() and len(url) <= 300
          and re.fullmatch(r"[A-Za-z0-9._~%/+-]*", url[len(prefix):]) is not None
          and ".." not in url[len(prefix):])
    if ok:
        try:
            check_url(url, {WEB_HOST})
        except UpdateError:
            ok = False
    if not ok:
        if url:
            log.info("release page address refused: %r", url[:200])
        return releases_page(owner, repo) + "/latest"
    return url


# --------------------------------------------------------------------------
# HTTP (the only part that touches the network)
# --------------------------------------------------------------------------

class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to allowed hosts (https)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url: str, limit: int = MAX_BYTES) -> bytes:
    """GET an allowed address. Raises HttpStatus for answers other than 200 and
    UpdateError (friendly) for no internet, time-outs and oversized answers."""
    check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect())
    req = urllib.request.Request(url, headers={
        "User-Agent": f"FoodLabeler/{__version__}",
        "Accept": "application/vnd.github+json"})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise HttpStatus(status)
            return fontget.read_limited(resp, limit, UpdateError(BAD_ANSWER))
    except urllib.error.HTTPError as e:
        raise HttpStatus(e.code) from None
    except (socket.timeout, TimeoutError):
        raise UpdateError(OFFLINE) from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, UpdateError):
            raise e.reason from None
        log.info("update check failed: %s", e)
        raise UpdateError(OFFLINE) from None
    except OSError as e:
        log.info("update check failed: %s", e)
        raise UpdateError(OFFLINE) from None


def _get_json(get, url):
    """``get(url, limit)`` and parse JSON; friendly errors (404 -> None)."""
    try:
        data = get(url, MAX_BYTES)
    except HttpStatus as e:
        if e.status == 404:
            return None
        if e.status in (403, 429):
            raise UpdateError(BUSY) from None
        log.info("GitHub answered %s for %s", e.status, url)
        raise UpdateError(PROBLEM) from None
    if data is None or len(data) > MAX_BYTES:
        raise UpdateError(BAD_ANSWER)
    try:
        return json.loads(bytes(data).decode("utf-8"))
    except (ValueError, RecursionError, UnicodeDecodeError):
        raise UpdateError(BAD_ANSWER) from None


# --------------------------------------------------------------------------
# release notes: simple Markdown -> plain text
# --------------------------------------------------------------------------

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


def _inline(text: str) -> str:
    """Links, images, bold, italic and code marks out of a line or paragraph. What is inside
    `code` is kept exactly (so `__init__.py` stays as it is)."""
    codes: list[str] = []

    def keep(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!<>~|])", keep, text)         # \* stays *
    text = re.sub(r"`+([^`]*)`+", keep, text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)                  # images: alt
    text = re.sub(r"\[([^\]]+)\]\(\s*(https?://[^)\s]+)[^)]*\)", r"\1 (\2)", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)                     # other links
    text = re.sub(r"<(https?://[^>\s]+)>", r"\1", text)                     # <autolinks>
    text = re.sub(r"</?[A-Za-z][^>]{0,200}>", "", text)                     # html tags
    text = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = html.unescape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def notes_lines(md) -> list[tuple[str, str]]:
    """Release notes as [(kind, text)]: kind is "heading", "bullet", "text" or
    "blank". Headings lose their #s, "- " bullets become "• ", and bold,
    italic, code and link marks go ([text](url) -> "text (url)"). Lines that
    only continue a paragraph or bullet are joined to it (the window wraps
    them). At most MAX_NOTES_CHARS characters are kept."""
    md = _CTRL.sub("", str(md or "")[:200000].replace("\r\n", "\n").replace("\r", "\n"))
    # [kind, prefix, raw text]; marks are taken out after joining, so **bold**
    # over two lines works. "code" lines are kept exactly and never joined.
    out: list[list[str]] = []
    fence = False
    for raw in md.split("\n"):
        line = raw.rstrip().replace("\t", "    ")
        if re.match(r"^\s*(```|~~~)", line):
            fence = not fence
            continue
        if fence:
            out.append(["code", "", line])
            continue
        stripped = line.strip()
        if not stripped or re.fullmatch(r"(-\s*){3,}|(\*\s*){3,}|(_\s*){3,}|=+", stripped):
            out.append(["blank", "", ""])
            continue
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            out.append(["heading", "", m.group(1)])
            continue
        quote = re.match(r"^\s*>", line) is not None
        line = re.sub(r"^\s*(>\s?)+", "", line)
        m = re.match(r"^(\s*)(?:[-*+]|(\d{1,3}[.)]))\s+(?:\[[ xX]\]\s+)?(.*)$", line)
        if m:
            depth = min(4, len(m.group(1)) // 2)
            mark = (m.group(2) + " ") if m.group(2) else "\u2022 "
            out.append(["bullet", "    " * depth + mark, m.group(3)])
            continue
        kind = "quote" if quote else "text"
        prev = out[-1][0] if out else ""
        if prev == kind or (prev == "bullet" and not quote):
            out[-1][2] += " " + line.strip()
        else:
            out.append([kind, "", line.strip()])
    # no blank lines at the ends, at most one in a row; a heading gets one before it
    tidy: list[tuple[str, str]] = []
    for kind, prefix, raw in out:
        text = raw if kind == "code" else prefix + _inline(raw)
        kind = "text" if kind in ("code", "quote") else kind
        if kind == "blank" and (not tidy or tidy[-1][0] == "blank"):
            continue
        if kind == "heading" and tidy and tidy[-1][0] != "blank":
            tidy.append(("blank", ""))
        tidy.append((kind, text))
    while tidy and tidy[-1][0] == "blank":
        tidy.pop()
    # very long notes are cut (the whole text is on the release page)
    kept, total = [], 0
    for kind, text in tidy:
        total += len(text) + 1
        if total > MAX_NOTES_CHARS:
            kept.append(("text", "…"))
            break
        kept.append((kind, text))
    return kept


def plain_notes(md) -> str:
    """notes_lines() as one plain text."""
    return "\n".join(t for _k, t in notes_lines(md))


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

@dataclass
class Release:
    """One published version, ready to show."""
    tag: str
    version: str                    # "1.6.0", or the tag as it is when it isn't a number
    date: str                       # "November 21, 2026" or ""
    notes: str                      # Markdown, as GitHub has it
    url: str                        # checked release page (or our releases page)


@dataclass
class Result:
    """What check() found. status: "newer", "current", "older" (this copy is newer
    than anything published) or "unknown" (the newest tag isn't a version number)."""
    status: str
    current: str
    latest: Release
    all_url: str
    newer: list = field(default_factory=list)     # Releases newer than this one, newest first


def date_words(iso) -> str:
    """"November 21, 2026" from GitHub's "2026-11-21T10:00:00Z"; "" if unreadable."""
    try:
        d = dt.date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return ""
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _is_published(r) -> bool:
    return isinstance(r, dict) and not r.get("draft") and not r.get("prerelease") \
        and isinstance(r.get("tag_name"), str) and bool(r.get("tag_name").strip())


def _release(r: dict, owner: str, repo: str) -> Release:
    body = r.get("body")
    return Release(tag=r["tag_name"].strip()[:64], version=version_words(r["tag_name"]),
                   date=date_words(r.get("published_at") or r.get("created_at")),
                   notes=body[:200000] if isinstance(body, str) else "",
                   url=release_page(r.get("html_url"), owner, repo))


def check(get=None, config: dict | None = None, current: str = __version__) -> Result:
    """Ask GitHub for the newest published version and compare it with ``current``.

    ``get(url, limit) -> bytes`` does the HTTP (``http_get``; tests pass a fake).
    Raises UpdateError with a friendly message."""
    get = get or http_get
    owner, repo = repo_from_config(config)
    all_url = releases_page(owner, repo)
    data = _get_json(get, latest_url(owner, repo))
    if data is None:
        raise UpdateError(NO_RELEASES)
    if not isinstance(data, dict) or "tag_name" not in data:
        raise UpdateError(BAD_ANSWER)
    if not _is_published(data):            # "latest" is never a draft or pre-release
        raise UpdateError(NO_RELEASES)
    latest = _release(data, owner, repo)
    order = compare(latest.tag, current)
    if order is None:
        return Result("unknown", current, latest, all_url, [latest])
    if order <= 0:
        return Result("current" if order == 0 else "older", current, latest, all_url)
    newer = [latest]
    try:
        listing = _get_json(get, list_url(owner, repo))
    except UpdateError as e:
        log.info("release list not read: %s", e)
        listing = None
    seen = {parse_version(latest.tag)}
    for r in listing if isinstance(listing, list) else []:
        if not _is_published(r):
            continue
        v = parse_version(r["tag_name"])
        if v is None or v in seen or compare(r["tag_name"], current) != 1 \
                or compare(r["tag_name"], latest.tag) != -1:
            continue
        seen.add(v)
        newer.append(_release(r, owner, repo))
    newer[1:] = sorted(newer[1:], key=lambda x: parse_version(x.tag), reverse=True)
    return Result("newer", current, latest, all_url, newer[:PER_PAGE])


# --------------------------------------------------------------------------
# what the window says
# --------------------------------------------------------------------------

def window_text(res: Result) -> dict:
    """The update window's words: {"title", "detail", "download" (bool),
    "notes": [(kind, text)]}. Pure, so it is tested without a window."""
    cur = version_words(res.current)
    lat = res.latest
    if res.status == "current":
        return {"title": f"You have the newest version ({cur}).", "detail": "",
                "download": False, "notes": []}
    if res.status == "older":
        return {"title": f"You have the newest version ({cur}).",
                "detail": f"The newest version published on GitHub is {lat.version}.",
                "download": False, "notes": []}
    if res.status == "unknown":
        title = f"The newest version on GitHub is “{lat.version}” (you have {cur})."
        detail = "Food Labeler can't tell whether that is newer than yours."
    else:
        title = f"Food Labeler {lat.version} is available (you have {cur})"
        detail = f"Published {lat.date}." if lat.date else ""
    notes: list[tuple[str, str]] = []
    many = len(res.newer) > 1
    for r in res.newer:
        if many:
            if notes:
                notes.append(("blank", ""))
            notes.append(("version", f"Version {r.version}" + (f" — {r.date}" if r.date
                                                                else "")))
        lines = notes_lines(r.notes)
        notes.extend(lines if lines else [("text", "(No notes for this version.)")])
    return {"title": title, "detail": detail, "download": True, "notes": notes}


__all__ = ["check", "parse_version", "compare", "notes_lines", "plain_notes", "window_text",
           "UpdateError", "Result", "Release"]
