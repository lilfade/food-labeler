"""The lock files and workflows stay locked down (see CONTRIBUTING.md, "Dependencies
and lock files"). These checks read files only; nothing is installed or downloaded."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCKS = ["requirements-lock.txt", "requirements-dev-lock.txt"]


def entries(name: str) -> dict[str, tuple[str, str, int]]:
    """{package: (version, marker, number of hashes)} from a lock file."""
    text = (ROOT / name).read_text(encoding="utf-8").replace("\\\n", " ")
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"([a-z0-9_.-]+)==(\S+?)(?:\s*;\s*([^-]+?))?\s+((?:--hash=sha256:"
                         r"[0-9a-f]{64}\s*)+)(?:#.*)?", line)
        assert m, f"{name}: not an exact, hashed requirement: {line[:80]}"
        out[m.group(1)] = (m.group(2), (m.group(3) or "").strip(), m.group(4).count("--hash"))
    return out


def wanted(name: str) -> set[str]:
    """Package names a requirements file asks for (following -r)."""
    out = set()
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line.startswith("-r "):
            out |= wanted(line[3:].strip())
        elif line:
            out.add(re.match(r"[A-Za-z0-9_.-]+", line).group(0).lower().replace("_", "-"))
    return out


@pytest.mark.parametrize("lock, source", [("requirements-lock.txt", "requirements.txt"),
                                          ("requirements-dev-lock.txt", "requirements-dev.txt")])
def test_lock_covers_its_requirements(lock, source):
    got = entries(lock)
    assert wanted(source) <= set(got)
    assert got["pywin32"][1] == "sys_platform == 'win32'"     # Windows-only, still locked


def test_runtime_and_dev_locks_agree():
    run, dev = entries("requirements-lock.txt"), entries("requirements-dev-lock.txt")
    for pkg, (ver, marker, _n) in run.items():
        assert dev[pkg][:2] == (ver, marker), pkg
    assert "setuptools" in dev                                # PyInstaller needs it


@pytest.mark.parametrize("wf", ["ci.yml", "release.yml"])
def test_workflows_install_only_hashed_and_pin_actions(wf):
    text = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
    installs = re.findall(r"pip install[^\n]*", text)
    assert installs and all("--require-hashes" in x for x in installs), installs
    uses = re.findall(r"uses:\s*(\S+)(.*)", text)
    assert uses
    for action, comment in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), action
        assert re.fullmatch(r"\s*# v\d+(\.\d+)*", comment), (action, comment)
