# Using Food Labeler

[← Back to the start](../README.md)

Food Labeler makes clear, big-print labels for home-made food and prints
them on a small thermal label printer. What you see on the screen is exactly
what comes out of the printer.

- [First time on Windows](#first-time-on-windows)
- [Making a label](#making-a-label)
- [Other things you can do](#other-things-you-can-do)
- [Lettering](#lettering)
- [Pictures](#pictures)
- [QR codes](#qr-codes)
- [For home bakers (cottage food labels)](#for-home-bakers-cottage-food-labels)
- [Licenses and branding](#licenses-and-branding)

Printer help is in [Your printer](printer.md), and quick fixes are in
[Something not right?](troubleshooting.md).

## First time on Windows

1. **Install the printer's own driver first.** Use the driver from the company
   that made your printer (for LP610BT-type printers: the Labelnize, Polono or
   Flexyva driver; for Zebra: the ZDesigner driver). Plug the printer in with
   its USB cable and switch it on. It should now appear in Windows
   *Settings → Printers*.
2. **Download `FoodLabeler.exe`** from the
   [Releases page](https://github.com/lilfade/food-labeler/releases/latest)
   (on Linux, download `food-labeler`). `SHA256SUMS.txt` on the same page
   lets a helper check the download is intact.
3. **Move it to your Desktop** (drag it from your *Downloads* folder), so it is
   easy to find next time.
4. **Double-click it.**
5. **Windows may show a blue box saying "Windows protected your PC".**
   That is normal for a small program that isn't sold in a shop: Windows has
   simply not seen it many times before. It does not mean anything is wrong.
   - Click the words **More info**.
   - Then click the **Run anyway** button that appears.

   Windows usually asks this only the first time you open a new download.
6. Food Labeler opens. If it finds your printer, its name is shown above the
   **PRINT** button. If not, see [Your printer](printer.md).

## Making a label

1. **Type what the food is** in the big box on the left, for example
   *Chicken Soup*.
2. **Made on** is already today.
3. **Use by**: press one of the quick buttons (*+3 days*, *+5 days*,
   *+1 week*, *+2 weeks*, *+1 month*) or press the date to pick it on a
   calendar.
4. **Contains**: tap any allergens that are in the food (Milk, Eggs, Wheat…).
5. If you like, add a **note** (tap *Keep refrigerated*, *Keep frozen*…) and
   **Made by**.
6. **Look at the picture on the right.** That is exactly what will print.
7. Choose **how many labels** with the big **−** and **+** buttons.
8. Press **PRINT**.

If the writing doesn't fit, a message tells you which part is too long.
Use shorter words or a bigger label.

## Other things you can do

![Choosing the kind of label](screenshot-templates.png)

- **Kind of label → Change…**: *Simple food label*, *Package label* (with
  ingredients and your kitchen's name and address), *Date sticker*,
  *Free text*, *Picture label* (one big picture), or *Cottage food label*
  (for home bakers, see [below](#for-home-bakers-cottage-food-labels)).
- **Label size → Change…**: pick the size of the labels in your printer.
- **Save** keeps the label so you can print it again. Saved labels appear
  under **My saved labels** at the top: one click opens them. When you open
  an old label, Food Labeler asks if the dates should change to today.
- **Undo** takes back the last change.
- **A−** and **A+** make all the writing on the screen smaller or bigger.
- **Save as picture** makes a picture of the label to send to someone.
- Your work is kept safe automatically, even if the computer switches off.
- Your saved labels are in `Documents\My Food Labels` (Linux:
  `~/Documents/My Food Labels`). Updates to Food Labeler never change them.

## Lettering

![A label with a fancy name in Pacifico](screenshot-fancy-name.png)

- **Lettering → Change…** (under *Label size*) lets you pick the kind of
  letters on your label: one for the **name of the food** and one for
  **everything else**. Each choice is shown in its own lettering, so you can
  see what you get. Food Labeler remembers your choice for your next label.
- For the name you can pick fancy lettering such as *Pacifico* or *Caveat*.
  Everything else uses only clear, easy-to-read lettering, and the wording
  the law asks for (ingredients, allergens, your address, your state's
  wording) always stays easy to read.
- **Get more fonts…** (in the list of lettering) can fetch any font from
  [fonts.google.com](https://fonts.google.com): type its name, for example
  *Dancing Script*, look at it, and press **Add this font**. This is the only
  part of Food Labeler that uses the internet, and you never need it.
  **Add a font file from my computer…** adds a font you already have.
- If you open a label made on another computer with a font you don't have,
  Food Labeler shows it in the standard lettering and offers to get the font.

<p>
<img src="screenshot-lettering.png" alt="Choosing the lettering" width="32%">
<img src="screenshot-font-picker.png" alt="The list of lettering" width="32%">
<img src="screenshot-get-fonts.png" alt="Getting a font from Google Fonts" width="32%">
</p>

Details for helpers: [fonts.md](fonts.md).

## Pictures

![A label with a logo and a QR code](screenshot-picture-qr.png)

- **Picture → Add a picture…** puts your logo (or any picture) on the label:
  above the name, on the left or right side, or in the top-left corner, as
  big as you like. Thermal printers only print black, so you choose how it
  turns black and white: *Logo / drawing (solid black)* with a *Lighter ↔
  Darker* slider, or *Photo (tiny dots)*. The picture on the right is exactly
  what prints. **Keep in My pictures** makes your logo one click next time.
  The picture is saved inside the label file. If there isn't room, the
  writing your state asks for keeps its size and the picture gets smaller.
- **Kind of label → Picture label** is one big picture (a logo sticker or a
  round seal) with a line of words under it if you want.

![Adding a picture](screenshot-picture.png)

## QR codes

**QR code → Add a QR code…** adds a code people can scan with their
phone: your website, your phone number, your email, or some text (for
example how to reheat it), with words under it like *Scan for our menu*.
What the code holds is shown in small print under the label picture. If
the code would be too small to scan, Food Labeler says so instead of
printing it.

![Adding a QR code](screenshot-qr.png)

## For home bakers (cottage food labels)

If you bake at home and sell under your state's *cottage food* law, choose
**Kind of label → Cottage food label**.

![A cottage food label for a Nebraska bakery](screenshot-cottage.png)

This is what that label prints (4 × 2 inch):

![Printed cottage food label example](samples/cottage_NE_large.png)

1. **Set up my bakery** (Food Labeler offers this the first time):
   pick your state, then type your bakery's name, full address (street,
   city, state and ZIP), phone, email and permit number if you have one.
   You can change these any time in **Settings → My bakery**.

   ![Set up my bakery: pick your state](screenshot-bakery-setup.png)
2. Fill in the label: product name, net weight (type *8 oz* or *1.5 lb*;
   grams are added when your state asks for them), ingredients, allergens,
   how to store it and the dates.
3. **Build from My ingredients…** lets you pick ingredients in order,
   heaviest first. Each one remembers what's in it ("Butter (cream, salt)")
   and its allergens, so **Contains** fills itself in. The starter list is
   only an example: check each ingredient against your own package and
   press **Change…** to match it.

   ![Building the ingredient list](screenshot-ingredients.png)
4. **Save to My products** keeps the product so next time **Choose from
   My products…** fills the whole label in one click.
5. The **Label check** at the top of the form says in green when everything
   your state asks for is on the label, or lists in red what is missing.
   **About (your state)'s rules…** shows the full list and where the rules
   come from. If something is missing, **PRINT** asks before printing.

   ![Label check showing a missing item](screenshot-cottage-check.png)
6. Your state's required wording is printed at the size your state asks
   for. If it doesn't all fit, Food Labeler says so and suggests a bigger
   label; it never makes the required wording smaller or leaves it out.

![My bakery: your state, its source and your kitchen details](screenshot-my-bakery.png)

**Your own wording is kept.** In **Settings → My bakery** you can change
the wording and the list of what must be on the label. Your changes are
marked *edited by you* and have a **Reset to state default** button. New
versions of Food Labeler never overwrite them; if your state's suggestion
changes, Food Labeler asks once whether to keep yours or use the new one.

> These are suggestions from public state guidance. You are responsible for
> following your state's rules. Each state's source and the date it was
> checked are shown in **My bakery**. States marked *Unverified — check with
> your state* could not be confirmed from an official source.

Details for helpers, including every state's wording and source:
[cottage-rules.md](cottage-rules.md).

## Licenses and branding

Food Labeler is free and open source under the [MIT License](../LICENSE).

Bundled fonts: DejaVu Sans (Bitstream Vera license, see
`food_labeler/fonts/LICENSE-DejaVu.txt`); Atkinson Hyperlegible, Roboto,
Open Sans, Lato, Playfair Display, Pacifico, Lobster and Caveat from Google
Fonts (SIL Open Font License 1.1, each with its `OFL.txt` in
`food_labeler/fonts/`; sources in [fonts.md](fonts.md)). The seal artwork in `assets/`
uses the Parisienne typeface (SIL Open Font License 1.1). The High Thyme
Kitchen name and seal are the kitchen's branding and are not covered by the
MIT License; if you publish your own version, please use your own name and
logo.
