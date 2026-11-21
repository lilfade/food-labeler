# Changelog

All notable changes to Food Labeler are listed here. Version numbers follow
[Semantic Versioning](https://semver.org/); the number itself lives in
`food_labeler/__init__.py`.

## 1.3.2 — 2026-11-21

Safety fixes.

- Printer update files: the printer names in them are now plain words
  (put `|` between alternatives) instead of patterns, so any update file
  is safe to add and printers are found as quickly as ever. Update files
  made for earlier versions still work; see
  [printer definitions](docs/printer-definitions.md) if one of yours used
  special characters.
- Files that are far too big, or damaged in unusual ways, are refused with
  the same plain message as any other file that can't be opened, instead
  of slowing the program down. If your settings file is ever damaged, a
  copy is kept as `settings.json.broken`.
- State rules from an update file you imported now say so ("From an update
  file you imported (checked … by whoever made it)") instead of looking
  like the rules checked by Food Labeler.
- The printer report lists only printers. To add the other things plugged
  in, tick **Also list everything else plugged in**; their serial numbers
  are never included.
- *My pictures* only ever uses its own folder, and printing straight to a
  USB printer only goes to a printer device.
- The release notes and the guide now say to download Food Labeler only
  from the Releases page, never from a link someone sends you.
- The program is built from exact, checked versions of the parts it uses.

## 1.3.1 — 2026-11-21

- 3 × 2 and 4 × 2 labels are drawn 50.0 mm tall instead of 50.8 mm. "2 inch"
  die-cut labels are really about 50 mm, so the bottom row of the picture
  landed in the gap and a border along the bottom edge didn't print. The
  size sent to the printer is unchanged.

## 1.3.0 — 2026-11-21

New roll? Set it up.

- **Print settings… → New roll? Set it up…** walks through setting up a
  new roll in three plain steps: put the roll in, say what is on it (label
  size and *labels with gaps / black marks / continuous roll*), and
  **Set it up**. It asks first ("This feeds 2–4 blank labels. OK?") and
  only then sends anything. **Settings → Advanced… → Feed / calibrate…**
  opens the same window.
- After setting up: **Print one test label** (a box 1 mm inside the edges,
  the size's name and an arrow pointing to the end that comes out first),
  printed with the printer's own print settings, then **Looks right** or
  **It's off — help me** (nudge the print, set it up again, or use the
  printer's own button).
- LP610BT-type printers: gaps use `GAPDETECT` exactly as before; black marks
  use `BLINE` + `BLINEDETECT` (not yet tried on these clones, so the window
  also shows how to do it with the printer's button); a continuous roll only
  sends the size. Zebra printers: `^MNW` / `^MNM` then `~JC`; a continuous
  roll only sets the label length. Settings are never saved in the printer
  for good (no `^JUS`). Printers of an unknown model get the job for their
  language and the general by-hand steps.
- Each printer remembers the roll last set up (size, kind, date). When you
  pick another label size for that printer, a short line under the printer
  offers to set up the new roll, with **No, same roll** to hide it for that
  size. It is only a line on the screen: nothing is sent without a click.
- The kind of roll chosen there is also kept in **Print settings**.
- Printer update files may now give `"calibrate_by_hand"`: how to set up a
  roll with that printer's own button, shown in the window. The built-in
  LP610BT-compatible, Zebra ZP450 and Zebra entries have it.
- `--selftest` also checks the set-up jobs and the test label.
- The new-roll reminder under the printer keeps its buttons on their own
  line, so *Set up* and *No, same roll* are never cut off.
- A long printer name no longer pushes the list's arrow onto its own line.

## 1.2.0 — 2026-11-21

Lettering: choose the fonts on your labels.

- **Lettering → Change…** on every kind of label: one font for the name of
  the food and one for everything else. The list shows each font's name in
  that font. The last choice is remembered for new labels of that kind.
- Comes with Atkinson Hyperlegible, Roboto, Open Sans and Lato (easy to
  read, for everything) and Playfair Display, Pacifico, Lobster and Caveat
  (for the name of the food), all under the SIL Open Font License. DejaVu
  Sans is still the standard lettering, so existing labels look the same.
- The wording the law asks for (ingredients, allergens, address, your
  state's statements) always stays in easy-to-read lettering.
- Script fonts are never shrunk below a size that can still be read; each
  font has its own smallest size.
- **Get more fonts…** fetches a font from Google Fonts by name (it shows a
  preview first and needs the internet only for this), and **Add a font file
  from my computer…** adds a .ttf or .otf. Added fonts are kept with your
  other Food Labeler files and can be removed again.
- A label that uses a font this computer doesn't have opens in the standard
  lettering and offers to get the font.
- Label files from earlier versions open unchanged; the file format is still
  version 1.

Sharper printing on 300 dpi printers.

- Each printer now has a **Sharpness** (in **My printers…** and
  **Settings → Advanced…**): *Normal (203 dpi) — most label printers* or
  *Sharp (300 dpi) — only if your printer says 300 dpi*. Food Labeler picks
  it for you: 300 dpi when the printer's name says so (for example Zebra
  *ZD421-300dpi*), otherwise 203 dpi.
- Labels keep their real size in millimetres and inches, so a label looks
  the same at either setting, only crisper at 300 dpi. The state's required
  wording keeps its minimum size in points at both.
- Labels printed on 203 dpi printers are exactly the same as before.
- A label size wider than the printer can print is refused with a plain
  message instead of being cut off.
- **Save as picture** saves the label at the printer's resolution and
  records it in the picture, so it prints at the right size.
- Printer update files may now say `"dpi": 300` and give the print width
  (`"max_width_dots"`). Nothing about resolution is saved in label files.

Pictures, QR codes and print settings.

- **Add a picture…** on every kind of label: above the name, on the left or
  right side or in the top-left corner, with a *Smaller ↔ Bigger* slider.
  The writing flows around it. Opens PNG, JPG, GIF, BMP and WebP (phone
  photos the right way up, see-through parts as paper; very big files are
  refused kindly).
- Black and white the way you want it, with a live preview of exactly what
  prints: *Logo / drawing (solid black)* with a *Lighter ↔ Darker* slider
  (it picks a good starting point by itself), or *Photo (tiny dots)* with
  brightness and contrast; *Swap black and white*; *Remove the background*.
- New kind of label, **Picture label**: one big picture (*Fill the label* or
  *Fit inside*), with a line of words under it if you want, for example a
  logo sticker or a round seal.
- The picture is saved inside the label file, so the file is complete on
  its own. **My pictures** keeps your logo for next time.
- The wording the law asks for always wins: the picture gets smaller first,
  and if it still doesn't fit the label says so.
- **Add a QR code…** on every kind of label: a website link (from *My
  bakery*, which now has a *Website* line), your phone number, your email or
  some text, with optional words under it. The code is drawn in whole
  printer dots with a clear border so phones can read it; a code that would
  be too small is refused with a plain message. The package label's old
  QR box is turned into this when an old label is opened.
- **Print settings…** next to the printer, kept for each printer:
  darkness, speed, *Nudge the print*, *Print upside down*, label gap, labels
  with gaps / black marks / continuous roll, and *Stop so I can tear it off*
  or *Feed a little extra*. **Darkness test** (3 labels, only when you press
  it) and **Feed one blank label**. **Reset to normal** puts it all back.
  Nothing changes for printers whose settings you never touch.
- The Picture, QR code and Print settings windows fit a laptop screen, and
  every button under the printer list is fully visible.
- At 300 dpi, letters no longer show a small gap inside words.
- Closing a window that was opened from another window gives the click lock
  back to the window underneath.

## 1.1.1 — 2026-11-20

- The cottage food form no longer squeezes the label preview and printer
  list into a thin strip; the screen keeps its left/right split.
- The Label check is shorter: one green line when everything is there, or
  just the missing items in red. **About (your state)'s rules…** shows the
  full list. The form below it stays in view on a laptop screen.
- The form's scroll bar can no longer be pushed off the edge.
- New screenshots in the README, including the cottage food screens.

## 1.1.0 — 2026-11-20

Labels for home bakers selling under their state's cottage food law.

- New kind of label, **Cottage food label**: product name, net weight (with
  grams added automatically when the state asks for it, or when you choose),
  ingredients, "CONTAINS:" allergens, storage line, made-on and best-by
  dates, "Produced by", your full address, phone, email and permit number as
  your state asks, and your state's required statement(s). Laid out like
  High Thyme Kitchen's own Nebraska package label.
- State presets for all 50 states and DC (plus "Custom / my own rules"),
  each with its official source and the date it was checked. States we
  couldn't confirm are marked "Unverified — check with your state".
- Required statements are never printed smaller than the state's minimum
  size; if everything doesn't fit, the label is refused with a suggestion to
  use a bigger label.
- **Label check**: a green/red list of what your state asks for. PRINT asks
  before printing a label with something missing.
- Your own wording and your own list of required items are kept separately
  from the built-in rules, so updates never overwrite them. Each edit is
  marked "edited by you" and can be reset to the state's suggestion; if a
  state's suggestion changes later, Food Labeler asks once whether to keep
  yours or use the new one.
- State rules update files can be added (Settings → My bakery).
- **Set up my bakery** (first run): state, then your details.
- **My ingredients**: save ingredients with what's in them and their
  allergens; build the ingredient line in order and fill in "Contains"
  automatically. Comes with an editable starter list of common baking
  ingredients (marked "check your package").
- **My products**: save a product and fill a label from it in one click;
  back up and restore to a file.
- Label files from 1.0.0 open unchanged; the file format is still version 1.

## 1.0.0 — 2026-11-20

First public release.

- Four kinds of label: simple food label, package label (ingredients,
  allergens, lot, best-by, kitchen details, optional QR code), date sticker
  and free text.
- Five label sizes at 203 dpi: Small 32 × 25 mm, Medium 3 × 2 in,
  Large 4 × 2 in, Round 2 in, Extra-large 4 × 6 in.
- Text is fitted automatically as large as possible; if it can't fit, the
  program says which part is too long instead of cutting it off.
- The preview is the exact picture that prints.
- Printers: LP610BT-compatible TSPL printers (Labelnize, Flexyva, Polono…)
  and Zebra ZPL printers such as the ZP450, by USB, Windows printer, CUPS
  queue or network (raw TCP). Identical printers are told apart by USB port.
- "My printer isn't in the list" helper with a printer report that can be
  e-mailed to High Thyme Kitchen; printer update files add new models.
- Saved labels, undo, autosave and session restore, bigger/smaller text.
- Windows `.exe` and Linux one-file program, built by GitHub Actions.
