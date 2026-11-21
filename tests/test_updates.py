"""Check for updates (updates.py): version numbers, the address checks, GitHub's
answers and the words the update window shows. GitHub is never contacted:
every answer here is made up (and conftest.py makes a real connection fail)."""
import inspect
import re
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from food_labeler import __version__, updates

API = "https://api.github.com/repos/lilfade/food-labeler/releases"
LATEST = API + "/latest"
LIST = API + "?per_page=10"
PAGE = "https://github.com/lilfade/food-labeler/releases/"


def release(tag, date="2026-12-15", body="", draft=False, prerelease=False, html_url=None):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease,
            "published_at": f"{date}T10:00:00Z", "body": body,
            "html_url": html_url if html_url is not None else PAGE + "tag/" + tag}


class FakeGitHub:
    """Answers GET by address; anything else is a 404. Records what was asked."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def __call__(self, url, limit):
        updates.check_url(url)
        self.asked.append(url)
        v = self.pages.get(url)
        if v is None:
            raise updates.HttpStatus(404)
        if isinstance(v, Exception):
            raise v
        data = v if isinstance(v, bytes) else json.dumps(v).encode()
        if len(data) > limit:
            raise updates.UpdateError(updates.BAD_ANSWER)
        return data


# --------------------------------------------------------------------------
# version numbers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("v1.6.0", (1, 6, 0)), ("1.6.0", (1, 6, 0)), ("V1.6.0", (1, 6, 0)),
    ("1.6", (1, 6, 0)), ("2", (2, 0, 0)), (" v1.10.3 ", (1, 10, 3)),
    ("v1.7.0-beta.1", (1, 7, 0)), ("1.2.3.4", (1, 2, 3, 4)),
    ("junk", None), ("", None), (None, None), (160, None), ("v", None),
    ("1.x.0", None), ("release-1.6", None), ("1..2", None), ("9" * 7, None),
])
def test_parse_version(text, want):
    assert updates.parse_version(text) == want


def test_compare_versions_as_numbers():
    assert updates.compare("v1.10.0", "1.9.9") == 1          # not compared as text
    assert updates.compare("1.6", "v1.6.0") == 0
    assert updates.compare("1.5.2", "1.6.0") == -1
    assert updates.compare("1.6.0.1", "1.6.0") == 1
    assert updates.compare("nightly", "1.6.0") is None
    assert updates.compare("1.6.0", "") is None


def test_version_words():
    assert updates.version_words("v1.7.0") == "1.7.0"
    assert updates.version_words("v2") == "2.0.0"
    assert updates.version_words("  spring   edition ") == "spring edition"
    assert updates.version_words("x" * 100) == "x" * 40


# --------------------------------------------------------------------------
# addresses
# --------------------------------------------------------------------------

def test_repository_comes_from_the_issues_address():
    assert updates.repo_from_config({}) == ("lilfade", "food-labeler")
    assert updates.repo_from_config(
        {"issues_url": "https://github.com/someone/my-labels/issues"}) == ("someone", "my-labels")
    for bad in ("http://github.com/a/b/issues", "https://evil.example/a/b/issues",
                "https://github.com/a/b/pulls", "https://github.com/../b/issues", 42):
        assert updates.repo_from_config({"issues_url": bad}) == ("lilfade", "food-labeler")


def test_api_addresses():
    assert updates.latest_url("lilfade", "food-labeler") == LATEST
    assert updates.list_url("lilfade", "food-labeler") == LIST


@pytest.mark.parametrize("url", [
    "http://api.github.com/repos/x/y/releases/latest",
    "https://example.com/releases/latest",
    "https://api.github.com.evil.example/x",
    "https://evil.example/?u=https://api.github.com/",
    "https://user:pw@api.github.com/x",
    "https://api.github.com:8443/x",
    "https://objects.githubusercontent.com/x",
    "ftp://github.com/x",
    "https://[::1]/x",
    "javascript:alert(1)",
])
def test_only_github_over_https(url):
    with pytest.raises(updates.UpdateError):
        updates.check_url(url)


def test_release_page_must_be_ours():
    good = PAGE + "tag/v1.7.0"
    assert updates.release_page(good, "lilfade", "food-labeler") == good
    assert updates.release_page("https://github.com/LilFade/Food-Labeler/releases/tag/v1.7.0",
                                "lilfade", "food-labeler").endswith("/tag/v1.7.0")
    fallback = "https://github.com/lilfade/food-labeler/releases/latest"
    for bad in ("https://github.com/someone-else/food-labeler/releases/tag/v1.7.0",
                "https://github.com/lilfade/food-labeler-fake/releases/tag/v1.7.0",
                "http://github.com/lilfade/food-labeler/releases/tag/v1.7.0",
                "https://github.com.evil.example/lilfade/food-labeler/releases/",
                "https://github.com/lilfade/food-labeler/issues/1",
                "https://github.com/lilfade/food-labeler/releases/../../other/repo",
                "https://github.com/lilfade/food-labeler/releases/tag/v1 x",
                "https://github.com/lilfade/food-labeler/releases/tag/v1?go=https://evil",
                "", None, 7):
        assert updates.release_page(bad, "lilfade", "food-labeler") == fallback


def test_redirect_off_the_list_is_refused():
    h = updates._SafeRedirect()
    req = urllib.request.Request(LATEST)
    for target in ("https://evil.example/x", "http://api.github.com/x",
                   "https://objects.githubusercontent.com/x"):
        with pytest.raises(updates.UpdateError):
            h.redirect_request(req, None, 302, "Found", {}, target)
    # within the list it is followed
    new = h.redirect_request(req, None, 301, "Moved", {},
                             "https://api.github.com/repositories/1/releases/latest")
    assert new.full_url.startswith("https://api.github.com/")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Resp:
    def __init__(self, data=b"{}", status=200, length=None):
        self.f = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Length": str(length)} if length else {}

    def read(self, n):
        return self.f.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(monkeypatch, answer):
    seen = {}

    class Opener:
        def open(self, req, timeout=None):
            seen["req"], seen["timeout"] = req, timeout
            if isinstance(answer, BaseException):
                raise answer
            return answer
    monkeypatch.setattr(updates.urllib.request, "build_opener", lambda *a: Opener())
    return seen


def test_request_says_only_who_is_asking(monkeypatch):
    seen = fake_opener(monkeypatch, Resp(b'{"a": 1}'))
    assert updates.http_get(LATEST) == b'{"a": 1}'
    req = seen["req"]
    assert seen["timeout"] == updates.TIMEOUT <= 15
    assert req.full_url == LATEST and req.get_method() == "GET" and req.data is None
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers == {"user-agent": f"FoodLabeler/{__version__}",
                       "accept": "application/vnd.github+json"}


def test_never_asks_another_host(monkeypatch):
    seen = fake_opener(monkeypatch, Resp())
    with pytest.raises(updates.UpdateError):
        updates.http_get("https://example.com/releases/latest")
    assert not seen


def test_size_cap(monkeypatch):
    fake_opener(monkeypatch, Resp(b"x" * (updates.MAX_BYTES + 1)))
    with pytest.raises(updates.UpdateError, match="couldn't be read"):
        updates.http_get(LATEST)
    fake_opener(monkeypatch, Resp(b"", length=10 ** 9))            # Content-Length says so
    with pytest.raises(updates.UpdateError, match="couldn't be read"):
        updates.http_get(LATEST)
    assert updates.MAX_BYTES <= 1024 * 1024


@pytest.mark.parametrize("err", [
    urllib.error.URLError(OSError("Name or service not known")),
    TimeoutError(), OSError("Network is unreachable"), ConnectionResetError(),
])
def test_offline_and_timeout(monkeypatch, err):
    fake_opener(monkeypatch, err)
    with pytest.raises(updates.UpdateError) as e:
        updates.http_get(LATEST)
    assert str(e.value) == updates.OFFLINE == ("Couldn't reach GitHub — check the internet "
                                               "and try again.")


def test_http_errors_become_statuses(monkeypatch):
    fake_opener(monkeypatch, urllib.error.HTTPError(LATEST, 403, "Forbidden", {}, None))
    with pytest.raises(updates.HttpStatus) as e:
        updates.http_get(LATEST)
    assert e.value.status == 403


@pytest.mark.parametrize("status, message", [
    (403, updates.BUSY), (429, updates.BUSY), (404, updates.NO_RELEASES),
    (500, updates.PROBLEM), (502, updates.PROBLEM),
])
def test_status_messages(status, message):
    web = FakeGitHub({LATEST: updates.HttpStatus(status)})
    with pytest.raises(updates.UpdateError) as e:
        updates.check(get=web, current="1.6.0")
    assert str(e.value) == message
    assert updates.BUSY == "GitHub is busy — try again in a while."


@pytest.mark.parametrize("data", [b"not json", b"\xff\xfe", b"[" * 100000 + b"]" * 100000,
                                  b"[]", b'"v1.7.0"', b'{"name": "no tag"}', b"null"])
def test_bad_answers(data):
    web = FakeGitHub({LATEST: data})
    with pytest.raises(updates.UpdateError) as e:
        updates.check(get=web, current="1.6.0")
    assert str(e.value) in (updates.BAD_ANSWER, updates.NO_RELEASES)


def test_offline_during_check_is_friendly():
    web = FakeGitHub({LATEST: updates.UpdateError(updates.OFFLINE)})
    with pytest.raises(updates.UpdateError, match="Couldn't reach GitHub"):
        updates.check(get=web, current="1.6.0")


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def test_up_to_date_asks_once():
    web = FakeGitHub({LATEST: release("v1.6.0")})
    res = updates.check(get=web, current="1.6.0")
    assert res.status == "current" and web.asked == [LATEST]
    assert res.all_url == "https://github.com/lilfade/food-labeler/releases"
    w = updates.window_text(res)
    assert w["title"] == "You have the newest version (1.6.0)." and not w["download"]


def test_this_copy_newer_than_github():
    res = updates.check(get=FakeGitHub({LATEST: release("v1.5.2")}), current="1.6.0")
    assert res.status == "older"
    w = updates.window_text(res)
    assert w["title"] == "You have the newest version (1.6.0)." and "1.5.2" in w["detail"]
    assert not w["download"]


def test_newer_version_with_notes_of_versions_in_between():
    web = FakeGitHub({
        LATEST: release("v1.8.0", "2027-01-10", "## New\n- **Big** thing"),
        LIST: [release("v1.9.0-beta", prerelease=True, body="beta"),
               release("v2.0.0", draft=True, body="draft"),
               release("v1.8.0", "2027-01-10", "dup"),
               release("v1.6.1", "2026-12-01", "- small fix"),
               release("v1.7.0", "2026-12-15", "- seven"),
               release("v1.6.0", "2026-11-25", "this one"),
               release("v1.5.0", body="old"),
               release("nightly", body="junk"), "not a dict", {"tag_name": 7}],
    })
    res = updates.check(get=web, current="1.6.0")
    assert res.status == "newer" and web.asked == [LATEST, LIST]
    assert [r.version for r in res.newer] == ["1.8.0", "1.7.0", "1.6.1"]
    assert res.latest.url == PAGE + "tag/v1.8.0"
    w = updates.window_text(res)
    assert w["title"] == "Food Labeler 1.8.0 is available (you have 1.6.0)"
    assert w["detail"] == "Published January 10, 2027." and w["download"]
    texts = [t for _k, t in w["notes"]]
    assert texts[0] == "Version 1.8.0 — January 10, 2027"
    assert ("heading", "New") in w["notes"] and ("bullet", "• Big thing") in w["notes"]
    assert "Version 1.7.0 — December 15, 2026" in texts and "• seven" in texts
    joined = "\n".join(texts)
    assert "beta" not in joined and "draft" not in joined and "this one" not in joined
    assert "old" not in joined and "dup" not in joined


def test_single_newer_version_has_no_version_line():
    web = FakeGitHub({LATEST: release("v1.7.0", body="- one"), LIST: [release("v1.7.0")]})
    w = updates.window_text(updates.check(get=web, current="1.6.0"))
    assert w["notes"] == [("bullet", "• one")]


def test_list_failure_still_shows_the_newest():
    web = FakeGitHub({LATEST: release("v1.7.0", body="- one"),
                      LIST: updates.HttpStatus(403)})
    res = updates.check(get=web, current="1.6.0")
    assert res.status == "newer" and [r.version for r in res.newer] == ["1.7.0"]


def test_draft_or_prerelease_latest_is_ignored():
    for r in (release("v9.0.0", draft=True), release("v9.0.0", prerelease=True)):
        with pytest.raises(updates.UpdateError, match="No versions"):
            updates.check(get=FakeGitHub({LATEST: r}), current="1.6.0")


def test_unparsable_tag_is_shown_as_it_is():
    web = FakeGitHub({LATEST: release("spring-edition", body="Nice")})
    res = updates.check(get=web, current="1.6.0")
    assert res.status == "unknown" and web.asked == [LATEST]
    w = updates.window_text(res)
    assert "spring-edition" in w["title"] and w["download"]
    assert w["notes"] == [("text", "Nice")]


def test_release_for_another_repository_opens_our_page():
    web = FakeGitHub({LATEST: release(
        "v1.7.0", html_url="https://github.com/evil/food-labeler/releases/tag/v1.7.0")})
    res = updates.check(get=web, current="1.6.0")
    assert res.latest.url == "https://github.com/lilfade/food-labeler/releases/latest"


def test_other_repository_from_config():
    api = "https://api.github.com/repos/someone/labels/releases/latest"
    web = FakeGitHub({api: release(
        "v1.6.0", html_url="https://github.com/someone/labels/releases/tag/v1.6.0")})
    res = updates.check(get=web, config={"issues_url": "https://github.com/someone/labels/issues"},
                        current="1.6.0")
    assert web.asked == [api] and res.all_url == "https://github.com/someone/labels/releases"


def test_empty_notes_and_missing_date():
    r = release("v1.7.0")
    r["published_at"] = None
    r["body"] = None
    w = updates.window_text(updates.check(get=FakeGitHub({LATEST: r}), current="1.6.0"))
    assert w["detail"] == "" and w["notes"] == [("text", "(No notes for this version.)")]


def test_date_words():
    assert updates.date_words("2026-11-21T10:00:00Z") == "November 21, 2026"
    assert updates.date_words("yesterday") == "" and updates.date_words(None) == ""


# --------------------------------------------------------------------------
# release notes as plain text
# --------------------------------------------------------------------------

def test_markdown_to_plain_text():
    md = ("## 1.7.0 — 2026-12-15\r\n\r\nEasier printing.\n\n"
          "- **Bold** and *italic* and __also__ and _this_, snake_case_name kept\n"
          "- `__init__.py` and `*stars*` stay as written\n"
          "  - nested [the guide](https://example.org/guide) and [local](docs/x.md)\n"
          "* star bullet ![logo](logo.png) <https://lilfade.github.io/food-labeler/>\n"
          "1. first\n"
          "> quoted &amp; escaped \\*not italic\\*\n"
          "---\n"
          "```\ncode  line\n```\n"
          "### Heading ###\nA paragraph that\nwraps over lines.\n\n\n\n")
    lines = updates.notes_lines(md)
    assert lines[0] == ("heading", "1.7.0 — 2026-12-15")
    text = updates.plain_notes(md)
    assert "• Bold and italic and also and this, snake_case_name kept" in text
    assert "• __init__.py and *stars* stay as written" in text
    assert "    • nested the guide (https://example.org/guide) and local" in text
    assert "• star bullet logo https://lilfade.github.io/food-labeler/" in text
    assert "1. first" in text
    assert "quoted & escaped *not italic*" in text
    assert "code  line" in text and "```" not in text and "---" not in text
    assert ("blank", "") in lines and ("heading", "Heading") in lines
    assert "A paragraph that wraps over lines." in text
    assert "#" not in text and "**" not in text and "](" not in text
    assert not text.endswith("\n") and "\n\n\n" not in text


def test_notes_drop_control_characters_and_are_capped():
    assert updates.plain_notes("a\x00b\x1b[31mc‮d") == "ab[31mcd"
    long = "\n".join(f"- line {i} " + "x" * 80 for i in range(1000))
    lines = updates.notes_lines(long)
    assert sum(len(t) + 1 for _k, t in lines) <= updates.MAX_NOTES_CHARS + 2
    assert lines[-1] == ("text", "…")
    assert updates.notes_lines("") == [] and updates.notes_lines(None) == []


def test_real_changelog_reads_well():
    md = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    text = updates.plain_notes(md)
    assert "**" not in text and "\n## " not in text and "• " in text


# --------------------------------------------------------------------------
# only when asked
# --------------------------------------------------------------------------

def test_never_checks_by_itself():
    """Nothing but the update window calls updates.check, and nothing at start-up."""
    root = Path(__file__).resolve().parents[1] / "food_labeler"
    for path in root.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if path.name in ("updates.py", "dialogs.py"):
            continue
        assert "updates.check" not in src and "updates.http_get" not in src, path.name
        if path.name != "__main__.py":           # --selftest checks the parts are there
            assert not re.search(r"import\b[^\n]*\bupdates\b", src), path.name
    from food_labeler import dialogs
    src = inspect.getsource(dialogs)
    outside = src.replace(inspect.getsource(dialogs.UpdateDialog), "")
    assert "updates.check" not in outside
    settings_src = inspect.getsource(dialogs.SettingsDialog)
    assert "UpdateDialog(self).run()" in settings_src and "lambda" in settings_src


def test_privacy_and_how_to_words():
    assert "only goes online when you press" in updates.PRIVACY
    assert "sends nothing about you" in updates.PRIVACY
    assert updates.HOW_TO == ("Download FoodLabeler.exe from that page and run it. Your "
                              "labels, products and settings are kept.")
