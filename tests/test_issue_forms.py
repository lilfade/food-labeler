"""The GitHub issue forms people use to ask for help (.github/ISSUE_TEMPLATE).

Reads files only. The full YAML check needs PyYAML, which is not part of the
locked test tools, so it is skipped where PyYAML isn't installed; the plain
text checks always run."""
import re
from pathlib import Path

import pytest

from food_labeler import report

FORMS = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"
EXPECTED = {"printer-not-working.yml": "printer", "add-my-printer.yml": "printer",
            "something-wrong.yml": "bug", "state-wording.yml": "state-rules"}


def test_the_forms_are_there_and_the_app_links_to_one():
    assert {p.name for p in FORMS.glob("*.yml")} == set(EXPECTED) | {"config.yml"}
    assert report.PRINTER_TEMPLATE in EXPECTED


@pytest.mark.parametrize("name, label", sorted(EXPECTED.items()))
def test_form_text(name, label):
    text = (FORMS / name).read_text(encoding="utf-8")
    assert "\t" not in text
    assert re.search(r"^name: \S", text, re.M) and re.search(r"^description: \S", text, re.M)
    assert re.search(r"^body:$", text, re.M)
    assert f'labels: ["{label}"]' in text


def test_config_keeps_email_as_a_quiet_fallback():
    text = (FORMS / "config.yml").read_text(encoding="utf-8")
    assert "blank_issues_enabled: true" in text
    assert "hello@highthymekitchen.com" in text
    assert re.search(r"url: https://", text)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_form_yaml(name):
    yaml = pytest.importorskip("yaml")
    form = yaml.safe_load((FORMS / name).read_text(encoding="utf-8"))
    assert set(form) <= {"name", "description", "title", "labels", "body", "assignees"}
    assert form["labels"] == [EXPECTED[name]]
    ids = [b["id"] for b in form["body"] if "id" in b]
    assert len(ids) == len(set(ids))
    for b in form["body"]:
        assert b["type"] in {"markdown", "input", "textarea", "dropdown", "checkboxes"}
        assert b["attributes"].get("label") or b["type"] == "markdown"
        if b["type"] == "dropdown":
            assert b["attributes"]["options"]
    assert any(b["type"] != "markdown" and b.get("validations", {}).get("required")
               for b in form["body"])


def test_config_yaml():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load((FORMS / "config.yml").read_text(encoding="utf-8"))
    assert cfg["blank_issues_enabled"] is True
    for link in cfg["contact_links"]:
        assert set(link) == {"name", "url", "about"} and link["url"].startswith("https://")
