# Architecture

Food Labeler is a single-process Python program: a Tk window, Pillow for
drawing, and no server or network service. The only internet use is the
optional *Get more fonts…* (`fontget.py`), which the user starts by hand; a
network printer the person added is only connected to when printing (or
*Test the connection*). It is packaged with PyInstaller as
one file (`FoodLabeler.exe` on Windows, `food-labeler` on Linux).

## Module map

| module | role |
|--------|------|
| `food_labeler/__init__.py` | app name, brand and `__version__` (the only place the version is written) |
| `food_labeler/__main__.py` | command line: `--selftest`, `--version`, or start the window (optionally opening a `.label` file) |
| `food_labeler_main.py` | tiny entry script used by PyInstaller and the Linux menu entry |
| `model.py` | `LabelDoc` (template, size, fields, copies), `.label` JSON load/save, atomic writes |
| `dates.py` | date parsing, quick "use by" offsets, date formats |
| `stocks.py` | label sizes (`Stock`) in mm and in dots at 203 or 300 dpi, `dots()` scaling, per-size printer defaults, which way round (`natural`, `turned`, `rotated`) |
| `templates.py` | per-template text blocks and the auto-fit layout engine |
| `lettering.py` | font registry (bundled + user fonts), font loading (variable fonts too), which block gets which font, per-font minimum sizes, legal-text rule |
| `fontget.py` | *Get more fonts*: find and download a Google Fonts family from github.com/google/fonts, add a local font file, install/remove user fonts |
| `pictures.py` | pictures on labels: reading files (PNG, JPG, GIF, BMP, WebP, TIFF, ICO; EXIF, transparency, CMYK, 16-bit, animations, size limits; a plain message for HEIC/SVG), the embedded picture dict and how it is stored small (`for_storing`, `compact`), colour → black and white (threshold with Otsu, Floyd–Steinberg dither), *My pictures* |
| `qrcodes.py` | QR codes: what they hold (link / phone / email / text), segno matrix, whole-dot module sizes, minimum size |
| `extras.py` | places a picture and/or QR code on a label (above, below, left, right, all four corners; top or bottom of the circle on round labels), text flowing around them, the Picture label, shrinking them before the wording, the QR size slider's range (`qr_size_range`) |
| `printsettings.py` | per-printer print settings (darkness, speed, nudge, upside down, gap, media, after printing) → TSPL/ZPL values; nudging/turning the picture |
| `calibrate.py` | setting up a new roll: set-up jobs per language and kind of roll, the line-up label, by-hand instructions, the per-printer "last roll" and the *New roll?* notice logic |
| `render.py` | draws a layout as the exact 1-bit printer bitmap (turned a quarter turn for a label laid out the other way round); on-screen preview (always upright); PNG export |
| `tspl.py` | TSPL job builder (LP610BT and clones) |
| `zpl.py` | ZPL job builder (Zebra), plus a decoder used by tests and `--selftest` |
| `printers.py` | printer discovery (Linux sysfs + CUPS, Windows spooler; adds paired Bluetooth printers from `btscan.py` and the network printers the person added), resolution detection, sending jobs (spooler, CUPS, device file, TCP, Bluetooth RFCOMM socket, COM port), status, network printers (`add_network_printer`, `network_printers`, `check_network`) |
| `btscan.py` | lists paired Bluetooth devices without connecting (`bluetoothctl devices`/`info` on Linux, PnP `BTHENUM` entries on Windows) and turns the printers among them into `Printer`s |
| `known.py` | known printer models: bundled `known_printers.json` + the user's update file |
| `cottage.py` | cottage food state rules (bundled `cottage_rules.json` < imported update < the user's own edits), "Label check", net quantity wording |
| `bakery.py` | the baker's files: *My bakery* details, *My ingredients* (seeded from `starter_ingredients.json`), *My products* |
| `bakery_dialogs.py` | Set up my bakery, My bakery, My ingredients, My products windows |
| `usbscan.py` | lists every USB device for "My printer isn't in the list" |
| `report.py` | the plain-text printer report a user pastes into a GitHub issue when asking for help (no label content); the new-issue link (https://github.com only, report never in the address) and the e-mail fallback |
| `settings.py` | settings file, data/labels folders, log file, autosave |
| `app.py` | main window: form, preview, printer menu, PRINT |
| `dialogs.py` | all other windows: pickers, save/open, settings, printers, Add a network printer, USB devices, report |
| `font_dialogs.py` | Lettering, the font list (names drawn in their own font), Get more fonts |
| `picture_dialogs.py` | Picture on the label, My pictures, QR code, Print settings, Set up a new roll windows |
| `widgets.py` | big-button Tk building blocks: `Modal`, `button`, `ask`/`tell` (web addresses in the message become links), calendar, toggles, `LinkLabel` (http/https only, `safe_url`), `ScrollFrame` (scrolls the focused widget into view, `scroll_target`) |

Nothing outside `app.py`, `dialogs.py`, `bakery_dialogs.py`, `font_dialogs.py`, `picture_dialogs.py` and `widgets.py` imports Tk, so
everything else is tested headless.

## Data flow

```
 form (app.py)                    the user types; each change edits App.doc
   │
   ▼
 LabelDoc (model.py)              template + stock id + fields (dates as ISO strings)
   │                              + the selected printer's dpi (203 or 300; not in the doc)
   ▼
 stocks.get(stock, dpi)           the label in that printer's dots
 templates.build_blocks()         fields → text Blocks with preferred/minimum sizes
 lettering.apply()                each Block gets its font (doc.lettering); minimums × font's
                                  min_scale; required wording forced to a readable sans
 extras.layout_with_extras()      (only with a picture / QR code / Picture label) places them
                                  and takes their space out of the Region
 templates.layout() / fit()       blocks → placed Lines that fit the Region
   │                              (rectangle inside margins, or circle on round labels;
   │                               a QR code is an exclusion the text flows around)
   ▼
 render.draw_layout()             pictures, Lines, QR → mode "1" image, stock.w × stock.h dots
   │                 ╲
   │                  ╲──────────▶ render.preview()  scaled copy for the screen
   ▼
 printsettings.adjust_image()     the printer's nudge / upside down (on the picture, not commands)
 printers.build_job()             picks the language for the chosen printer; print settings →
   ├── tspl.build_job()           SIZE/GAP/DENSITY/SPEED/CLS + BITMAP + PRINT
   └── zpl.build_job()            ^XA … ^GFA (hex bitmap) … ^PQ … ^XZ
   │
   ▼
 printers.send()                  on a worker thread; one of
   ├── windows_raw                RAW document through the Windows spooler
   ├── windows_driver             picture drawn through the Windows driver (fallback)
   ├── cups                       lp -o raw
   ├── device                     write to /dev/usb/lpN (or a udev symlink)
   └── network                    raw TCP to host:port (9100 unless the address says otherwise)
```

`FOOD_LABELER_DRY_RUN=<folder>` short-circuits `printers.send()`: jobs are
written to files in that folder instead. The tests always set it.

### Resolution (203 / 300 dpi)

The print head's resolution is a property of the printer (`printers.printer_dpi`:
the user's choice in *My printers → Sharpness* or *Advanced*, else "300dpi"
in the 1284 model / Windows driver name, else the model's `dpi` in
`known_printers.json`, else 203). `App.current_dpi()` is the selected
printer's (203 when none is selected) and is passed to `render.render(doc,
ctx, dpi=…)`; picking a printer with another resolution draws the label
again. Nothing about dpi is stored in `.label` files.

The label is laid out in physical units: `stocks.get(id, dpi)` gives the same
mm size in that printer's dots (`SIZES_DOTS`: the 203 dpi numbers are the
historic ones, every row equals round(mm × dpi / 25.4)). Every other fixed
number — margins, minimum font sizes, the round label's inner margin and
circle, QR module/target/gaps, the test label — is written in 203 dpi dots
and goes through `stock.d()`, which returns it unchanged at 203 and scales it
by dpi/203 otherwise; preferred sizes are already fractions of the label.
Cottage statement minimums convert points with the real dpi. So 203 dpi
output is byte-identical to earlier versions (`tests/test_dpi.py` checks 130
labels against stored hashes) and a 300 dpi label looks the same, only
sharper (`docs/samples/dpi-203-vs-300.png`).

TSPL `SIZE`/`GAP` stay in mm; `BITMAP` and ZPL `^PW`/`^LL`/`^GFA` come from
the image, so they are in the printer's dots; ZPL `^LT` is scaled. A model's
`max_width_dots` is converted to the label's dpi and wider labels are refused
before anything is sent (`printers.too_wide_message`). *Save as picture*
writes the printer's dots (each as 2 × 2 pixels) with the PNG dpi set to
dpi × 2, so it prints at the real size. The preview scales the bitmap to the
window, so it looks the same at either resolution.

### Pictures and QR codes

A label may carry a picture (`LabelDoc.picture`, see `pictures.py`) and a QR
code (`LabelDoc.qr`, see `qrcodes.py`). The picture is kept as the original
(colour, with transparency, at most 2000 px on its longest side) and turned
into dots only when drawn, at the final size and the printer's resolution:
greyscale + LANCZOS resize first, then a threshold (*Logo*, Otsu's value
unless the user moved *Lighter/Darker*) or Floyd–Steinberg dither (*Photo*,
with brightness/contrast); *Swap black and white* inverts, transparent parts
are always paper and *Remove the background* makes near-white paper too.
Results are cached per picture, settings and size, because the label is
redrawn on every key press.

`extras.arrange()` gives each item its box. The bands come first: *Above
the name* across the top and *Below the writing* across the bottom (several
items side by side, centred); their space comes off `Region.top` /
`Region.bottom`. Then each side, inside what is left: *Left/Right side* is a
column (at most 45 % of the width) the height of the text area, and the four
corners just their own box at the top or bottom of that side; a corner and a
column on the same side share one column, so nothing overlaps. Side space
becomes `Region.exclusions` entries, so wrapping flows around it. On round
labels (`extras.where`) bottom places go across the bottom of the circle and
everything else across the top, and pictures are masked to the circle.
`tests/test_placements.py` checks that no picture, QR code and line of
writing overlap, for every placement and pair of placements on every size.
QR codes are drawn from segno's matrix with an integer module (≥ 3 dots
at 203 dpi, scaled for 300) and a 4-module quiet zone that is kept white;
a size that can't give that is refused with a plain message. The QR window's *How big?* slider only
covers `extras.qr_size_range()`: from the first size whose module is at
least the minimum for what the code holds (at this size and dpi) to the
last size at which the layout still prints the code as asked and everything
fits, at most 60 % of the text area's height when there is writing.
If the text doesn't fit, `fit()` shrinks it as usual (never below each
block's minimum, so legal wording keeps its size); only then are the picture and code made 15 % smaller at a time, down
to 6 mm / 3-dot modules, and if it still doesn't fit the overflow names the
picture or QR code. The *Picture label* (`template == "picture"`) puts one
picture in the area left after its words (bottom 28 %) and any QR column:
*Fit inside* keeps it whole (and inside the circle), *Fill the label* covers
the area and cuts off what sticks out.

*My pictures* is `<data>/pictures/` (one PNG per picture plus
`pictures.json`); choosing one gives exactly the same embedded PNG.

The embedded PNG is kept small (`pictures.for_storing`): greyscale ("L"),
with alpha ("LA") only when part of it is see-through, exact black and
white dots ("1") when that is all it has, at most 1600 pixels on its
longest side (3600 for black and white), never enlarged. That gives the same
greys the print conversion makes from colour, so what prints doesn't
change; a 12 megapixel photo goes in at well under 1.5 MB instead of
several. Pictures in older files (colour, up to 2000 pixels) open as they
are and `pictures.compact` (in `LabelDoc.from_dict`, remembered per
picture) stores them the small way, so the next save is small.

Black stays black: nothing in the conversion ever swaps light and dark
except *Swap black and white*. `tests/test_picture_polarity.py` opens a
label saved with *Save as picture* as a picture and checks it prints the
same way round, in every PNG mode (1-bit, grey, palette with and without
a see-through colour, RGB, RGBA, LA, 16-bit, 2 × 2 with dpi) and file type,
and with every setting. A white or very light logo on a see-through
background (`pictures._light_shape`) prints its shape in black instead of
vanishing on white paper.

### Which way round (wide or tall)

`LabelDoc.orientation` is `""` (the roll's own way: `stocks.natural`, wide
for every size but 4 × 6) or `"wide"`/`"tall"` when the label is laid out
the other way round (never on round labels). `LabelDoc.set_orientation`
stores the roll's own way as `""`, so only turned labels say so in the file.
For a turned label `render.render()` lays out on `stocks.rotated(stock)`
(width and height swapped, everything else the label's own), draws it
upright and turns the picture a quarter turn clockwise into the roll's
size: `RenderResult.image` is always `stock.w × stock.h` (what TSPL/ZPL
get), `upright` is the label as read (the preview and *Save as picture*),
and the layout's coordinates belong to `layout_stock`. The upright label's
left edge comes out of the printer first (its right edge when the printer
prints upside down); the preview draws an arrow there. Nudge and upside down
still work on the printed picture. With no orientation set, every label is
byte-for-byte what it was (the 203 dpi baseline is unchanged).

### Print settings

`printers[<id>]["print"]` in settings.json holds only what the user changed
in *Print settings…* (`printsettings.clean` checks ranges). Darkness, speed
and gap come first, then the older per-size Advanced values, the model's
defaults and the size's defaults. Media type and *after printing* are sent
(`GAP`/`BLINE`/`GAP 0`, `OFFSET`; `^MN`, `^TA`) only once the user has set
them, so with nothing set every job is byte-identical to earlier versions.
Nudge and upside down change the picture (`adjust_image`), not printer
commands. *Darkness test* (three labels in one job) and *Feed one blank
label* (`FORMFEED` / `~PH`) are only sent from their buttons.

### Setting up a new roll (calibration)

*Print settings → New roll? Set it up…* (and *Advanced → Feed / calibrate…*,
both via `App.setup_roll`) opens `RollSetupDialog`. `calibrate.setup_job`
builds the job:

| roll | TSPL | ZPL |
|------|------|-----|
| gaps | `SIZE` + `GAP g mm,0 mm` + `GAPDETECT` (byte-identical to 1.2.0) | `^XA^MNW^XZ` + `~JC` |
| black marks | `SIZE` + `BLINE b mm,0 mm` + `BLINEDETECT` (unverified on LP610BT clones) | `^XA^MNM^XZ` + `~JC` |
| continuous | `SIZE` + `GAP 0 mm,0 mm` (nothing fed) | `^XA^MNN^PW^LL^XZ` (nothing fed) |

The gap / mark height comes from the printer's print settings, then
Advanced, then the label size. `^JUS` is never sent. The language is the
printer's Type, so a printer with no known model still gets the right job.
`calibrate.send_setup` sends only when its `confirm` callback returns True
(the "This feeds 2–4 blank labels. OK?" question). The line-up label
(`lineup_label_image`: box 1 mm inside the edges, or a circle on round
labels, the size's name and an arrow to the top edge, which comes out
first) goes through `printsettings.adjust_image` and `printers.build_job`
like any label. The by-hand steps come from the model's `calibrate_by_hand`
in `known_printers.json`, else `GENERIC_BY_HAND`.

After a set-up, `printers[<id>]["roll"] = {"stock", "media", "date",
"same"}` is saved and the kind of roll is written to the print settings.
`App.refresh_roll_notice` (run when the label, its size or the printer list
changes) shows the one-line *New roll in the …?* notice when
`calibrate.show_notice` says the size differs from that roll and the person
hasn't pressed *No, same roll* for this size (`same`, emptied by the next
set-up). Nothing sends from the notice; `tests/test_calibrate.py` checks
that no method that runs by itself can reach a send.

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

### Lettering (fonts)

Every Block and Line carries a `font` (a family name; `""` = DejaVu Sans,
so the standard look is byte-identical to earlier versions). `lettering.py`
keeps a registry of `Face`s: the bundled ones (`BUNDLED`, files in
`food_labeler/fonts/`) and the user's (`<data>/fonts/<folder>/font.json`).
Fonts are read into memory once and cached per (file, size, bold); variable
fonts get their weight axis set to 400 or 700. Text widths and line heights
used by `fit()` come from the same fonts that `render.draw_layout()` draws
with, so wrapping stays exact.

`lettering.apply()` gives the name block (food / product / lot / free text)
the label's *name* font and every other block the *other* font, which must
be `readable`; blocks in `LEGAL_KEYS` (and `statement:*`) fall back to DejaVu
Sans if they would otherwise get a non-readable font. Each block's minimum
size is multiplied by the face's `min_scale` (script fonts 1.3–1.6), so
auto-shrink never goes below a legible size for that font. A font the
computer doesn't have resolves to DejaVu Sans; `lettering.missing()` names
it and the window offers to get it.

*Get more fonts* runs `fontget.fetch_family()` on a worker thread (results
via a queue, like printing); see [fonts.md](fonts.md) for how a family is
found and checked.

### Cottage food labels

The cottage template (`templates._cottage_blocks`) reads only the label's
own fields from the document; the business details and the state's
statements come from the render context, which `App.render_ctx()` builds
from `bakery.Profile` and `cottage.CottageRules.effective(state)`:

```
 cottage_rules.json (bundled)  ─┐
 <data>/cottage_rules.json     ─┼─▶ CottageRules.base(state)      (update wins if checked_on ≥ bundled)
 <data>/cottage_overrides.json ─┘   CottageRules.effective(state) (user edits on top, with markers)
                                            │ .to_ctx()
 <data>/my_bakery.json ──▶ Profile ─────────┼──▶ ctx["cottage"] = {"rule", "profile"}
                                            ▼
                         templates._cottage_blocks()  ──▶ fit() ──▶ render
                         cottage.check_label()        ──▶ Label check panel, PRINT question
