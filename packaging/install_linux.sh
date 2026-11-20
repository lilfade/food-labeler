#!/usr/bin/env bash
# Install the built program for the current user (no sudo needed):
#   ~/.local/bin/food-labeler, menu entry and icon.
set -euo pipefail
cd "$(dirname "$0")/.."
install -Dm755 dist/food-labeler "$HOME/.local/bin/food-labeler"
install -Dm644 food_labeler/assets/icon.png "$HOME/.local/share/icons/hicolor/256x256/apps/food-labeler.png"
install -Dm644 food_labeler/assets/icon-48.png "$HOME/.local/share/icons/hicolor/48x48/apps/food-labeler.png"
install -Dm644 packaging/food-labeler.desktop "$HOME/.local/share/applications/food-labeler.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Installed. Look for \"Food Labeler\" in the applications menu."
echo "Printing by USB cable needs your user in the \"lp\" group:  sudo usermod -aG lp \$USER  (then log out and in)."
