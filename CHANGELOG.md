# Changelog

All notable changes to Food Labeler are listed here. Version numbers follow
[Semantic Versioning](https://semver.org/); the number itself lives in
`food_labeler/__init__.py`.

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
