"""Cottage food labels: state rules, user edits layered on top, the Label check,
minimum statement size, net quantity, and the bakery libraries."""
import json
import shutil

import pytest

from food_labeler import bakery, cottage, model, render, settings, stocks, templates


# High Thyme Kitchen's own Nebraska label wording (apps/kitchen/models.py,
# BusinessSettings.cottage_food_disclaimer and .allergen_notice).
HTK_DISCLAIMER = ("This food was prepared in a kitchen that is not subject to regulation "
                  "and inspection by the regulatory authority and may contain allergens.")
HTK_ALLERGEN_NOTICE = ("Made in a home kitchen that also handles wheat, eggs, milk, soy, "
                       "peanuts, and tree nuts. Cross-contact is possible.")

PROFILE = dict(bakery.PROFILE_DEFAULTS, state="NE", business="High Thyme Kitchen",
               legal_entity="Example Bakes LLC", street="123 Garden Lane", city="Springfield",
               region="NE", zip="68000", phone="(555) 010-0199", email="hello@example.com",
               permit="12345")


def rules_file(tmp_path, states, updated="2026-11-20", name="rules.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"format": cottage.FORMAT, "version": 1, "updated": updated,
                             "states": states}), encoding="utf-8")
    return p


def state(sid="ZZ", text="Made in a home kitchen.", checked="2026-01-01", **kw):
    e = {"id": sid, "name": kw.pop("name", "Testland"), "verified": True,
         "statements": [{"id": "main", "text": text, "min_pt": kw.pop("min_pt", None)}],
         "required": kw.pop("required", ["product_name", "ingredients"]),
         "checked_on": checked, "source_url": "https://example.gov/cottage"}
    e.update(kw)
    return e


def cottage_doc(stock="large", **fields):
    doc = model.LabelDoc("cottage", stock, model.default_fields("cottage"))
    doc.fields.update(product="Lemon Shortbread", net="8 oz",
                      ingredients="Butter (cream, salt), wheat flour, sugar, lemon zest",
                      contains="Milk, Wheat", storage="Store in a cool, dry place")
    doc.fields.update(fields)
    return doc


def ctx_for(rules, sid, profile=PROFILE):
    return {"date_style": "us", "cottage": {"rule": rules.effective(sid).to_ctx(),
                                            "profile": profile}}


# ---------------------------------------------------------------------------
# the bundled rules
# ---------------------------------------------------------------------------

def test_bundled_rules_are_valid_and_complete():
    head, rules = cottage.parse_rules_text(cottage.BUILTIN.read_text(encoding="utf-8"))
    ids = {r.id for r in rules}
    assert len(ids - {"custom"}) == 51 and "DC" in ids and "custom" in ids
    assert head["updated"]
    for r in rules:
        if r.id == "custom":
            continue
        if r.verified:
            # every verified entry says where it came from and when it was checked
            assert r.source_url.startswith("https://") or r.source_url.startswith("http://"), r.id
            assert cottage.DATE_RE.match(r.checked_on), r.id
        else:
            assert "check with your state" in r.notes.lower(), r.id


def test_rules_schema_rejects_bad_files(tmp_path):
    bad = [
        "{nope",
        {"format": "other", "version": 1, "states": [state()]},
        {"format": cottage.FORMAT, "version": 99, "states": [state()]},
        {"format": cottage.FORMAT, "version": 1, "states": []},
        {"format": cottage.FORMAT, "version": 1, "states": [state(), state()]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(sid="zz")]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(required=["shoe_size"])]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(min_pt=200)]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(text="")]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(text="By {owner}")]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(surprise=1)]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(source_url="file:///x")]},
        {"format": cottage.FORMAT, "version": 1, "states": [state(checked_on="20 Nov")]},
    ]
    for b in bad:
        with pytest.raises(cottage.RulesError):
            cottage.parse_rules_text(b if isinstance(b, str) else json.dumps(b))
    # a byte-order mark (Windows Notepad) is fine
    ok = "﻿" + json.dumps({"format": cottage.FORMAT, "version": 1, "states": [state()]})
    assert cottage.parse_rules_text(ok)[1][0].id == "ZZ"


