#!/usr/bin/env bash
# per-user install: launcher on PATH, app-grid entry and icon. no root needed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$here/bin/mosaic" ~/.local/bin/mosaic
cp "$here/data/io.github.iamzainrizwan.mosaic.desktop" ~/.local/share/applications/
cp "$here/data/io.github.iamzainrizwan.mosaic.svg" ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "installed: run 'mosaic' or find it in the app grid"
