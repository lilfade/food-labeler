# Contributing to Food Labeler

Thank you for helping! Food Labeler is used by people who are not computer
experts, so the guiding rules are:

- **Plain words** in everything the user sees. Printer jargon lives only in
  *Settings → Advanced*.
- **The preview is the printout.** Everything that prints goes through
  `render.render()`; never draw printer-only content elsewhere.
- **Never print by surprise.** Only a button press sends anything to a printer
  (test labels, calibration and "Which one is it?" included). Anything that
  uses up labels (setting up a roll, the darkness test) asks first and says
  how many. `tests/test_calibrate.py` checks no automatic path can send.
- **Never lose work.** Writes are atomic; the session is autosaved.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit.

User help lives in [README.md](README.md) and three guides:
[Using Food Labeler](docs/guide.md), [Your printer](docs/printer.md) and
[Something not right?](docs/troubleshooting.md). Changes are listed in
[CHANGELOG.md](CHANGELOG.md).

## For helpers

- **Linux:** download `food-labeler`, make it executable
  (`chmod +x food-labeler`) and run it, or build it yourself with
  `./build_linux.sh` and install a menu entry with
  `./packaging/install_linux.sh`. Printing straight to a USB printer needs the
  user in the `lp` group (`sudo usermod -aG lp $USER`, then log out and in);
  a raw CUPS queue also works.
- **Where things are kept:** saved labels in `Documents\My Food Labels`
  (Linux: `~/Documents/My Food Labels`); settings, autosave, log, printer
  updates, *My bakery*, *My ingredients*, *My products*, fonts you added and
  your own cottage wording in `%APPDATA%\FoodLabeler` (Linux:
  `~/.local/share/food-labeler`). Updates to Food Labeler never change them.
- **Checking a download:** `SHA256SUMS.txt` on the
  [Releases page](https://github.com/lilfade/food-labeler/releases/latest)
  has the checksum of each file.

## Developer docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the pieces fit.
- [docs/printer-definitions.md](docs/printer-definitions.md): adding new
  printer models with a printer update file.
- [docs/cottage-rules.md](docs/cottage-rules.md): the state cottage food
  rules and how to update them.
- [docs/fonts.md](docs/fonts.md): bundled fonts, their sources and fonts
  users add.
- [docs/samples](docs/samples): sample printouts of every label kind and size.

## Development setup

You need Python 3.11 or newer (CI uses 3.12) with Tk (`python3-tk` on
Debian/Ubuntu; included in the python.org installers).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip ...
.venv/bin/python -m food_labeler                  # run the app
```

To get exactly what CI and the release builds use (Python 3.12):

```sh
.venv/bin/pip install --require-hashes -r requirements-lock.txt
.venv/bin/pip install --require-hashes -r requirements-dev-lock.txt
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

Screenshots in `docs/` come from `python tools/screenshot.py docs`. It
opens the real window with example data for about half a minute, so only run
it on a desktop nobody is using at that moment.

`tools/render_samples.py` redraws `docs/samples/*.png` (the exact printer
bitmaps for every template and size, the fonts sheet, `dpi-203-vs-300.png`,
`picture-*.png` and `qr-*.png`) — run it after changing a template and look
at the result.

`tests/test_qr.py` decodes the printed QR codes with `zxing-cpp` (in
`requirements-dev.txt`); without it those checks are skipped and the module
geometry is still compared with segno's matrix exactly. Picture tests use
pictures drawn in the test, so no photos are kept in the repository.

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

## Updating the cottage food state rules

State rules are data, not code: `food_labeler/cottage_rules.json`. The
format, the layering with the user's own edits and the checklist are in
[docs/cottage-rules.md](docs/cottage-rules.md). In short:

1. Check every change against the state's **official** source (department
   of agriculture or health, statute, administrative code) and copy the
   wording exactly. Never guess: if you can't confirm a state, set
   `"verified": false` and start the notes with "Unverified — check with
   your state."
2. Update `source_url` and `checked_on` (the day you checked).
3. Run the tests; `tests/test_cottage.py` validates the file and checks the
   Nebraska preset still matches High Thyme Kitchen's own label wording.
4. Run `tools/render_samples.py` and look at `docs/samples/cottage-*.png`.
5. Update the table at the end of `docs/cottage-rules.md` and the CHANGELOG.

Never change what is in a user's data folder from code that runs on update:
`cottage_overrides.json`, `my_bakery.json`, `my_ingredients.json` and
`my_products.json` belong to the user. New fields need a default and, if
the layout changes, a migration in `bakery.Profile.migrate` (and a test).

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
   label size and the `stocks` it takes. Add `calibrate_by_hand`: how to set
   up a new roll with the printer's own button, in plain words, checked
   against the printer's own guide (it is shown in *Set up a new roll*).
4. Validate: `.venv/bin/python -c "from food_labeler import known; print(known.parse_file_text(open('food_labeler/known_printers.json', encoding='utf-8').read()))"`
5. Add a test in `tests/test_known.py` or `tests/test_printers.py` that the
   model is matched (see the existing LP610BT and ZP450 tests).