def test_states_list_has_custom_last():
    r = cottage.CottageRules()
    names = [s.name for s in r.states()]
    assert names[-1] == cottage.CUSTOM_NAME
    assert names[:-1] == sorted(names[:-1])


# ---------------------------------------------------------------------------
# High Thyme Kitchen's Nebraska label
# ---------------------------------------------------------------------------

def test_nebraska_preset_matches_high_thyme_kitchen():
    r = cottage.CottageRules()
    ne = r.effective("NE")
    texts = [s.text for s in ne.statements]
    assert texts == [HTK_DISCLAIMER]
    # the same words the existing package template already used
    assert model.DEFAULT_DISCLAIMER == HTK_DISCLAIMER
    assert model.DEFAULT_CROSS_CONTACT == HTK_ALLERGEN_NOTICE
    # like HTK, the producer's complete address is required
    assert "address" in ne.required and "business_name" in ne.required
    assert ne.rule.source_url.startswith("https://")


def test_nebraska_label_lines_follow_htk_layout():
    r = cottage.CottageRules()
    prof = dict(PROFILE, cross_contact=HTK_ALLERGEN_NOTICE, show_phone=True)
    res = render.render(cottage_doc("xl"), ctx_for(r, "NE", prof))
    assert not res.overflow
    keys = []
    for ln in res.layout.lines:
        if not keys or keys[-1] != ln.key:
            keys.append(ln.key)
    assert keys == ["brand", "product", "net", "ingredients", "contains", "storage", "dates",
                    "produced", "address", "contact", "permit", "statement:main",
                    "cross_contact"]
    def block(key):
        return " ".join(ln.text for ln in res.layout.lines if ln.key == key)
    assert block("produced") == "Produced by: High Thyme Kitchen · Example Bakes LLC"
    assert block("contains") == "CONTAINS: Milk, Wheat"
    assert block("address") == "123 Garden Lane Springfield, NE 68000"
    assert block("statement:main") == HTK_DISCLAIMER
    assert block("cross_contact") == HTK_ALLERGEN_NOTICE


# ---------------------------------------------------------------------------
# states checked one by one
# ---------------------------------------------------------------------------

def test_missouri_rules_from_statute_and_dhss_guidance():
    r = cottage.CottageRules()
    mo = r.effective("MO").rule
    assert mo.verified and mo.checked_on == "2026-11-21"
    # RSMo 196.298 describes the statement but gives no exact words
    assert mo.statements == []
    assert "no exact wording" in mo.notes and "Suggestion" in mo.notes.title()
    assert "not inspected by the department or local health department" in mo.notes
    # DHSS guidance: name and address, common name, ingredients, net weight, allergens
    assert set(mo.required) == {"product_name", "net_quantity", "ingredients", "allergens",
                                "business_name", "address"}
    assert not mo.metric_required and mo.min_statement_pt is None
    assert mo.source_url == "https://revisor.mo.gov/main/OneSection.aspx?section=196.298"
    assert any(u.startswith("https://health.mo.gov/") for u in mo.extra_sources)
    assert "check with your state" not in mo.notes.lower()


def test_west_virginia_rules_from_61csr38():
    r = cottage.CottageRules()
    wv = r.effective("WV").rule
    assert wv.verified and wv.checked_on == "2026-11-21"
    by_id = {s["id"]: s for s in wv.statements}
    # 61CSR38 section 7.5.a, word for word
    assert by_id["main"]["kind"] == "label"
    assert by_id["main"]["text"] == (
        "This product was made in a non-commercial kitchen that may not be subject to "
        "inspection and may contain cross-contact allergens not included in the allergen "
        "statement.")
    # 61CSR42 section 6.3.9 (potentially hazardous cottage foods) is offered as an alternative
    assert by_id["phf"]["kind"] == "alternative"
    assert "non-commercial or home kitchen" in by_id["phf"]["text"]
    assert set(wv.required) == {"product_name", "net_quantity", "ingredients", "allergens",
                                "business_name", "city_state_zip"}
    assert wv.metric_required
    assert wv.source_url.startswith("https://apps.sos.wv.gov/")
    assert any("agriculture.wv.gov" in u for u in wv.extra_sources)
    assert "private residence" in wv.notes  # the 2019 wording is named as out of date
    assert "check with your state" not in wv.notes.lower()


