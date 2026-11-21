"""Clickable web addresses (only plain http/https ever open), scrolling the field
with the keyboard focus into view, and the address's State box filled in from
the chosen state. All without opening a window."""
import pytest

from food_labeler import bakery, widgets


@pytest.mark.parametrize("url", [
    "https://github.com/lilfade/food-labeler/issues",
    "http://www.example.gov/cottage-food",
    "https://fonts.google.com",
    "https://agr.example.gov/rules?page=2#labels",
    "HTTPS://EXAMPLE.COM/x",
])
def test_safe_urls_open(url):
    seen = []
    assert widgets.safe_url(url) == url
    assert widgets.open_url(url, opener=lambda u: seen.append(u) or True) is True
    assert seen == [url]


@pytest.mark.parametrize("url", [
    "", "fonts.google.com", "file:///etc/passwd", "javascript:alert(1)",
    "mailto:someone@example.com", "ftp://example.com/x", "https://", "https:///path",
    "https://user:pw@example.com/", "https://example.com/a b", "https://exa mple.com",
    "https://example.com/\nhttps://evil.example", "https://exa\x00mple.com",
    "ms-settings:bluetooth", "\\\\server\\share", "https://..example.com",
    "https://" + "a" * 2100 + ".com",
])
def test_anything_else_never_opens(url):
    seen = []
    assert widgets.safe_url(url) is None
    assert widgets.open_url(url, opener=lambda u: seen.append(u) or True) is False
    assert seen == []


def test_a_browser_that_fails_is_harmless():
    def broken(u):
        raise RuntimeError("no browser")
    assert widgets.open_url("https://example.com", opener=broken) is False


def test_addresses_found_in_messages():
    text = ("Source: https://dhhs.ne.gov/Pages/Cottage-Food.aspx. Also see fonts.google.com, "
            "or www.example.org/help! Email hello@highthymekitchen.com if you're stuck. "
            "Your settings are in settings.json and known_printers.json.")
    got = widgets.find_urls(text)
    assert got == [("https://dhhs.ne.gov/Pages/Cottage-Food.aspx",
                    "https://dhhs.ne.gov/Pages/Cottage-Food.aspx"),
                   ("fonts.google.com", "https://fonts.google.com"),
                   ("www.example.org/help", "https://www.example.org/help")]
    assert widgets.find_urls("No web address here, just 192.168.1.50:9100.") == []
    assert widgets.find_urls("(see https://example.com/a)") == [
        ("https://example.com/a", "https://example.com/a")]


def test_every_web_address_in_the_program_can_be_opened():
    """The web addresses the program shows are all ones LinkLabel will open."""
    from food_labeler import cottage, report
    from food_labeler.dialogs import PROJECT_SITE
    from food_labeler.font_dialogs import GOOGLE_FONTS
    for url in (report.issues_url(), PROJECT_SITE, GOOGLE_FONTS):
        assert widgets.safe_url(url) == url
    rules = cottage.CottageRules()
    for r in rules.states():
        for url in [r.source_url, *r.extra_sources]:
            if url:
                assert widgets.safe_url(url) == url, (r.id, url)


# ---- scrolling the focused field into view ---------------------------------------

def test_already_visible_stays_put():
    assert widgets.scroll_target(100, 30, 0, 400, 2000) is None
    assert widgets.scroll_target(500, 30, 450, 400, 2000) is None


def test_field_below_the_fold_scrolls_up_into_view():
    frac = widgets.scroll_target(900, 40, 0, 400, 2000, margin=12)
    new_top = frac * 2000
    assert new_top == pytest.approx(900 + 40 + 12 - 400)
    assert new_top <= 900 - 12 and new_top + 400 >= 900 + 40 + 12   # fully visible


def test_field_above_the_view_scrolls_down_to_it():
    frac = widgets.scroll_target(100, 40, 600, 400, 2000, margin=12)
    assert frac * 2000 == pytest.approx(88)


def test_partly_hidden_field_is_shown_whole():
    frac = widgets.scroll_target(380, 40, 0, 400, 2000, margin=12)
    assert frac * 2000 == pytest.approx(380 + 40 + 12 - 400)


def test_tall_field_shows_its_top_and_ends_are_clamped():
    assert widgets.scroll_target(500, 900, 0, 400, 2000) * 2000 == pytest.approx(488)
    assert widgets.scroll_target(1980, 20, 0, 400, 2000) * 2000 == pytest.approx(1600)
    assert widgets.scroll_target(5, 20, 300, 400, 2000) == 0.0
    assert widgets.scroll_target(10, 20, 0, 400, 300) is None    # nothing to scroll


# ---- the State box of the address -----------------------------------------------

def test_state_is_filled_in_when_empty():
    assert bakery.state_for_address("", "NE") == "NE"
    assert bakery.state_for_address("  ", "TX", "") == "TX"


def test_state_follows_a_change_of_state_it_filled_in():
    assert bakery.state_for_address("NE", "IA", "NE") == "IA"
    assert bakery.state_for_address("ne", "IA", "NE") == "IA"


def test_never_over_what_they_typed():
    assert bakery.state_for_address("Nebraska", "IA", "NE") == "Nebraska"
    assert bakery.state_for_address("KS", "NE", "IA") == "KS"


def test_custom_rules_fill_in_nothing():
    assert bakery.state_for_address("", "custom", "NE") == ""
    assert bakery.state_for_address("NE", "custom", "NE") == "NE"
    assert bakery.state_for_address("", "", "NE") == ""


def test_every_state_preset_is_a_postal_abbreviation():
    from food_labeler import cottage
    for r in cottage.CottageRules().states():
        if r.id != cottage.CUSTOM_ID:
            assert bakery.state_for_address("", r.id) == r.id and len(r.id) == 2
