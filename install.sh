#!/usr/bin/env bash
# per-user install: launcher on PATH, app-grid entry and icon. no root needed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$here/bin/mosaic" ~/.local/bin/mosaic
cp "$here/data/io.github.iamzainrizwan.mosaic.desktop" ~/.local/share/applications/
cp "$here/data/io.github.iamzainrizwan.mosaic.svg" ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications 2>/dev/null || true

# shell extension that lets mosaic name captured windows (GNOME only)
ext=mosaic-windows@iamzainrizwan.github.io
if command -v gnome-extensions >/dev/null; then
  mkdir -p ~/.local/share/gnome-shell/extensions
  ln -sfn "$here/extension/$ext" ~/.local/share/gnome-shell/extensions/$ext
  if gnome-extensions enable "$ext" 2>/dev/null; then
    echo "window-naming extension enabled"
  else
    echo "window-naming extension installed: log out and back in once, then run ./install.sh again to enable it"
  fi
fi
echo "installed: run 'mosaic' or find it in the app grid"
