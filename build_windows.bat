@echo off
rem Build FoodLabeler.exe on Windows. Needs Python 3.11+ from python.org
rem (tick "Add python.exe to PATH" when installing it).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || python -m venv .venv || goto :error
)
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller pytest || goto :error
.venv\Scripts\python -m pytest -q || goto :error
.venv\Scripts\python -m PyInstaller --noconfirm --clean food_labeler.spec || goto :error
dist\FoodLabeler.exe --selftest
echo.
echo Built dist\FoodLabeler.exe  -- copy it to the Desktop of the computer that will use it.
goto :eof
:error
echo.
echo Build FAILED. Scroll up to see why.
exit /b 1
