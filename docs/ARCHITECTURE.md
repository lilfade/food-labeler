# Architecture

Food Labeler is a single-process Python program: a Tk window, Pillow for
drawing, and no server or network service. It is packaged with PyInstaller as
one file (`FoodLabeler.exe` on Windows, `food-labeler` on Linux).

## Module map

| module | role |
|--------|------|
| `food_labeler/__init__.py` | app name, brand and `__version__` (the only place the version is written) |
| `food_labeler/__main__.py` | command line: `--selftest`, `--version`, or start the window (optionally opening a `.label` file) |
| `food_labeler_main.py` | tiny entry script used by PyInstaller and the Linux menu entry |
| `model.py` | `LabelDoc` (template, size, fields, copies), `.label` JSON load/save, atomic writes |
| `dates.py` | date parsing, quick "use by" offsets, date formats |
| `stocks.py` | label sizes (`Stock`) in dots and mm, per-size printer defaults |
| `templates.py` | per-template text blocks and the auto-fit layout engine |
| `render.py` | draws a layout as the exact 1-bit printer bitmap; on-screen preview; PNG export |
| `tspl.py` | TSPL job builder (LP610BT and clones) |
| `zpl.py` | ZPL job builder (Zebra), plus a decoder used by tests and `--selftest` |
| `printers.py` | printer discovery (Linux sysfs + CUPS, Windows spooler, network), sending jobs, status |
| `known.py` | known printer models: bundled `known_printers.json` + the user's update file |
| `usbscan.py` | lists every USB device for "My printer isn't in the list" |
| `report.py` | the plain-text printer report a user can send for help (no label content) |
| `settings.py` | settings file, data/labels folders, log file, autosave |
| `app.py` | main window: form, preview, printer menu, PRINT |
| `dialogs.py` | all other windows: pickers, save/open, settings, printers, USB devices, report |
| `widgets.py` | big-button Tk building blocks: `Modal`, `button`, `ask`/`tell`, calendar, toggles |

Nothing outside `app.py`, `dialogs.py` and `widgets.py` imports Tk, so
everything else is tested headless.

## Data flow

```
 form (app.py)                    the user types; each change edits App.doc
   │
   ▼
 LabelDoc (model.py)              template + stock id + fields (dates as ISO strings)
   │
   ▼
 templates.build_blocks()         fields → text Blocks with preferred/minimum sizes
 templates.layout() / fit()       blocks → placed Lines that fit the Region
   │                              (rectangle inside margins, or circle on round labels;
   │                               a QR code is an exclusion the text flows around)
   ▼
 render.draw_layout()             Lines (+ QR) → mode "1" image, stock.w × stock.h dots
   │                 ╲
   │                  ╲──────────▶ render.preview()  scaled copy for the screen
   ▼
 printers.build_job()             picks the language for the chosen printer
   ├── tspl.build_job()           SIZE/GAP/DENSITY/SPEED/CLS + BITMAP + PRINT
   └── zpl.build_job()            ^XA … ^GFA (hex bitmap) … ^PQ … ^XZ
   │
   ▼
 printers.send()                  on a worker thread; one of
   ├── windows_raw                RAW document through the Windows spooler
   ├── windows_driver             picture drawn through the Windows driver (fallback)
   ├── cups                       lp -o raw
   ├── device                     write to /dev/usb/lpN (or a udev symlink)
   └── network                    raw TCP to host:9100
```

`FOOD_LABELER_DRY_RUN=<folder>` short-circuits `printers.send()`: jobs are
written to files in that folder instead. The tests always set it.

### Layout auto-shrink

Each template gives every field a preferred size (a fraction of the label's
size, so one template scales from 32 mm to 4 × 6 in) and a minimum size.
`templates.fit()`:

1. shrinks headline blocks alone until their longest word fits a line;
2. scales all blocks together in 6 % steps, each clamped at its minimum;
3. binary-searches between the last failing and first fitting step;
4. if it still doesn't fit at minimum sizes, returns an *overflow* layout
   naming the tallest block. The UI highlights that field and refuses to
   print; nothing is ever silently cut off.

On round labels each line's width depends on its height in the circle, which
depends on vertical centring, which depends on the wrapping — `_try()`
iterates until the top edge stops moving.

### Bitmap polarity

Pillow's mode "1" packs 8 pixels per byte, MSB first, 1 = white, with each
row padded to a whole byte (pad bits are 0).

- **TSPL** `BITMAP` uses 1 = white too, so the bytes go out as they are; only
  the pad bits are forced to 1 (otherwise a black stripe prints down the
  right edge). Some clones use the opposite polarity: Advanced → *Invert
  colours* XORs everything and then forces the pad bits to 0.
- **ZPL** `^GFA` uses 1 = black, so every byte is XORed with 0xFF and the pad
  bits (now 1) are masked back to 0.

### Printer identity

Settings are kept per printer id, which must survive reboots and re-plugs.
LP610BT clones share USB vid:pid `0483:2025` *and* the serial number, and
`/dev/usb/lpN` numbers change between boots, so on Linux the id is the
physical USB port path (`usb:1-1.4`). On Windows each unit is its own spooler
printer on its own port, so the id is `win:<printer name>|<port>`. A CUPS
queue that points at a detected device is merged into that device's entry.

### Background work

Tk may only be used from the main thread. Printer discovery (every 15 s and
on request), USB scans and sending jobs run on daemon threads and hand their
results back through a `queue.Queue` that the window polls with `after()`.

### Autosave and session restore

Every 4 s, if anything changed, the window writes `autosave.json`: the
document, the file it came from and whether it had unsaved changes. It is
also written on errors and on close. At start-up the session is restored
exactly, including the "not saved yet" state, so closing the window without
saving or a power cut never loses typing. All writes are atomic (temp file +
fsync + rename).

## File formats

| file | where | format |
|------|-------|--------|
| `*.label` | wherever the user saves (default `Documents/My Food Labels`) | JSON: `{"app": "easy-labels", "version": 1, "template", "stock", "fields", "copies"}` |
| `settings.json` | data folder | JSON, merged over built-in defaults key by key (unknown keys and wrong types are ignored) |
| `autosave.json` | data folder | `{"doc": <label>, "path": "...", "dirty": bool}` |
| `known_printers.json` | bundled in the package, and optionally in the data folder | see [printer-definitions.md](printer-definitions.md) |
| `app_config.json` | bundled | support e-mail address and name |
| `food-labeler.log` | data folder | text log, rotated at 512 kB (3 files) |

The `.label` format id `easy-labels` is the project's original name and must
not change, or existing files stop opening.

## Settings locations

| | Windows | Linux | macOS (from source) |
|---|---|---|---|
| data folder | `%APPDATA%\FoodLabeler` | `$XDG_DATA_HOME/food-labeler` (default `~/.local/share/food-labeler`) | `~/Library/Application Support/FoodLabeler` |
| saved labels | `Documents\My Food Labels` | `~/Documents/My Food Labels` (`xdg-user-dir DOCUMENTS`) | `~/Documents/My Food Labels` |

Environment overrides: `FOOD_LABELER_DATA`, `FOOD_LABELER_LABELS`,
`FOOD_LABELER_DRY_RUN`.

## Packaging

`food_labeler.spec` builds a one-file, windowed program and bundles the
fonts, icons, `known_printers.json` and `app_config.json`. On Windows it also
embeds a version resource (file/product version from `__version__`, product
"Food Labeler", company "High Thyme Kitchen"). `--selftest` is run on every
build to prove the bundle is complete.
