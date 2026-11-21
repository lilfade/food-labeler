"""Food Labeler — make and print food labels, by High Thyme Kitchen.

Package layout (see docs/ARCHITECTURE.md for the full picture):

    model      the label document (what the user typed) and the .label file format
    templates  turns a document into text blocks and fits them on the label
    lettering  the fonts a label can use (bundled + the user's), min sizes, legal text
    fontget    "Get more fonts": Google Fonts from GitHub, or a font file
    render     draws the fitted layout as the exact 1-bit picture that prints
    tspl, zpl  turn that picture into a job in the printer's own language
    printers   finds printers and sends jobs to them
    known      printer models we recognise (known_printers.json + user updates)
    calibrate  setting up a new roll: jobs, the line-up label, the "New roll?" notice
    cottage    cottage food state rules, the user's own edits, the Label check
    bakery     My bakery details, My ingredients, My products
    app, dialogs, widgets   the Tk user interface

``__version__`` below is the single source of truth for the version number:
the About section in Settings, the printer report, ``--version``, the
PyInstaller Windows version resource and the release workflow all read it.
"""

APP_NAME = "Food Labeler"
APP_ID = "food-labeler"
BRAND = "High Thyme Kitchen"
__version__ = "1.3.0"
