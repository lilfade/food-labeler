import datetime as dt

from food_labeler import dates

D = dt.date(2026, 11, 20)


def test_quick_buttons():
    got = {t: dates.quick(D, k, n) for t, k, n in dates.QUICK}
    assert got == {"+3 days": dt.date(2026, 11, 23), "+5 days": dt.date(2026, 11, 25),
                   "+1 week": dt.date(2026, 11, 27), "+2 weeks": dt.date(2026, 12, 4),
                   "+1 month": dt.date(2026, 12, 20)}


def test_month_end():
    assert dates.add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert dates.add_months(dt.date(2026, 12, 15), 1) == dt.date(2027, 1, 15)


def test_formats():
    assert dates.fmt(D) == "Nov 20, 2026"
    assert dates.fmt(D, "dmy") == "20 Nov 2026"
    assert dates.fmt(D, "numeric") == "11/20/2026"
    assert dates.fmt(D, "mdy_short") == "11/20/26"
    assert dates.fmt_long(D) == "Friday, Nov 20, 2026"
    assert dates.parse("bad") is None and dates.parse("2026-11-20") == D
