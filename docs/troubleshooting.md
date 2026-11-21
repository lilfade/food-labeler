# Something not right?

[← Back to the start](../README.md)

**The labels come out as a black block, or blank.**
Go to **Settings → Advanced…**, tick **Invert colours**, and press **Save**.
Some printers use the opposite colours; this switch fixes that.

**A picture prints with black and white swapped.**
Press **Picture → Change…** and check **Swap black and white** is off: while
it is on, the window says *Black and white are swapped*. The picture on the
right of the main window is exactly what prints, so if it looks right there
but not on paper, the whole label is swapped: see the entry above.

**My picture won't open.**
Food Labeler opens PNG, JPG, GIF, BMP, WebP, TIFF and ICO pictures. iPhone
photos (HEIC) and SVG drawings can't be opened yet: open them in a photo or
drawing program and save them as PNG or JPG first.

**The printing is too pale or too dark.**
Press **Print settings…** (under the printer list) and move *Darkness*
towards *Darker* or *Lighter*, then **Save**. Not sure which is best? Press
**Darkness test**. More in [Print settings](printer.md#print-settings).

**The printing is not in the middle of the label, or comes out upside down.**
**Print settings…** → *Nudge the print* moves it left, right, up or down;
*Print upside down* turns it round.

**Labels print across the gap, or the printer skips labels.**
The printer doesn't know where each label starts on this roll. Set up the
roll: **Print settings…** → **New roll? Set it up…** (see
[New roll? Set it up](printer.md#new-roll-set-it-up)). Check the label size
and the kind of roll match what is in the printer.

**My printer isn't found.**
Check it is switched on and plugged in, then press **Look for printers
again**. Still nothing? Follow
[My printer isn't in the list](printer.md#my-printer-isnt-in-the-list):
it finds the printer when you plug it back in, or makes a short report and
opens a help form on GitHub where you paste it, and we'll try to help.

**My network printer isn't answering.**
Check the printer and its print server or network bridge are switched on and
on the same network as the computer. **My printers… → Add a network
printer…** lists it with its address; type the address again and press **Test
the connection** to check it (nothing is printed). See
[Network printers](printer.md#network-printers).

**On Windows, nothing prints but there is no error.**
**Settings → Advanced…** → tick **Print through Windows driver** → **Save**.

**The writing doesn't fit.**
A message tells you which part is too long. Use shorter words or a bigger
label (**Label size → Change…**).

**Windows says "Windows protected your PC".**
That is normal for a new download. Click **More info**, then **Run anyway**.
See [First time on Windows](guide.md#first-time-on-windows).

**Something else went wrong.**
Food Labeler keeps a log for your helper: *Settings → Advanced… → Open log
folder*, file `food-labeler.log`.

**Still stuck?** [Open an issue on GitHub](https://github.com/lilfade/food-labeler/issues/new/choose): pick what's
wrong and fill in the boxes, and we'll try to help. It's free to make a
GitHub account; or, if you're stuck, email hello@highthymekitchen.com.