def test_every_bundled_state_is_verified():
    rules = cottage.CottageRules()
    unverified = [s.id for s in rules.states() if s.id != "custom" and not s.verified]
    assert unverified == []


# ---------------------------------------------------------------------------
# layering and user edits
# ---------------------------------------------------------------------------

def test_layering_bundled_update_override(tmp_path):
    builtin = rules_file(tmp_path, [state(text="Bundled words.", checked="2026-01-01")],
                         name="bundled.json")
    data = tmp_path / "data"
    r = cottage.CottageRules(data, builtin)
    assert r.effective("ZZ").statements[0].text == "Bundled words."
    # an imported update wins over the bundled file
    upd = rules_file(tmp_path, [state(text="Updated words.", checked="2026-06-01")])
    lines = r.import_file(upd)
    assert lines == ["Testland: wording updated"]
    assert r.effective("ZZ").statements[0].text == "Updated words."
    # the user's own wording wins over both
    r.set_statement("ZZ", "main", "My words.")
    eff = r.effective("ZZ")
    assert eff.statements[0].text == "My words." and eff.statements[0].edited
    assert not eff.statements[0].default_changed
    # and survives a restart
    assert cottage.CottageRules(data, builtin).effective("ZZ").statements[0].text == "My words."
    # reset to the state default
    r.reset_statement("ZZ", "main")
    assert r.effective("ZZ").statements[0].text == "Updated words."
    assert not r.effective("ZZ").statements[0].edited


def test_old_update_never_hides_newer_bundled_rules(tmp_path):
    data = tmp_path / "data"
    old_builtin = rules_file(tmp_path, [state(text="2026 words.", checked="2026-01-01")],
                             name="b1.json")
    r = cottage.CottageRules(data, old_builtin)
    r.import_file(rules_file(tmp_path, [state(text="Spring update.", checked="2026-03-01")]))
    assert r.effective("ZZ").statements[0].text == "Spring update."
    # an app update ships rules checked later than the imported file
    new_builtin = rules_file(tmp_path, [state(text="Autumn words.", checked="2026-10-01")],
                             name="b2.json")
    r2 = cottage.CottageRules(data, new_builtin)
    assert r2.effective("ZZ").statements[0].text == "Autumn words."


def test_override_survives_app_update_and_default_change_is_asked_once(tmp_path):
    data = tmp_path / "data"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    builtin = app_dir / "cottage_rules.json"
    shutil.copy(rules_file(tmp_path, [state(text="Old words.",
                                            required=["product_name", "ingredients"])]),
                builtin)
    r = cottage.CottageRules(data, builtin)
    r.set_statement("ZZ", "main", "My own words.")
    r.set_required("ZZ", ["product_name", "ingredients", "phone"])
    overrides = (data / cottage.OVERRIDES_NAME).read_text(encoding="utf-8")
    assert r.pending_changes("ZZ") == []

    # Simulated app update: the bundled file is replaced; user files untouched.
    shutil.copy(rules_file(tmp_path, [state(text="New words.", checked="2026-09-01",
                                            required=["product_name", "ingredients",
                                                      "net_quantity"])], name="n.json"),
                builtin)
    r2 = cottage.CottageRules(data, builtin)
    assert (data / cottage.OVERRIDES_NAME).read_text(encoding="utf-8") == overrides
    eff = r2.effective("ZZ")
    assert eff.statements[0].text == "My own words."           # never overwritten
    assert eff.statements[0].default == "New words."
    assert "phone" in eff.required and "net_quantity" not in eff.required
    pend = r2.pending_changes("ZZ")
    assert [p["kind"] for p in pend] == ["statement", "required"]
    assert pend[0]["yours"] == "My own words." and pend[0]["new"] == "New words."

    # keep mine: not asked again, still mine
    r2.keep_mine("ZZ", pend[0])
    assert [p["kind"] for p in r2.pending_changes("ZZ")] == ["required"]
    assert r2.effective("ZZ").statements[0].text == "My own words."
    # use the new one for the required items
    r2.use_new("ZZ", r2.pending_changes("ZZ")[0])
    assert r2.pending_changes("ZZ") == []
    assert "net_quantity" in r2.effective("ZZ").required
    # and after a restart nothing is asked
    assert cottage.CottageRules(data, builtin).pending_changes("ZZ") == []


