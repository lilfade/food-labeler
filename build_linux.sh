#!/usr/bin/env bash
# Build the Linux one-file program: dist/food-labeler
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt pyinstaller pytest
.venv/bin/python -m pytest -q
.venv/bin/python -m PyInstaller --noconfirm --clean food_labeler.spec
./dist/food-labeler --selftest
echo
echo "Built dist/food-labeler"
echo "To add it to the applications menu:  ./packaging/install_linux.sh"
