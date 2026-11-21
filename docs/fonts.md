# Fonts

Food Labeler prints in **DejaVu Sans** unless you choose other lettering
(**Lettering ▾** above the form). Every label has two choices:

- **Name of the food** (on a date sticker: the lot number; on free text: your
  words) — any font.
- **Everything else** — only the easy-to-read fonts marked *readable* below.

The wording the law asks for — ingredients, allergens, net weight, business
name and address, phone/email, permit number, your state's statements and
the cross-contact notice — is always drawn in a readable sans font, whatever
the label file says (`lettering.apply()`; tested in `tests/test_fonts.py`).

Script and display fonts look smaller than DejaVu Sans at the same size and
break up sooner on a 203 dpi printer, so each font has a *minimum size
factor*: the label's smallest allowed size is multiplied by it, and the
automatic shrinking stops there. If the words don't fit at that size, the
usual "too much writing" message appears instead.

## Bundled fonts

All bundled fonts are unmodified files from Google's public font repository,
[github.com/google/fonts](https://github.com/google/fonts), at commit
`06bfe0d62a98375cb09c942fa18e68bd32cff057` (2026-11-20). Each family's
license file sits next to its fonts in `food_labeler/fonts/<folder>/`.

| font | used for | min. size factor | license | files (size) | source path in google/fonts |
|------|----------|------------------|---------|--------------|------------------------------|
| DejaVu Sans (default) | everything (readable) | 1.0 | Bitstream Vera / DejaVu (`LICENSE-DejaVu.txt`) | `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf` (1.4 MB) | not from google/fonts: [dejavu-fonts.github.io](https://dejavu-fonts.github.io/) |
| Atkinson Hyperlegible | everything (readable) | 1.1 | SIL OFL 1.1 | Regular + Bold static (107 kB) | [`ofl/atkinsonhyperlegible/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/atkinsonhyperlegible) `AtkinsonHyperlegible-Regular.ttf`, `AtkinsonHyperlegible-Bold.ttf`, `OFL.txt` |
| Roboto | everything (readable) | 1.05 | SIL OFL 1.1 | variable, weight axis (477 kB) | [`ofl/roboto/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/roboto) `Roboto[wdth,wght].ttf`, `OFL.txt` |
| Open Sans | everything (readable) | 1.0 | SIL OFL 1.1 | variable, weight axis (520 kB) | [`ofl/opensans/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/opensans) `OpenSans[wdth,wght].ttf`, `OFL.txt` |
| Lato | everything (readable) | 1.08 | SIL OFL 1.1 | Regular + Bold static (1.3 MB) | [`ofl/lato/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/lato) `Lato-Regular.ttf`, `Lato-Bold.ttf`, `OFL.txt` |
| Playfair Display | name of the food | 1.15 | SIL OFL 1.1 | variable, weight axis (294 kB) | [`ofl/playfairdisplay/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/playfairdisplay) `PlayfairDisplay[wght].ttf`, `OFL.txt` |
| Pacifico | name of the food | 1.4 | SIL OFL 1.1 | Regular only (322 kB) | [`ofl/pacifico/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/pacifico) `Pacifico-Regular.ttf`, `OFL.txt` |
| Lobster | name of the food | 1.3 | SIL OFL 1.1 | Regular only (397 kB) | [`ofl/lobster/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/lobster) `Lobster-Regular.ttf`, `OFL.txt` |
| Caveat | name of the food | 1.6 | SIL OFL 1.1 | variable, weight axis (394 kB) | [`ofl/caveat/`](https://github.com/google/fonts/tree/06bfe0d62a98375cb09c942fa18e68bd32cff057/ofl/caveat) `Caveat[wght].ttf`, `OFL.txt` |

The fonts added in 1.2.0 come to about 3.7 MB. Google's repository only has
variable versions of Roboto, Open Sans, Playfair Display and Caveat, so those
ship as the variable file and bold is drawn from the weight axis (700) with
Pillow (`lettering.set_weight`). Pacifico and Lobster have no bold; bold
text in them uses the regular style. Some of these licenses list a Reserved
Font Name; that is fine because the files are shipped unmodified.

`docs/samples/fonts-contact-sheet.png` shows each bundled font on a sample
label (`python tools/render_samples.py --fonts`).

## Fonts you add

**Get more fonts…** (in the font list for the name of the food) fetches a
family from Google Fonts by name. No account or key is used:

1. The family name becomes the repository folder name: lower case, letters
   and digits only (*Dancing Script* → `dancingscript`).
2. `METADATA.pb` is read from
   `https://raw.githubusercontent.com/google/fonts/main/<license>/<folder>/`
   for `ofl`, then `apache`, then `ufl`. If none exists: *"Couldn't find a
   font called … Check the spelling on fonts.google.com"*.
3. The regular (weight 400) and bold (700) normal styles are taken from it;
   a family that only comes as a variable font gets that one file. If the
   metadata lists no files, the folder is listed with the GitHub contents
   API (`api.github.com`, unauthenticated, limited per hour: when the limit
   is hit the user is told to try again later).
4. The license file (`OFL.txt`, `LICENSE.txt` or `UFL.txt`) is fetched too.

Every download is https only, only from `github.com`,
`raw.githubusercontent.com` and `api.github.com` (redirects included), has a
time-out, is at most 5 MB, and must be a TrueType/OpenType font that Pillow
can open. The user sees a preview before **Add this font**. Without internet
the window just says getting fonts needs the internet; everything else
works offline.

**Add a font file from my computer…** takes a `.ttf` or `.otf` file, with the
same checks and preview.

Added fonts are kept in the data folder, `fonts/<folder>/` (font files,
license and a `font.json` description), next to the user's other files, so
updates never remove them. They are offered for the name of the food only,
with a minimum size factor worked out from the font's x-height and its
Google Fonts category. **Remove** deletes the folder.

A label that uses a font the computer doesn't have is drawn in DejaVu Sans,
and opening it says so: *"This label used the font X, which isn't on this
computer — showing it in the standard lettering. Get the font?"* The choice
stays in the file, so the font comes back once it is added.

## In the `.label` file

```json
{"app": "easy-labels", "version": 1, "template": "simple", "stock": "large",
 "fields": {...}, "copies": 1,
 "lettering": {"name": "Pacifico", "other": "Lato"}}
```

`lettering` is optional and written only when it isn't the standard look,
so labels in the standard lettering are exactly what earlier versions wrote,
and earlier versions simply ignore the key. The format version is still 1.