def test_own_statements_and_custom_preset(tmp_path):
    r = cottage.CottageRules(tmp_path / "data")
    eff = r.effective("custom")
    assert eff.statements == [] and "address" in eff.required
    sid = r.add_own_statement("custom", "Made in my county's licensed home kitchen.", 9)
    eff = r.effective("custom")
    assert eff.statements[0].own and eff.statements[0].text.startswith("Made in")
    assert eff.to_ctx()["statements"][0]["min_pt"] == 9
    r.set_statement("custom", sid, "Changed.")
    assert r.effective("custom").statements[0].text == "Changed."
    r.reset_statement("custom", sid)
    assert r.effective("custom").statements == []


def test_broken_overrides_file_is_kept_aside(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / cottage.OVERRIDES_NAME).write_text("{broken", encoding="utf-8")
    r = cottage.CottageRules(data)
    assert r.effective("NE").statements[0].text == HTK_DISCLAIMER
    assert (data / (cottage.OVERRIDES_NAME + ".broken")).exists()


def test_import_rejects_bad_file_and_writes_nothing(tmp_path):
    data = tmp_path / "data"
    r = cottage.CottageRules(data)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"format": cottage.FORMAT, "version": 1, "states": [{"id": "x"}]}))
    with pytest.raises(cottage.RulesError):
        r.import_file(p)
    assert not (data / cottage.USER_RULES_NAME).exists()


# ---------------------------------------------------------------------------
# the Label check
# ---------------------------------------------------------------------------

def test_label_check_green_and_red():
    eff = {"required": ["product_name", "net_quantity", "ingredients", "allergens",
                        "business_name", "address", "phone", "permit_number", "date_made"],
           "statements": [{"id": "main", "text": "Made at home.", "min_pt": 10}]}
    doc = cottage_doc()
    items = cottage.check_label(doc.fields, PROFILE, eff)
    assert all(i.ok for i in items)
    assert items[-1].key == "statement:main" and "10 pt" in items[-1].label
    # half an address is not an address; no allergens chosen; no net weight
    prof = dict(PROFILE, zip="", phone="")
    items = cottage.check_label(dict(doc.fields, net="", contains=""), prof, eff)
    bad = [i.key for i in cottage.missing(items)]
    assert bad == ["net_quantity", "allergens", "address", "phone"]
    # "none of the nine" counts as answered
    items = cottage.check_label(dict(doc.fields, contains="", no_allergens=True), PROFILE, eff)
    assert not cottage.missing(items)


def test_label_never_prints_half_an_address():
    r = cottage.CottageRules()
    prof = dict(PROFILE, zip="")
    res = render.render(cottage_doc("xl"), ctx_for(r, "NE", prof))
    text = "\n".join(ln.text for ln in res.layout.lines)
    assert "123 Garden Lane" not in text


def test_placeholders_filled_from_my_bakery():
    text, empty = cottage.fill_placeholders("Made at Home by {business_name}", PROFILE)
    assert text == "Made at Home by High Thyme Kitchen" and empty == []
    text, empty = cottage.fill_placeholders("Permit {permit_number}", dict(PROFILE, permit=""))
    assert text == "Permit ____" and empty == ["permit_number"]


