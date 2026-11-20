# PyInstaller spec for Food Labeler (one-file, windowed).
#   Windows:  build_windows.bat   -> dist\FoodLabeler.exe
#   Linux:    ./build_linux.sh    -> dist/food-labeler
# The GitHub release workflow (.github/workflows/release.yml) uses this file too.
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
IS_WIN = sys.platform.startswith("win")


def package_version() -> str:
    """__version__ from food_labeler/__init__.py (read, not imported: the
    package's dependencies need not be importable by the build Python)."""
    text = (ROOT / "food_labeler" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


VERSION = package_version()


def windows_version_info(version: str):
    """The version resource shown in Explorer → Properties → Details."""
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo,
                                                      StringStruct, StringTable,
                                                      VarFileInfo, VarStruct,
                                                      VSVersionInfo)
    nums = tuple(int(x) for x in re.findall(r"\d+", version)[:4])
    nums = (nums + (0, 0, 0, 0))[:4]
    strings = [
        StringStruct("CompanyName", "High Thyme Kitchen"),
        StringStruct("FileDescription", "Food Labeler"),
        StringStruct("FileVersion", version),
        StringStruct("InternalName", "FoodLabeler"),
        StringStruct("OriginalFilename", "FoodLabeler.exe"),
        StringStruct("ProductName", "Food Labeler"),
        StringStruct("ProductVersion", version),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[StringFileInfo([StringTable("040904B0", strings)]),   # US English, Unicode
              VarFileInfo([VarStruct("Translation", [0x0409, 1200])])],
    )


datas = [
    (str(ROOT / "food_labeler" / "fonts"), "food_labeler/fonts"),
    (str(ROOT / "food_labeler" / "assets"), "food_labeler/assets"),
    (str(ROOT / "food_labeler" / "known_printers.json"), "food_labeler"),
    (str(ROOT / "food_labeler" / "app_config.json"), "food_labeler"),
]
hidden = ["PIL._tkinter_finder", "segno"]
if IS_WIN:
    hidden += ["win32print", "win32ui", "win32con", "win32api", "pywintypes"]

a = Analysis(
    [str(ROOT / "food_labeler_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hidden,
    excludes=["numpy", "matplotlib", "pytest", "cairosvg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FoodLabeler" if IS_WIN else "food-labeler",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "food_labeler" / "assets" / "icon.ico") if IS_WIN else None,
    version=windows_version_info(VERSION) if IS_WIN else None,
)
