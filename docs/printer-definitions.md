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
this format (unknown keys, bad ids, bad patterns, a resolution other than
203 or 300 dpi…)
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
      "max_width_dots": 812,
      "media": "gap",
      "usb": ["0483:2025"],
      "ieee1284": {"MDL": "LP610", "CMD": "TSPL"},
      "windows": ["LP610", "Polono", "Labelnize", "Flexyva", "4B-", "BAR PRINTER"],
      "density": {"default": 8, "small": 9},
      "speed": {"default": 4, "small": 3, "round": 3},
      "stocks": ["small", "medium", "large", "round", "xl"],
      "notes": "free text for us",
      "calibrate_by_hand": "Put at least 4 labels in the printer and close the lid. Hold the feed button down for about 3 seconds, until the printer starts feeding, then let go."
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
| `language` | yes | `"tspl"` (LP610BT and clones), `"zpl"` (Zebra) or `"driver"`: the printer doesn't take TSPL or ZPL and only prints through its maker's driver (see *Driver-only printers* below) |
| `dpi` | no | print head resolution: `203` (default) or `300`. 600 dpi and anything else is refused. Labels are laid out in mm, so the same label prints the same size at either resolution, only sharper at 300. |
| `max_width_dots` | no | widest the head can print, in dots at this entry's `dpi` (LP610BT-type 812, Zebra ZP450 832 = 4.09 in). Labels wider than this are refused with a plain message. Leave it out if not known. |
| `max_width_mm` | no | the same in mm (e.g. `104`), when the maker gives the width in mm; turned into dots at `dpi` (rounded down). If both are given, `max_width_dots` wins. |
| `verified_on_paper` | no | `true` only when we have printed real labels on this model. Default `false`: the printer is shown as *alpha — not tested yet* and the first print to it shows a one-time notice. Only the LP610BT-compatible and Zebra ZP450 entries are `true`. |
| `verified_bluetooth` | no | `true` only when we have also printed real labels on this model **over Bluetooth**. Default `false`: reached over Bluetooth, the printer is *alpha* even if `verified_on_paper` is `true`. Only counts together with `verified_on_paper`. |
| `bt_chunk` | no | how many bytes to send at a time over Bluetooth, 64–65536 (default 4096). Cheap printers have small buffers; LP610BT-type printers use 2048. |
| `bt_delay_ms` | no | pause between those pieces in milliseconds, 0–1000 (default 20; LP610BT-type 30). |
| `media` | no | `"gap"` (default), `"continuous"`, `"black-mark"` (informational for now) |
| `usb` | no | list of `"vvvv:pppp"` USB vendor:product ids (hex) |
| `ieee1284` | no | map of IEEE 1284 device-id keys to name patterns (see *Name patterns* below); **all** must match. Keys as the printer reports them, e.g. `MFG`, `MDL`, `CMD`, `MANUFACTURER`, `MODEL`, `COMMAND SET`. |
| `windows` | no | name patterns matched against the Windows printer name + driver name (and CUPS queue name/URI on Linux); any one matching is enough |
| `density` | no | TSPL `DENSITY` 0–15: a number, or `{"default": n, "<size>": n}` |
| `speed` | no | TSPL `SPEED`: same shape as `density` |
| `stocks` | no | label sizes the printer takes: `small`, `medium`, `large`, `round`, `xl` (default: all). Printing another size asks "Print anyway?" |
| `notes` | no | free text, ignored by the program |
| `calibrate_by_hand` | no | how to set up a new roll with the printer's own button, in plain words (text, at most 600 characters). Shown in *Set up a new roll* under "If it still isn't right:". Without it a general instruction is shown. Check it against the printer's own guide. |

Label size ids: `small` 32×25 mm, `medium` 3×2 in, `large` 4×2 in,
`round` 2 in circle, `xl` 4×6 in.

## Name patterns

Patterns in `ieee1284` and `windows` are **plain text**, not regular
expressions. A pattern matches when its text appears anywhere in the name,
ignoring upper/lower case. Separate alternatives with `|`:
`"ZP450|ZP 450"` matches *Zebra ZP450* and *ZDesigner ZP 450-200dpi*.
Every other character is taken literally, so `?`, `*`, `.`, `(`, `[`, `^`
and `$` only match themselves. Each pattern (all its alternatives together)
may be at most 80 characters, and only the first 200 characters of a name
are looked at.

