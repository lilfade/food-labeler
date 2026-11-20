"""The version number lives only in food_labeler/__init__.py; everything reads it."""
import re
import subprocess
import sys
from pathlib import Path

import food_labeler
from food_labeler import __main__ as entry

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", food_labeler.__version__)


def test_version_flag(capsys):
    assert entry.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == food_labeler.__version__


def test_spec_reads_version_from_package():
    spec = (ROOT / "food_labeler.spec").read_text(encoding="utf-8")
    assert "__version__" in spec and food_labeler.__version__ not in spec


def test_changelog_mentions_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {food_labeler.__version__}" in text


def test_selftest_headless():
    # Runs in a child process: renders and encodes every label, never opens a window.
    r = subprocess.run([sys.executable, "-m", "food_labeler", "--selftest"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest OK" in r.stdout