# ---------------------------------------------------------------------------
# minimum statement size
# ---------------------------------------------------------------------------

def test_statement_never_below_minimum_and_too_small_label_refused(tmp_path):
    long_text = ("This product was made in a home kitchen that has not been inspected by "
                 "the department of health and may contain common food allergens.")
    builtin = rules_file(tmp_path, [state(text=long_text, min_pt=11,
                                          required=["product_name", "ingredients"])])
    r = cottage.CottageRules(tmp_path / "data", builtin)
    lo = cottage.pt_to_dots(11)
    assert lo == 32                      # 11 pt at 203 dpi, rounded up
    big = render.render(cottage_doc("xl"), ctx_for(r, "ZZ"))
    assert not big.overflow
    st_lines = [ln for ln in big.layout.lines if ln.key == "statement:main"]
    assert st_lines and all(ln.size >= lo for ln in st_lines)
    # the same label with lots of ingredients on a 3 x 2 in label: refused, not shrunk
    doc = cottage_doc("medium", ingredients=", ".join(["enriched wheat flour"] * 12))
    small = render.render(doc, ctx_for(r, "ZZ"))
    assert small.overflow
    assert "11 pt" in small.message and "bigger label" in small.message
    assert small.problem_field == "ingredients"     # something the baker can shorten
    assert all(ln.size >= lo for ln in small.layout.lines if ln.key == "statement:main")
    # nothing required was dropped from the attempt either
    keys = {ln.key for ln in small.layout.lines}
    assert {"product", "ingredients", "statement:main"} <= keys


def test_pt_to_dots():
    assert cottage.pt_to_dots(72) == 203
    assert cottage.pt_to_dots(10) == 29
    assert cottage.pt_to_dots(4.5) == 13


# ---------------------------------------------------------------------------
# net quantity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typed,metric,out", [
    ("8 oz", False, "Net Wt. 8 oz"),
    ("8 oz", True, "Net Wt. 8 oz (227 g)"),
    ("8 ounces", True, "Net Wt. 8 oz (227 g)"),
    ("Net Wt. 12 oz", True, "Net Wt. 12 oz (340 g)"),
    ("1.5 lb", True, "Net Wt. 24 oz (1 lb 8 oz) 680 g"),
    ("1 lb 4 oz", False, "Net Wt. 20 oz (1 lb 4 oz)"),
    ("1 lb", True, "Net Wt. 16 oz (1 lb) 454 g"),
    ("5 lb", True, "Net Wt. 5 lb (2.27 kg)"),
    ("227 g", True, "Net Wt. 8 oz (227 g)"),
    ("16 fl oz", True, "Net 16 fl oz (473 mL)"),
    ("12 cookies", True, "Net 12 cookies"),
    ("1 dozen", False, "Net 1 dozen"),
    ("One loaf", True, "One loaf"),
    ("", True, ""),
])
def test_format_net(typed, metric, out):
    assert cottage.format_net(typed, metric) == out


def test_metric_shown_when_state_requires_it(tmp_path):
    builtin = rules_file(tmp_path, [state(metric_required=True)])
    r = cottage.CottageRules(tmp_path / "data", builtin)
    res = render.render(cottage_doc("xl"), ctx_for(r, "ZZ", dict(PROFILE, metric=False)))
    assert any(ln.text == "Net Wt. 8 oz (227 g)" for ln in res.layout.lines)
    # and when the user asks for it although the state doesn't
    r2 = cottage.CottageRules(tmp_path / "data2")
    res = render.render(cottage_doc("xl"), ctx_for(r2, "NE", dict(PROFILE, metric=True)))
    assert any(ln.text == "Net Wt. 8 oz (227 g)" for ln in res.layout.lines)
    res = render.render(cottage_doc("xl"), ctx_for(r2, "NE", dict(PROFILE, metric=None)))
    assert any(ln.text == "Net Wt. 8 oz" for ln in res.layout.lines)


