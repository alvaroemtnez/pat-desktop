#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Pat Desktop AppImage (x86_64).
#
# The AppImage bundles Pat and the wrapper but uses the system's Python,
# GTK 4, libadwaita and WebKitGTK. Pat and libax25 are taken from the same pins
# as the Flatpak manifest, so both formats ship the same Pat.
#
# Requires: go (>= the version in Pat's go.mod), gcc, make, git, curl.
# The glibc of the build machine is the minimum glibc of the result, so CI
# builds in Debian 12 (glibc 2.36).
#
# Usage: tools/build-appimage.sh [OUTPUT_DIR]   (default: dist/)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)

APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

APP_ID=$(sed -n 's/^APP_ID = "\(.*\)"$/\1/p' "$ROOT/pat_desktop/__init__.py")
VERSION=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$ROOT/pat_desktop/__init__.py")
MANIFEST="$ROOT/build-aux/flatpak/$APP_ID.yml"

# The value of KEY on the first line matching it after the line matching AFTER.
manifest_value() {
	sed -n "\\#$1#,\$ { s#^ *$2: *##p }" "$MANIFEST" | head -n 1
}
PAT_URL=https://github.com/la5nta/pat.git
PAT_TAG=$(manifest_value "url: $PAT_URL" tag)
PAT_COMMIT=$(manifest_value "url: $PAT_URL" commit)
AX25_URL=$(manifest_value "name: libax25" url)
AX25_SHA256=$(manifest_value "name: libax25" sha256)
for v in APP_ID VERSION PAT_TAG PAT_COMMIT AX25_URL AX25_SHA256; do
	eval "[ -n \"\$$v\" ]" || { echo "could not determine $v" >&2; exit 1; }
done

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

fetch() { # URL SHA256 DEST
	curl -fsSL -o "$3" "$1"
	echo "$2  $3" | sha256sum -c --quiet - || { echo "checksum mismatch: $1" >&2; exit 1; }
}

echo "==> libax25"
fetch "$AX25_URL" "$AX25_SHA256" "$WORK/libax25.tar.gz"
mkdir "$WORK/libax25"
tar -xzf "$WORK/libax25.tar.gz" -C "$WORK/libax25" --strip-components=1
(
	cd "$WORK/libax25"
	./configure -q --sysconfdir=/etc --localstatedir=/var --enable-static --disable-shared CFLAGS="-O2 -fPIC" >/dev/null
	make -s >/dev/null 2>&1
)

echo "==> Pat $PAT_TAG"
git -c advice.detachedHead=false clone -q --depth 1 --branch "$PAT_TAG" "$PAT_URL" "$WORK/pat"
ACTUAL=$(git -C "$WORK/pat" rev-parse HEAD)
[ "$ACTUAL" = "$PAT_COMMIT" ] || { echo "$PAT_TAG is $ACTUAL, expected $PAT_COMMIT" >&2; exit 1; }
(
	cd "$WORK/pat"
	# Modules are verified against Pat's go.sum.
	GOFLAGS="-mod=readonly -trimpath" GOTOOLCHAIN=local CGO_ENABLED=1 \
	CGO_CFLAGS="-I$WORK/libax25" CGO_LDFLAGS="$WORK/libax25/.libs/libax25.a" \
		go build -tags 'libax25 static' -ldflags '-s -w' -o pat .
)

echo "==> AppDir"
APPDIR="$WORK/AppDir"
"$ROOT/install.sh" "$APPDIR/usr"
rm "$APPDIR/usr/bin/pat-desktop" # AppRun replaces the prefix-bound launcher
install -m755 "$WORK/pat/pat" "$APPDIR/usr/bin/pat"
install -Dm644 "$WORK/pat/LICENSE" "$APPDIR/usr/share/licenses/$APP_ID/pat/LICENSE"
install -Dm644 "$WORK/pat/web/dist/static/LICENSES.md" "$APPDIR/usr/share/licenses/$APP_ID/pat/web-LICENSES.md"
install -Dm644 "$WORK/libax25/COPYING" "$APPDIR/usr/share/licenses/$APP_ID/libax25/COPYING"
install -Dm644 "$ROOT/LICENSE" "$APPDIR/usr/share/licenses/$APP_ID/pat-desktop/LICENSE"
install -m755 "$ROOT/build-aux/appimage/AppRun" "$APPDIR/AppRun"
cp "$ROOT/data/$APP_ID.desktop" "$APPDIR/"
cp "$ROOT/data/icons/$APP_ID-256.png" "$APPDIR/$APP_ID.png"
ln -s "$APP_ID.png" "$APPDIR/.DirIcon"

echo "==> AppImage"
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" "$WORK/appimagetool"
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" "$WORK/runtime"
chmod +x "$WORK/appimagetool"
TARGET="$OUT/Pat_Desktop-$VERSION-x86_64.AppImage"
# Extract-and-run: build containers usually have no FUSE.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$WORK/appimagetool" --no-appstream \
	--runtime-file "$WORK/runtime" "$APPDIR" "$TARGET" >/dev/null
echo "Built $TARGET"
