#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Rename the Flatpak application ID everywhere (file names and contents).
# Usage: tools/rename-app-id.sh NEW_ID     e.g. org.example.PatDesktop
set -eu
NEW=${1:?usage: rename-app-id.sh NEW_ID}
cd "$(dirname "$0")/.."
OLD=$(sed -n 's/^APP_ID = "\(.*\)"$/\1/p' pat_desktop/__init__.py)
[ -n "$OLD" ] || { echo "current APP_ID not found" >&2; exit 1; }
[ "$OLD" != "$NEW" ] || { echo "already $NEW"; exit 0; }

git ls-files | while read -r f; do
	case "$f" in *.png) continue ;; esac
	if grep -qF "$OLD" "$f"; then
		sed -i "s/$(printf '%s' "$OLD" | sed 's/\./\\./g')/$NEW/g" "$f"
	fi
done
git ls-files | grep -F "$OLD" | while read -r f; do
	git mv "$f" "$(printf '%s' "$f" | sed "s/$(printf '%s' "$OLD" | sed 's/\./\\./g')/$NEW/g")"
done
echo "Renamed $OLD -> $NEW. Review with: git status && git diff"