# ---------------------------------------------------------------------------
# my ingredients / my products
# ---------------------------------------------------------------------------

def test_starter_ingredients_seeded_and_marked_check(tmp_path):
    ing = bakery.Ingredients(tmp_path / "data" / bakery.INGREDIENTS_NAME)
    flour = ing.find("All-purpose flour")
    assert flour and flour["allergens"] == ["Wheat"] and flour["check"]
    assert ing.find("Butter")["sub"] == "cream, salt"
    assert (tmp_path / "data" / bakery.INGREDIENTS_NAME).exists()
    # the user's edits stay; the starter list is never copied in again
    flour["sub"] = "wheat flour"
    flour["check"] = False
    ing.put(flour)
    again = bakery.Ingredients(tmp_path / "data" / bakery.INGREDIENTS_NAME)
    assert again.find("All-purpose flour")["sub"] == "wheat flour"
    assert again.find("All-purpose flour")["check"] is False


def test_ingredients_build_line_and_contains(tmp_path):
    ing = bakery.Ingredients(tmp_path / bakery.INGREDIENTS_NAME)
    picked = [ing.find(n) for n in ("Butter", "All-purpose flour", "Sugar", "Eggs",
                                    "Semi-sweet chocolate chips", "Walnuts")]
    line = bakery.build_ingredients(picked)
    assert line.startswith("Butter (cream, salt), All-purpose flour (wheat flour, niacin, "
                           "reduced iron, thiamine mononitrate, riboflavin, folic acid), Sugar, "
                           "Eggs, Semi-sweet chocolate chips (")
    assert bakery.allergens_for(picked) == ["Milk", "Eggs", "Wheat", "Soy",
                                            "Tree nuts (walnuts)"]


def test_product_library_round_trip_and_backup(tmp_path):
    data = tmp_path / "data"
    prods = bakery.Products(data / bakery.PRODUCTS_NAME)
    doc = cottage_doc(best_by="2026-11-27", made_on="2026-11-20")
    entry = bakery.product_from_fields(doc.fields)
    assert entry["best_by_days"] == 7
    saved = prods.put(entry)
    again = bakery.Products(data / bakery.PRODUCTS_NAME)
    assert again.get(saved["id"]) == saved
    # choosing a product fills the label (dates from today)
    import datetime as dt
    fields = bakery.apply_product(model.default_fields("cottage"), saved, dt.date(2027, 1, 1))
    assert fields["product"] == "Lemon Shortbread" and fields["net"] == "8 oz"
    assert fields["contains"] == "Milk, Wheat" and fields["best_by"] == "2027-01-08"
    # export -> import into a fresh library
    backup = again.export_file(tmp_path / "backup.json")
    other = bakery.Products(tmp_path / "other" / bakery.PRODUCTS_NAME)
    added, updated = other.import_file(backup)
    assert added == ["Lemon Shortbread"] and updated == []
    added, updated = other.import_file(backup)
    assert added == [] and updated == ["Lemon Shortbread"] and len(other.items) == 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": bakery.INGREDIENTS_FORMAT, "version": 1,
                               "ingredients": []}))
    with pytest.raises(bakery.LibraryError):
        other.import_file(bad)


# ---------------------------------------------------------------------------
# my kitchen details
# ---------------------------------------------------------------------------

def test_profile_seeded_from_package_kitchen_and_survives(tmp_path):
    data = tmp_path / "data"
    kitchen = {"business": "Rosie's Bakes", "address": "12 Oak St\nOmaha, NE 68102",
               "cross_contact": model.DEFAULT_CROSS_CONTACT}
    p = bakery.Profile(data / bakery.PROFILE_NAME, kitchen)
    assert p["business"] == "Rosie's Bakes" and p["street"] == "12 Oak St"
    assert (p["city"], p["region"], p["zip"]) == ("Omaha", "NE", "68102")
    assert p["cross_contact"] == ""          # the example notice isn't copied as a fact
    p["phone"] = "555-0100"
    p["state"] = "NE"
    p.save()
    q = bakery.Profile(data / bakery.PROFILE_NAME, {"business": "Something else"})
    assert q["business"] == "Rosie's Bakes" and q["phone"] == "555-0100"
    assert p.address_lines() == ["12 Oak St", "Omaha, NE 68102"]


