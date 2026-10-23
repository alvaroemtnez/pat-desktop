#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Install Pat Desktop into a prefix: ./install.sh /app (Flatpak) or ~/.local
set -eu
PREFIX=${1:?usage: install.sh PREFIX}
APP_ID=io.getpat.desktop
SRC=$(dirname "$0")

install -d "$PREFIX/share/pat-desktop/pat_desktop"
install -m644 "$SRC"/pat_desktop/*.py "$PREFIX/share/pat-desktop/pat_desktop/"

install -d "$PREFIX/bin"
cat > "$PREFIX/bin/pat-desktop" <<LAUNCHER
#!/bin/sh
export PYTHONPATH="$PREFIX/share/pat-desktop\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m pat_desktop "\$@"
LAUNCHER
chmod 755 "$PREFIX/bin/pat-desktop"

install -Dm644 "$SRC/data/$APP_ID.desktop" "$PREFIX/share/applications/$APP_ID.desktop"
install -Dm644 "$SRC/data/$APP_ID.metainfo.xml" "$PREFIX/share/metainfo/$APP_ID.metainfo.xml"
for size in 128 256; do
	install -Dm644 "$SRC/data/icons/$APP_ID-$size.png" \
		"$PREFIX/share/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
done
