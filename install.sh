#!/usr/bin/env bash
# per-user install: launcher on PATH, app-grid entry and icon. no root needed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$here/bin/mosaic" ~/.local/bin/mosaic
# absolute Exec: GNOME's session PATH doesn't always include ~/.local/bin
sed "s#^Exec=mosaic#Exec=$HOME/.local/bin/mosaic#" "$here/data/io.github.iamzainrizwan.mosaic.desktop" \
  > ~/.local/share/applications/io.github.iamzainrizwan.mosaic.desktop
cp "$here/data/io.github.iamzainrizwan.mosaic.svg" ~/.local/share/icons/hicolor/scalable/apps/
if command -v rsvg-convert >/dev/null; then  # pngs too, for anything that skips svg
  for s in 32 48 64 128 256; do
    mkdir -p ~/.local/share/icons/hicolor/${s}x${s}/apps
    rsvg-convert -w $s -h $s "$here/data/io.github.iamzainrizwan.mosaic.svg" \
      -o ~/.local/share/icons/hicolor/${s}x${s}/apps/io.github.iamzainrizwan.mosaic.png
  done
fi
touch ~/.local/share/icons/hicolor  # nudge the icon theme to rescan
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