For a user who can't wait for a release, put just the new entries in their
own file (same format) and send it to them; they add it with *Settings → Add
printer update file…*.

Printers are 203 or 300 dpi (`"dpi"`, default 203); add `"max_width_dots"`
when you know the print width. Layout numbers in `templates.py`/`render.py`
are written in 203 dpi dots and must go through `stock.d()` (or
`stocks.dots()`), so they scale for 300 dpi and stay byte-identical at 203.
`tests/test_dpi.py` compares 130 labels at 203 dpi with hashes from before
300 dpi support (`tests/data/render_baseline_203.json`); if a change is
*meant* to alter 203 dpi output, regenerate it on purpose with
`python tests/render_cases.py --write` and say so in the commit.

## Adding a bundled font

Bundled fonts must be licensed under the SIL Open Font License or Apache 2.0
and keep the program small (prefer static Regular + Bold files; use the
variable file only when Google's repository has nothing else).

1. Download the files, unmodified, from
   [github.com/google/fonts](https://github.com/google/fonts) at a fixed
   commit: `raw.githubusercontent.com/google/fonts/<commit>/ofl/<folder>/…`.
2. Put them with the license file in `food_labeler/fonts/<folder>/`
   (`OFL.txt` — the spec refuses to build a family folder without it).
3. Add a `Face` to `BUNDLED` in `food_labeler/lettering.py`: `readable=True`
   only for a plain, easy-to-read sans (it may then be used for everything
   else, including required wording); `variable=True` for a variable font;
   `min_scale` from its x-height compared with DejaVu Sans (55 at size 100)
   and more for script/handwriting fonts.
4. Add it to the table in `docs/fonts.md` (license, size, exact source path
   and commit), to the license paragraph in `docs/guide.md` and to the CHANGELOG.
5. Run the tests (`tests/test_fonts.py` checks every bundled font loads,
   draws and has a real bold) and `python tools/render_samples.py --fonts`,
   then look at `docs/samples/fonts-contact-sheet.png`.

## Dependencies and lock files

`requirements.txt` (what the program needs) and `requirements-dev.txt`
(tests and building) say which packages are wanted. CI and the *Release*
workflow never install from them directly: they install the lock files
with `pip install --require-hashes`, so every package is an exact version
and every downloaded file must match its SHA-256 hash.

| file | made from | holds |
|------|-----------|-------|
| `requirements-lock.txt` | `requirements.txt` | Pillow, segno, pywin32 (Windows only) |
| `requirements-dev-lock.txt` | `requirements-dev.txt` | the above plus pytest, PyInstaller, pyflakes, zxing-cpp and what they need |

Both are made for Python 3.12 on Windows *and* Linux in one go (packages
that only one system needs carry a `; sys_platform == …` marker), and list
the hash of every file PyPI has for each version, so the same file works on
`win_amd64` and `manylinux` x86-64. `pip-compile` from pip-tools can't do
this: it only resolves for the computer it runs on and would leave out the
Windows-only packages. The lock files are made with
[uv](https://docs.astral.sh/uv/) instead (`pip install uv`):

```sh
uv pip compile --universal --python-version 3.12 --generate-hashes \
    requirements.txt -o requirements-lock.txt
uv pip compile --universal --python-version 3.12 --generate-hashes \
    -c requirements-lock.txt requirements-dev.txt -o requirements-dev-lock.txt
```

Run both after changing a requirements file, and to take newer versions add
`--upgrade` (or `--upgrade-package pillow`). The second command uses the
first lock as a constraint, so both files pin the same versions
(`tests/test_locks.py` checks this). Then run the tests, look at
`tests/test_dpi.py` especially after a Pillow update (203 dpi output must
stay byte-identical), and commit the requirements and lock files together.

Dependabot (`.github/dependabot.yml`) opens weekly pull requests for newer
packages and for the GitHub Actions. The actions are pinned to full commit
SHAs with the version tag as a comment (`actions/checkout@<sha> # v4.4.0`);
when pinning one by hand, look the tag up at
`https://api.github.com/repos/actions/<name>/git/refs/tags/<tag>` (for an
annotated tag, follow its `object.url` to the commit).

`requirements-icons.txt` (cairosvg, only for `tools/make_icons.py`) is not
locked and not installed by CI.

## Code style

- Python 3.11+, `from __future__ import annotations`, standard library plus
  Pillow and segno (pywin32 on Windows). Network code (only `fontget.py`)
  uses `urllib` from the standard library, never runs on the Tk thread, and
  is tested with fake HTTP answers. New dependencies need a good reason:
  they all end up inside the one-file program.
- Lines up to about 100 characters; pyflakes must be clean.
- Every module has a docstring saying what it is for; public functions and
  classes have one too. Comment the *why* of anything tricky.
- Messages to the user are kind, short and say what to do next. Technical
  details go to the log (`food-labeler.log`), never into a dialog.
