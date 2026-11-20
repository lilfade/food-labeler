# Contributing to Food Labeler

Thank you for helping! Food Labeler is used by people who are not computer
experts, so the guiding rules are:

- **Plain words** in everything the user sees. Printer jargon lives only in
  *Settings → Advanced*.
- **The preview is the printout.** Everything that prints goes through
  `render.render()`; never draw printer-only content elsewhere.
- **Never print by surprise.** Only a button press sends anything to a printer
  (test labels, calibration and "Which one is it?" included).
- **Never lose work.** Writes are atomic; the session is autosaved.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit.

## Development setup

You need Python 3.11 or newer (CI uses 3.12) with Tk (`python3-tk` on
Debian/Ubuntu; included in the python.org installers).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip ...
.venv/bin/python -m food_labeler                  # run the app
```

Optional, only for rebuilding the icons from `assets/seal.svg`
(needs the Cairo library):

```sh
.venv/bin/pip install -r requirements-icons.txt
.venv/bin/python tools/make_icons.py
```

## Tests

```sh
.venv/bin/python -m pyflakes food_labeler tests tools food_labeler_main.py
.venv/bin/python -m pytest -q
```

The tests never open a window and never print: `tests/conftest.py` points
the data and labels folders at a temporary directory, sets
`FOOD_LABELER_DRY_RUN` so print jobs become files, and makes any real network
connection fail the test. Printer discovery is tested against a fake Linux
`/sys` tree and fake `win32print`/`lpstat` objects.

The window layout tests in `tests/test_ui_layout.py` are opt-in because they
need a display. Only run them on a throwaway X server, never on a desktop
someone is using:

```sh
Xvfb :99 &  FOOD_LABELER_UI_TESTS=1 DISPLAY=:99 .venv/bin/python -m pytest tests/test_ui_layout.py
```

To try printing without a printer:

```sh
FOOD_LABELER_DRY_RUN=/tmp/jobs .venv/bin/python -m food_labeler
```

`tools/render_samples.py` redraws `docs/samples/*.png` (the exact printer
bitmaps for every template and size) — run it after changing a template and
look at the result.

## Building the programs

| | command | result |
|---|---|---|
| Windows | double-click `build_windows.bat` (Python 3.11+ from python.org) | `dist\FoodLabeler.exe` |
| Linux | `./build_linux.sh` | `dist/food-labeler` |

Both run the tests, build with `food_labeler.spec` and run `--selftest` on
the result. `./packaging/install_linux.sh` installs the Linux build for the
current user with a menu entry.

## Releasing

1. Update `__version__` in `food_labeler/__init__.py` and add a section to
   `CHANGELOG.md` (`## 1.2.3 — date`).
2. Commit, then tag and push: `git tag v1.2.3 && git push origin v1.2.3`.
3. The *Release* workflow checks the tag matches `__version__`, builds and
   self-tests `FoodLabeler.exe` (Windows) and `food-labeler` (Linux), and
   publishes a GitHub Release with both files and `SHA256SUMS.txt`, using the
   matching CHANGELOG section as release notes.

## Adding a printer definition

Printer models are data, not code: `food_labeler/known_printers.json`. The
format and matching rules are in
[docs/printer-definitions.md](docs/printer-definitions.md).

1. Get the facts: ask the user for the report (*My printer isn't in the list →
   Send this to High Thyme Kitchen*). It lists the USB vendor:product id, the
   IEEE 1284 device id (Linux) and the Windows printer/driver names.
2. Add an entry with a new lowercase `id`. Prefer `ieee1284` and `usb`
   matches; use `windows` name patterns for Windows. If several brands sell
   the same hardware, list them all in `brands` — never claim one brand for a
   shared USB id.
3. Set `language` (`tspl` or `zpl`) and, if needed, `density`/`speed` per
   label size and the `stocks` it takes.
4. Validate: `.venv/bin/python -c "from food_labeler import known; print(known.parse_file_text(open('food_labeler/known_printers.json', encoding='utf-8').read()))"`
5. Add a test in `tests/test_known.py` or `tests/test_printers.py` that the
   model is matched (see the existing LP610BT and ZP450 tests).

For a user who can't wait for a release, put just the new entries in their
own file (same format) and send it to them; they add it with *Settings → Add
printer update file…*.

Only 203 dpi printers are supported for now: every layout is computed in
203 dpi dots.

## Code style

- Python 3.11+, `from __future__ import annotations`, standard library plus
  Pillow and segno (pywin32 on Windows). New dependencies need a good reason:
  they all end up inside the one-file program.
- Lines up to about 100 characters; pyflakes must be clean.
- Every module has a docstring saying what it is for; public functions and
  classes have one too. Comment the *why* of anything tricky.
- Messages to the user are kind, short and say what to do next. Technical
  details go to the log (`food-labeler.log`), never into a dialog.