def test_profile_migration_and_newer_keys_kept(tmp_path):
    path = tmp_path / bakery.PROFILE_NAME
    path.write_text(json.dumps({"format": bakery.PROFILE_FORMAT, "version": 0,
                                "business": "Old", "address": "1 Main St\nLincoln, NE 68508",
                                "metric": "yes", "show_phone": 1, "future": {"x": 1}}))
    p = bakery.Profile(path)
    assert p["street"] == "1 Main St" and p["zip"] == "68508"
    assert p["metric"] is None and p["show_phone"] is False      # bad types -> defaults
    p.save()
    saved = json.loads(path.read_text())
    assert saved["future"] == {"x": 1} and saved["version"] == bakery.PROFILE_VERSION
    # a file written by a newer version is read but never written back
    path.write_text(json.dumps({"format": bakery.PROFILE_FORMAT, "version": 99,
                                "business": "Newer"}))
    n = bakery.Profile(path)
    assert n["business"] == "Newer"
    n["business"] = "Changed"
    n.save()
    assert json.loads(path.read_text())["business"] == "Newer"


def test_broken_profile_is_set_aside_not_overwritten(tmp_path):
    path = tmp_path / bakery.PROFILE_NAME
    path.write_text("{oops")
    p = bakery.Profile(path)
    assert p["business"] == ""
    assert (tmp_path / (bakery.PROFILE_NAME + ".broken")).read_text() == "{oops"


def test_kitchen_settings_never_reset(tmp_path):
    s = settings.Settings(tmp_path / "s.json")
    s["kitchen"]["business"] = "Rosie's Bakes"
    s.save()
    assert settings.Settings(tmp_path / "s.json")["kitchen"]["business"] == "Rosie's Bakes"


# ---------------------------------------------------------------------------
# label files
# ---------------------------------------------------------------------------

V1_FILES = {
    "simple": {"food": "Chili", "made_on": "2026-11-01", "use_by": "2026-11-06",
               "contains": "Milk", "note": "Keep frozen", "made_by": "Jo", "kitchen": True},
    "package": {"product": "Shortbread", "net": "8 oz", "ingredients": "Butter, flour",
                "contains": "Milk, Wheat", "cross_contact": "x", "lot": "261101",
                "best_by": "2026-11-15", "business": "B", "address": "A",
                "disclaimer": "D", "qr": ""},
    "sticker": {"lot": "261101", "made": "2026-11-01", "best_by": "2026-11-08", "count": "3"},
    "free": {"text": "Hello"},
}


@pytest.mark.parametrize("template", list(V1_FILES))
def test_version_1_0_label_files_still_open(tmp_path, template):
    """Files saved by Food Labeler 1.0.0 open unchanged in this version."""
    raw = {"app": "easy-labels", "version": 1, "template": template, "stock": "large",
           "fields": V1_FILES[template], "copies": 3}
    p = tmp_path / "old.label"
    p.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    doc = model.load(p)
    assert doc.template == template and doc.copies == 3 and doc.fields == V1_FILES[template]
    assert doc.to_dict() == raw              # saving again writes the same thing
    assert not render.render(doc, {}).overflow


def test_cottage_label_file_round_trip(tmp_path):
    doc = cottage_doc(no_allergens=False, show_made=False)
    p = model.save(doc, tmp_path / "shortbread")
    back = model.load(p)
    assert back.to_dict() == doc.to_dict()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["template"] == "cottage"