Until 1.3.1 these were regular expressions. Older update files still import
without an error, but any regular-expression characters in them are now
taken literally, so a pattern such as `ZP ?450` no longer matches *ZP450*:
write it as `ZP450|ZP 450`. Plain-word patterns such as `Zebra` or `LP610`
work exactly as before.

## Tested and alpha printers

Every entry without `"verified_on_paper": true`, and every printer that
matches no entry at all, is *alpha*: its name has *(alpha — not tested yet)*
after it in the printer list, *My printers*, the USB devices window and the
*Print settings* title, and the first print to it asks once:
"This printer hasn't been tested with Food Labeler yet. It should work, but
if it doesn't, please tell us on GitHub" (**OK, print** / **Cancel**). The
answer is remembered for that printer (`"alpha_ok"` in its settings). The
printer report says `tested` or `alpha (not tested yet)` for each printer.

Bluetooth counts separately. A printer reached over Bluetooth is alpha
unless its entry has both `"verified_on_paper": true` and
`"verified_bluetooth": true`, and its one-time notice says that printing over
Bluetooth hasn't been tested yet. A Bluetooth printer has its own id
(`bt:<address>`), so the notice is shown once for it even if the same
printer was already used over USB. No entry has `verified_bluetooth` yet.

## Driver-only printers

Some cheap printers don't understand TSPL or ZPL; they only print what the
maker's own driver sends them. Give them `"language": "driver"`. On Windows,
Food Labeler then prints the label picture through that driver, exactly like
the *Print through Windows driver* switch in *Advanced* (the darkness and
speed in *Print settings* don't apply; set those in the driver). On Linux
printing stops with a plain message saying the printer needs its maker's
driver, and nothing is sent. Setting up a new roll can't be done through a
driver, so the window's "with the printer's own button" text matters for
these printers. If the printer's IEEE 1284 id names `TSPL` or `ZPL`, or the
user picks a *Type* in *My printers*, that wins and the label is sent in that
language as usual. EPL-only printers are treated as `driver` for now.

## How matching works

1. **IEEE 1284 id** (Linux reads `/sys/class/usbmisc/lpN/device/ieee1284_id`):
   entries with more `ieee1284` keys are tried first.
2. **USB id** (`usb`).
3. **Names** (`windows` patterns): the entry with the longest alternative
   found in the name wins, so a specific entry such as `ZDesigner ZP 450`
   beats a generic `Zebra`, and `POLONO PL60` beats the LP610BT entry's
   `Polono`. On a tie the entry listed first wins.

The printer *resolution* is, in order: the user's own choice for that printer
(*My printers… → Sharpness*, or *Advanced*), else `300` if the 1284
`MODEL`/`MDL` or the Windows printer/driver name says so (`300dpi`,
`300 dpi` or `-300`, e.g. Zebra *ZD421-300dpi*; `200dpi`/`203dpi` means
203), else the matched entry's `dpi`, else 203. It is never stored in
`.label` files, so a label prints right on any printer.

The printer *language* comes from the 1284 `CMD`/`COMMAND SET` if present
(TSPL → TSPL, ZPL → ZPL), else from the matched entry, else from name
heuristics, else TSPL. The user can override it per printer under
*My printers… → Type*.

Identical units (same USB id **and** serial, e.g. two LP610BT clones) are told
apart by USB port path on Linux (`usb:1-1.3`, `usb:1-1.4`) and by
printer name + port (`USB001`, `USB002`) on Windows. `/dev/usb/lpN` numbers
are never used as identity because they change between boots.

## Making an update

1. Get the printer report (the person pastes it into the *Add my printer*
   issue form; in the app: *Ask for help on GitHub*): it lists USB ids, the
   1284 id and the Windows driver name.
2. Write a file with just the new/changed entries, run
   `python -c "from food_labeler import known; print(known.parse_file_text(open('my-update.json', encoding='utf-8').read()))"`
   to validate it, and send it.
3. If the model should ship with the program, add the entry to
   `food_labeler/known_printers.json` as well (see CONTRIBUTING.md).
