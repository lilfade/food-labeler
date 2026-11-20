"""Entry point used by PyInstaller and the .desktop file."""
import sys

from food_labeler.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
