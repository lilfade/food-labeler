from PIL import Image, ImageDraw

from food_labeler import stocks, tspl

EXPECTED_SIZE = {
    "small": "SIZE 32 mm,25 mm", "medium": "SIZE 76.2 mm,50.8 mm",
    "large": "SIZE 101.6 mm,50.8 mm", "round": "SIZE 50.8 mm,50.7 mm",
    "xl": "SIZE 101.6 mm,152.4 mm",
}


def test_header_per_stock():
    for sid, size in EXPECTED_SIZE.items():
        st = stocks.get(sid)
        h = tspl.header(st).decode()
        lines = h.split("\r\n")
        assert lines[0] == size
        assert lines[1] == f"GAP {'2' if sid == 'small' else '3'} mm,0 mm"
        assert lines[2:4] == ["DIRECTION 1,0", "REFERENCE 0,0"]
        assert lines[4] == f"DENSITY {9 if sid == 'small' else 8}"
        assert lines[5] == f"SPEED {3 if sid in ('small', 'round') else 4}"
        assert lines[6] == "CLS"
        assert h.endswith("\r\n")


def test_stock_dots():
    assert [(stocks.get(s).w, stocks.get(s).h) for s in stocks.ORDER] == [
        (256, 200), (609, 400), (812, 400), (406, 405), (812, 1218)]
    assert stocks.get("round").circle_dia == 382
    assert stocks.get("small").margin == 12 and stocks.get("large").margin == 24


def test_overrides_and_clamp():
    st = stocks.get("large")
    h = tspl.header(st, density=20, speed=2, gap_mm=2.5).decode()
    assert "DENSITY 15\r\n" in h and "SPEED 2\r\n" in h and "GAP 2.5 mm,0 mm" in h
    job = tspl.build_job(Image.new("1", (812, 406), 1), st, copies=999)
    assert job.endswith(b"PRINT 200,1\r\n")
    job = tspl.build_job(Image.new("1", (812, 406), 1), st, copies=0)
    assert job.endswith(b"PRINT 1,1\r\n")


def test_bitmap_polarity_and_padding():
    # 10 px wide: 2 bytes per row, 6 pad bits
    img = Image.new("1", (10, 2), 1)
    img.putpixel((0, 0), 0)          # black top-left
    img.putpixel((9, 1), 0)          # black at right edge, row 2
    rb, h, data = tspl.pack_bitmap(img)
    assert (rb, h) == (2, 2)
    # row 0: pixel0 black -> bit 0, rest white (1), pad bits 1
    assert data[0] == 0b01111111 and data[1] == 0b11111111
    # row 1: pixel 9 is bit 6 of byte 1 (MSB first) -> 0; pad bits (low 6) = 1
    assert data[2] == 0xFF and data[3] == 0b10111111


def test_bitmap_inverted():
    img = Image.new("1", (10, 1), 1)
    img.putpixel((0, 0), 0)
    _, _, data = tspl.pack_bitmap(img, invert=True)
    assert data[0] == 0b10000000 and data[1] == 0b00000000   # pad bits 0 = white


def test_full_job_layout():
    st = stocks.get("large")
    img = Image.new("1", (st.w, st.h), 1)
    ImageDraw.Draw(img).rectangle((0, 0, 7, 0), fill=0)
    job = tspl.build_job(img, st, 3)
    head = tspl.header(st)
    assert job.startswith(head)
    rest = job[len(head):]
    prefix = b"BITMAP 0,0,102,400,0,"
    assert rest.startswith(prefix)
    data = rest[len(prefix):len(prefix) + 102 * 400]
    assert data[0] == 0x00 and data[1] == 0xFF
    assert data[101] == 0xFF          # last byte of row: 4 pad bits set to 1
    assert rest[len(prefix) + 102 * 400:] == b"\r\nPRINT 3,1\r\n"


def test_calibrate():
    job = tspl.calibrate_job(stocks.get("small")).decode()
    assert job == "SIZE 32 mm,25 mm\r\nGAP 2 mm,0 mm\r\nGAPDETECT\r\n"
