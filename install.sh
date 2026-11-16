#!/bin/sh
# Installs owui-pop for this user with pipx (or pip --user), plus its menu entry.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$here"
else
  echo "pipx not found; using pip --user (pipx is recommended)"
  python3 -m pip install --user --upgrade "$here"
fi
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
cp "$here/data/owui-pop.desktop" "$apps/owui-pop.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" || true
echo
echo "Installed. Run 'owui-pop' (Settings opens on first run), then bind it to a key in your"
echo "desktop's keyboard shortcuts. KDE: System Settings > Shortcuts > Add New > Command."
