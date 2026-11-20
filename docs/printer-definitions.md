# Printer definition files

Food Labeler recognises printer models from a list in
`food_labeler/known_printers.json` (shipped inside the program). We can send
users an **update file** in the same format; they add it with
*Settings → Add printer update file…* (also on the "My printer isn't in the
list" screen). It is saved as `known_printers.json` in their data folder
(`%APPDATA%\FoodLabeler` on Windows, `~/.local/share/food-labeler` on Linux)
and merged on top of the built-in list: an entry with the same `id` replaces
the built-in one completely (fields are not merged one by one), new ids are
added. Later update files are merged into the same user file the same way, so
several updates add up. If the user file is ever damaged it is ignored and
the built-in list keeps working.

Files are checked strictly. Anything in a printer entry that doesn't match
this format (unknown keys, bad ids, bad patterns, non-203-dpi printers…)
rejects the whole file with a plain message, and nothing is saved. Extra
top-level keys (such as `"updated": "2026-11-20"`) are allowed and ignored.
Save files as UTF-8 (with or without a byte-order mark).

## Format

```json
{
  "format": "food-labeler-printers",
  "version": 1,
  "printers": [
    {
      "id": "lp610bt-compatible",
      "name": "LP610BT-compatible label printer",
      "brands": ["Labelnize", "Flexyva", "Polono"],
      "language": "tspl",
      "dpi": 203,
      "media": "gap",
      "usb": ["0483:2025"],
      "ieee1284": {"MDL": "LP610", "CMD": "TSPL"},
      "windows": ["LP610", "Polono", "Labelnize", "Flexyva", "4B-", "BAR PRINTER"],
      "density": {"default": 8, "small": 9},
      "speed": {"default": 4, "small": 3, "round": 3},
      "stocks": ["small", "medium", "large", "round", "xl"],
      "notes": "free text for us"
    }
  ]
}
```

| key | required | meaning |
|-----|----------|---------|
| `format` | yes | must be `"food-labeler-printers"` |
| `version` | yes | must be `1` |
| `printers` | yes | 1–200 entries; each `id` once |
| `id` | yes | lowercase letters, digits, `-` (max 64). Same id as a built-in entry replaces it. |
| `name` | yes | what the user sees (max 80 chars) |
| `brands` | no | brand names sold with this hardware. With 2+ brands the name is shown as `name (A / B / C…)` because clones share USB ids — never claim one brand. |
| `language` | yes | `"tspl"` (LP610BT and clones) or `"zpl"` (Zebra) |
| `dpi` | no | must be 203 (the only resolution this version lays out for) |
| `media` | no | `"gap"` (default), `"continuous"`, `"black-mark"` (informational for now) |
| `usb` | no | list of `"vvvv:pppp"` USB vendor:product ids (hex) |
| `ieee1284` | no | map of IEEE 1284 device-id keys to regular expressions; **all** must match (case-insensitive search). Keys as the printer reports them, e.g. `MFG`, `MDL`, `CMD`, `MANUFACTURER`, `MODEL`, `COMMAND SET`. |
| `windows` | no | regular expressions matched against the Windows printer name + driver name (and CUPS queue name/URI on Linux) |
| `density` | no | TSPL `DENSITY` 0–15: a number, or `{"default": n, "<size>": n}` |
| `speed` | no | TSPL `SPEED`: same shape as `density` |
| `stocks` | no | label sizes the printer takes: `small`, `medium`, `large`, `round`, `xl` (default: all). Printing another size asks "Print anyway?" |
| `notes` | no | free text, ignored by the program |

Label size ids: `small` 32×25 mm, `medium` 3×2 in, `large` 4×2 in,
`round` 2 in circle, `xl` 4×6 in.

## How matching works

1. **IEEE 1284 id** (Linux reads `/sys/class/usbmisc/lpN/device/ieee1284_id`):
   entries with more `ieee1284` keys are tried first.
2. **USB id** (`usb`).
3. **Names** (`windows` patterns; longer patterns are tried first, so a
   specific entry such as `ZP ?450` beats a generic `Zebra`).

The printer *language* comes from the 1284 `CMD`/`COMMAND SET` if present
(TSPL → TSPL, ZPL → ZPL), else from the matched entry, else from name
heuristics, else TSPL. The user can override it per printer under
*My printers… → Type*.

Identical units (same USB id **and** serial, e.g. two LP610BT clones) are told
apart by USB port path on Linux (`usb:1-1.3`, `usb:1-1.4`) and by
printer name + port (`USB001`, `USB002`) on Windows. `/dev/usb/lpN` numbers
are never used as identity because they change between boots.

## Making an update

1. Ask the user for the report (*Send this to High Thyme Kitchen*): it lists
   USB ids, the 1284 id and the Windows driver name.
2. Write a file with just the new/changed entries, run
   `python -c "from food_labeler import known; print(known.parse_file_text(open('my-update.json', encoding='utf-8').read()))"`
   to validate it, and send it.
3. If the model should ship with the program, add the entry to
   `food_labeler/known_printers.json` as well (see CONTRIBUTING.md).