```

Each statement becomes a Block whose minimum size is the state's minimum
(points → dots), so `fit()` can never shrink it further; if the label still
doesn't fit, the overflow message suggests a bigger label and points at the
ingredients. Statements may contain `{business_name}`, `{permit_number}` or
`{county}`, filled from *My bakery*.

User edits remember the default they were based on, so a changed default is
detected (`CottageRules.pending_changes`) and asked about once
(`bakery_dialogs.ask_about_changes`) instead of being overwritten. User
files are versioned; unreadable ones are renamed `*.broken` rather than
overwritten, and files written by a newer version are read but not written.
See [cottage-rules.md](cottage-rules.md).

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
A Bluetooth printer is `bt:<address>` on both systems (`bt:<COM port>` on
Windows if the address can't be read): LP610BT units all have the same
Bluetooth name, so the address is what tells them apart. Lists show only
its last two bytes ("Bluetooth (…3F:A2)"), and the printer report never has
more than that.

### Bluetooth (alpha)

Classic Bluetooth printers (Serial Port Profile) take the same TSPL bytes as
over USB, so Bluetooth is only another way to deliver `build_job`'s bytes.
Pairing is always done in the system's settings; the program only reads
which devices are paired and never pairs or connects to look.

- **Linux:** method `bluetooth`, target the address. `send_bluetooth` opens
  an `AF_BLUETOOTH` / `BTPROTO_RFCOMM` socket (standard library, 8 s connect
  timeout), sends the job in `bt_chunk`-byte pieces `bt_delay_ms` apart
  (per model, defaults 4096 and 20), waits half a second and closes. The
  channel is the one chosen in Advanced (`bt_channel`), else the one that
  worked last time (`bt_channel_found`), else 1, 2, 3; a refused channel
  moves on at once. Errors become plain messages: Bluetooth switched off
  (also read from `/sys/class/rfkill` before connecting), not paired, not
  answering (off or out of range), not allowed.
- **Windows:** pairing an SPP printer makes an outgoing virtual COM port.
  Method `serial`, target `COM5`: `send_serial` writes to `\\.\COM5` in
  the same pieces (only `COM1`–`COM999` are accepted). If the maker's driver
  is installed on that port, the spooler printer is used (`windows_raw`) and
  only marked as Bluetooth. Python's own RFCOMM sockets also exist on
  Windows, and `send_bluetooth` works there, but discovery uses the COM port.
- **macOS:** not supported.
- `Printer.bluetooth` makes a printer alpha unless its model has
  `verified_bluetooth` as well as `verified_on_paper`; `status()` never
  connects. `auto_pick` prefers a cable over Bluetooth.

### Network printers

A network printer is a printer the person added with *Add a network
printer…* (My printers, My printer isn't in the list, Set up my printer;
Advanced lists them and opens the same window): `printers[<id>]` in
settings.json with `"manual": true, "method": "network", "target":
"host:port", "kind"` and the kind of printer they said it is (`"model"`, a
known printer id). `App.set_found` adds them to what discovery found, so
they count as connected for printing, test labels, print settings, setting
up a roll, the darkness test and feeding. Nothing looks for printers on the
network. *Test the connection* (`printers.check_network`) opens a TCP
connection with a 3 s timeout on a worker thread and closes it without
sending anything. A network printer is alpha unless its model has
`verified_network` as well as `verified_on_paper` (the LP610BT-compatible
entry has, from printing through a raw TCP bridge).

### Background work

Tk may only be used from the main thread. Printer discovery (every 15 s and
on request, including the `bluetoothctl` calls, each with a 3 s timeout and
8 s for the whole Bluetooth scan), USB scans and sending jobs run on daemon
threads and hand their results back through a `queue.Queue` that the window
polls with `after()`. Windows that look for printers on the spot reuse the
last Bluetooth list if it is less than 10 s old.

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
| `*.label` | wherever the user saves (default `Documents/My Food Labels`) | JSON: `{"app": "easy-labels", "version": 1, "template", "stock", "fields", "copies"}`, plus optional `"orientation": "wide" \| "tall"` (only when turned), `"lettering": {"name", "other"}` (font family names; only written when not the standard look), `"picture": {"png" (base64), "name", "place", "size", "mode", "threshold", "brightness", "contrast", "invert", "remove_bg"}` and `"qr": {"what", "value", "caption", "place", "size"}` (only written when the label has them) |
| `pictures/` | data folder | *My pictures*: `<id>.png` files and `pictures.json` `{"format": "food-labeler-pictures", "version": 1, "pictures": [{"id", "name", "file"}]}` |
| `fonts/<folder>/` | data folder | fonts the user added: the font file(s), license, `font.json` `{"format": "food-labeler-font", "version": 1, "name", "regular", "bold", "variable", "category", "license", "source", "min_scale"}` |
| `settings.json` | data folder | JSON, merged over built-in defaults key by key (unknown keys and wrong types are ignored) |
| `autosave.json` | data folder | `{"doc": <label>, "path": "...", "dirty": bool}` |
| `known_printers.json` | bundled in the package, and optionally in the data folder | see [printer-definitions.md](printer-definitions.md) |
| `app_config.json` | bundled | `issues_url` (GitHub issues page for help, must be https://github.com/…/issues), support e-mail address (fallback) and name |
| `cottage_rules.json` | bundled, and optionally in the data folder | state presets, see [cottage-rules.md](cottage-rules.md) |
| `cottage_overrides.json` | data folder | the baker's own wording / required items, see [cottage-rules.md](cottage-rules.md) |
| `my_bakery.json` | data folder | `{"format": "food-labeler-bakery", "version": 1, "state", "business", "legal_entity", "street", "street2", "city", "region", "zip", "phone", "email", "permit", ...}`; first created from the package-label kitchen details in `settings.json` |
| `my_ingredients.json` | data folder | `{"format": "food-labeler-ingredients", "version": 1, "ingredients": [{"id", "name", "sub", "allergens", "check"}]}`; seeded once from the bundled `starter_ingredients.json` |
| `my_products.json` | data folder | `{"format": "food-labeler-products", "version": 1, "products": [{"id", "name", "net", "ingredients", "contains", "no_allergens", "storage", "best_by_days", ...}]}`; also the backup file format |
| `food-labeler.log` | data folder | text log, rotated at 512 kB (3 files) |

Files are size-checked before they are read (`model.read_text_limited`):
`.label` files and the autosave up to 64 MB, printer and state rules update
files 2 MB, *My products* / *My ingredients* backups and the baker's own
files 16 MB. A file that is too big, or nested absurdly deep, gets the same
plain "This isn't a … file" / "damaged" message as any other bad file; one in
the data folder is set aside as `*.broken`.

`settings.json` keeps per printer (`printers[<id>]`) the nickname, Type,
last label size, resolution choice (`"dpi"`), print settings (`"print"`) and
the last roll set up (`"roll"`, see *Setting up a new roll*).
It also keeps the last lettering per kind of label
(`"lettering": {"simple": {"name", "other"}, ...}`) as the default for new
labels.

The `.label` format id `easy-labels` is the project's original name and must
not change, or existing files stop opening. Adding the cottage template did
not change the format version (still 1): 1.0.0 files open unchanged, and a
cottage label opened in 1.0.0 falls back to a simple label instead of being
refused. `tests/test_cottage.py` keeps 1.0.0 files of every kind opening. Lettering
(1.2.0) is likewise an optional key: older files open in the standard
lettering and save back byte for byte (`tests/test_fonts.py`). So are
`"picture"` and `"qr"` (1.2.0); a picture label opened in an older version
falls back to a simple label. `"orientation"` (1.5.0) is optional too: an
older version lays a turned label out the roll's way, and the new places
(`"bottom"`, `"corner_bottom_left"`, `"corner_bottom_right"`) fall back to
*above* there. A package label's old `fields["qr"]` web
address becomes a `"qr"` object when opened (the file on disk only changes
when saved), and saving keeps writing the code's text to `fields["qr"]` so
older versions still print the code (`tests/test_qr.py`).

## Settings locations

| | Windows | Linux | macOS (from source) |
|---|---|---|---|
| data folder | `%APPDATA%\FoodLabeler` | `$XDG_DATA_HOME/food-labeler` (default `~/.local/share/food-labeler`) | `~/Library/Application Support/FoodLabeler` |
| saved labels | `Documents\My Food Labels` | `~/Documents/My Food Labels` (`xdg-user-dir DOCUMENTS`) | `~/Documents/My Food Labels` |

Environment overrides: `FOOD_LABELER_DATA`, `FOOD_LABELER_LABELS`,
`FOOD_LABELER_DRY_RUN`.

## Packaging

`food_labeler.spec` builds a one-file, windowed program and bundles the
fonts (the whole `fonts/` folder with one sub-folder per family; the spec
refuses to build if a family folder lacks its font files or `OFL.txt`), icons, `known_printers.json`, `app_config.json`, `cottage_rules.json`
and `starter_ingredients.json`. On Windows it also
embeds a version resource (file/product version from `__version__`, product
"Food Labeler", company "High Thyme Kitchen"). `--selftest` is run on every
build to prove the bundle is complete.
