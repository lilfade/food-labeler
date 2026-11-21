# Changelog

All notable changes to Food Labeler are listed here. Version numbers follow
[Semantic Versioning](https://semver.org/); the number itself lives in
`food_labeler/__init__.py`.

## 1.2.0 — unreleased

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