def test_switch_package_to_cottage_keeps_product():
    doc = model.LabelDoc("package", "large", model.default_fields("package"))
    doc.fields.update(product="Pie", net="2 lb", ingredients="Apples", contains="Wheat")
    doc.set_template("cottage")
    assert (doc.fields["product"], doc.fields["net"], doc.fields["ingredients"],
            doc.fields["contains"]) == ("Pie", "2 lb", "Apples", "Wheat")


def test_cottage_renders_on_every_allowed_size_without_context():
    for sid in templates.ALLOWED_STOCKS["cottage"]:
        res = render.render(cottage_doc(sid), {})
        st = stocks.get(sid)
        assert res.image.size == (st.w, st.h) and not res.overflow


# ---------------------------------------------------------------------------
# who checked the rules
# ---------------------------------------------------------------------------

def test_only_bundled_rules_say_checked_against_the_official_source(tmp_path):
    from food_labeler import bakery_dialogs
    builtin = rules_file(tmp_path, [state(text="Bundled words.", checked="2026-01-01")],
                         name="bundled.json")
    data = tmp_path / "data"
    r = cottage.CottageRules(data, builtin)
    text, warn = cottage.check_status(r.base("ZZ"))
    assert text == "Checked against the official source on 2026-01-01" and not warn
    assert dict(bakery_dialogs.state_choices(r))["ZZ"] == "Testland"
    # an imported file claims to be verified and checked
    r.import_file(rules_file(tmp_path, [state(text="Updated words.", checked="2026-06-01",
                                              verified=True)]))
    rule = r.effective("ZZ").rule
    assert rule.verified and rule.from_update
    text, warn = cottage.check_status(rule)
    assert text == ("From an update file you imported (checked 2026-06-01 by whoever "
                    "made it).") and warn
    assert "official" not in text
    about = "\n".join(cottage.about_source_lines(rule))
    assert "official" not in about and "From an update file you imported" in about
    assert "Source named in the update file: https://example.gov/cottage" in about
    assert "imported" in dict(bakery_dialogs.state_choices(r))["ZZ"]
    # the same after a restart (from_update is never read from the file itself)
    r = cottage.CottageRules(data, builtin)
    assert r.base("ZZ").from_update
    assert "from_update" not in json.loads((data / cottage.USER_RULES_NAME).read_text())[
        "states"][0]
    # the user's own wording on top doesn't make it official either
    r.set_statement("ZZ", "main", "My words.")
    assert cottage.check_status(r.effective("ZZ").rule)[0].startswith("From an update file")
    # once Food Labeler ships newer rules, those are used and are official again
    newer = rules_file(tmp_path, [state(text="Autumn words.", checked="2026-10-01")],
                       name="b2.json")
    r2 = cottage.CottageRules(data, newer)
    assert cottage.check_status(r2.base("ZZ"))[0].startswith("Checked against the official")


def test_update_file_cannot_claim_from_bundled(tmp_path):
    # "from_update" isn't a key a rules file may contain
    with pytest.raises(cottage.RulesError, match="doesn't understand"):
        cottage.parse_rules_text(json.dumps({"format": cottage.FORMAT, "version": 1,
                                             "updated": "2026-11-20",
                                             "states": [state(from_update=False)]}))


def test_unverified_and_undated_update_wording(tmp_path):
    builtin = rules_file(tmp_path, [state(sid="AA", name="Aland")], name="bundled.json")
    r = cottage.CottageRules(tmp_path / "data", builtin)
    r.import_file(rules_file(tmp_path, [state(verified=False, checked="")]))
    text, warn = cottage.check_status(r.base("ZZ"))
    assert text == ("From an update file you imported (not dated by whoever made it). "
                    "Unverified — check with your state.") and warn
    bundled_unverified = cottage.StateRule(id="QQ", name="Q", verified=False)
    assert cottage.check_status(bundled_unverified) == ("Unverified — check with your state.",
                                                        True)
    assert cottage.check_status(cottage.custom_rule()) == ("", False)
