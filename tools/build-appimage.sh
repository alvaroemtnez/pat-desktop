#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Pat Desktop AppImage for this machine's architecture (x86_64, or
# aarch64 in an arm64 container), with its .zsync file for delta updates.
#
# The AppImage bundles Pat, the modems (ardopcf, Direwolf, Mercury, xara) and
# Hamlib's rigctld, and the wrapper; it uses the system's Python, GTK 4,
# libadwaita and WebKitGTK, and its sound (ALSA, PulseAudio), USB and udev
# libraries. Every component is taken from the same pins as the Flatpak
# manifest, so both formats ship the same versions.
#
# Requires: go (>= the version in Pat's go.mod), gcc, make, cmake, ninja, git,
# curl, pkg-config, zsync, and the development files of ALSA, PulseAudio,
# libusb and libudev. The Rust toolchain is fetched (pinned below). The glibc
# of the build machine is the minimum glibc of the result, so CI builds in
# Debian 12 (glibc 2.36).
#
# Usage: tools/build-appimage.sh [OUTPUT_DIR]   (default: dist/)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)
ARCH=$(uname -m)
JOBS=$(nproc)

case "$ARCH" in
x86_64)
	APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
	RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
	RUSTUP_SHA256=20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c
	;;
aarch64)
	APPIMAGETOOL_SHA256=f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158
	RUNTIME_SHA256=00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444
	RUSTUP_SHA256=e3853c5a252fca15252d07cb23a1bdd9377a8c6f3efa01531109281ae47f841c
	;;
*) echo "unsupported architecture $ARCH" >&2; exit 1 ;;
esac
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-$ARCH.AppImage
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-$ARCH
# rustup verifies the toolchain it installs against the release's checksums.
RUSTUP_URL=https://static.rust-lang.org/rustup/archive/1.28.2/$ARCH-unknown-linux-gnu/rustup-init
RUST_VERSION=1.99.0

APP_ID=$(sed -n 's/^APP_ID = "\(.*\)"$/\1/p' "$ROOT/pat_desktop/__init__.py")
VERSION=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$ROOT/pat_desktop/__init__.py")
MANIFEST="$ROOT/build-aux/flatpak/$APP_ID.yml"
# Gear Lever, AppImageUpdate and other updaters read this, and fetch the
# .zsync of GitHub's latest release, written beside the AppImage.
UPDATE_INFO="gh-releases-zsync|alvaroemtnez|pat-desktop|latest|Pat_Desktop-*-$ARCH.AppImage.zsync"

# The value of KEY on the first line matching it after the line matching AFTER.
manifest_value() {
	sed -n "\\#$1#,\$ { s#^ *$2: *##p }" "$MANIFEST" | head -n 1
}
PAT_URL=https://github.com/la5nta/pat.git
PAT_TAG=$(manifest_value "url: $PAT_URL" tag)
PAT_COMMIT=$(manifest_value "url: $PAT_URL" commit)
AX25_URL=$(manifest_value "name: libax25" url)
AX25_SHA256=$(manifest_value "name: libax25" sha256)
HAMLIB_URL=$(manifest_value "name: hamlib" url)
HAMLIB_SHA256=$(manifest_value "name: hamlib" sha256)
for v in APP_ID VERSION PAT_TAG PAT_COMMIT AX25_URL AX25_SHA256 HAMLIB_URL HAMLIB_SHA256; do
	eval "[ -n \"\$$v\" ]" || { echo "could not determine $v" >&2; exit 1; }
done

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
APPDIR="$WORK/AppDir"
LICENSES="$APPDIR/usr/share/licenses/$APP_ID"

# Run a noisy build step, showing its output only if it fails.
quiet() {
	"$@" > "$WORK/step.log" 2>&1 || { cat "$WORK/step.log" >&2; echo "failed: $*" >&2; exit 1; }
}

fetch() { # URL SHA256 DEST
	curl -fsSL -o "$3" "$1"
	echo "$2  $3" | sha256sum -c --quiet - || { echo "checksum mismatch: $1" >&2; exit 1; }
}

# Clone the manifest's pin of module NAME (tag and commit) into DIR.
checkout() { # NAME DIR
	url=$(manifest_value "name: $1" url)
	tag=$(manifest_value "name: $1" tag)
	commit=$(manifest_value "name: $1" commit)
	[ -n "$url" ] && [ -n "$tag" ] && [ -n "$commit" ] || { echo "no pin for $1" >&2; exit 1; }
	echo "==> $1 $tag"
	git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" "$url" "$2"
	actual=$(git -C "$2" rev-parse HEAD)
	[ "$actual" = "$commit" ] || { echo "$1 $tag is $actual, expected $commit" >&2; exit 1; }
}

echo "==> libax25"
fetch "$AX25_URL" "$AX25_SHA256" "$WORK/libax25.tar.gz"
mkdir "$WORK/libax25"
tar -xzf "$WORK/libax25.tar.gz" -C "$WORK/libax25" --strip-components=1
(
	cd "$WORK/libax25"
	# The bundled config.guess predates aarch64.
	for f in config.guess config.sub; do
		cp -f "$(ls /usr/share/misc/$f /usr/share/automake-*/$f 2>/dev/null | head -n 1)" . || true
	done
	quiet ./configure --sysconfdir=/etc --localstatedir=/var --enable-static --disable-shared CFLAGS="-O2 -fPIC"
	quiet make
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
"$ROOT/install.sh" "$APPDIR/usr"
rm "$APPDIR/usr/bin/pat-desktop" # AppRun replaces the prefix-bound launcher
install -m755 "$WORK/pat/pat" "$APPDIR/usr/bin/pat"
install -Dm644 "$WORK/pat/LICENSE" "$LICENSES/pat/LICENSE"
install -Dm644 "$WORK/pat/web/dist/static/LICENSES.md" "$LICENSES/pat/web-LICENSES.md"
install -Dm644 "$WORK/libax25/COPYING" "$LICENSES/libax25/COPYING"
install -Dm644 "$ROOT/LICENSE" "$LICENSES/pat-desktop/LICENSE"

echo "==> Hamlib"
fetch "$HAMLIB_URL" "$HAMLIB_SHA256" "$WORK/hamlib.tar.gz"
mkdir "$WORK/hamlib" "$WORK/prefix"
tar -xzf "$WORK/hamlib.tar.gz" -C "$WORK/hamlib" --strip-components=1
(
	cd "$WORK/hamlib"
	quiet ./configure --prefix="$WORK/prefix" --disable-static --without-cxx-binding \
		--without-perl-binding --without-python-binding --without-tcl-binding \
		--without-lua-binding --without-readline --without-indi --without-xml-support
	quiet make -j"$JOBS"
	quiet make install
	install -Dm644 COPYING.LIB "$LICENSES/hamlib/COPYING.LIB"
	install -Dm644 COPYING "$LICENSES/hamlib/COPYING"
)
install -m755 "$WORK/prefix/bin/rigctld" "$APPDIR/usr/bin/rigctld"
mkdir -p "$APPDIR/usr/lib"
# The modems are started with usr/lib on LD_LIBRARY_PATH (pat_desktop/modems.py).
cp -P "$WORK/prefix/lib"/libhamlib.so* "$APPDIR/usr/lib/"
export PKG_CONFIG_PATH="$WORK/prefix/lib/pkgconfig"

checkout ardopcf "$WORK/ardopcf"
(
	cd "$WORK/ardopcf"
	# As in the manifest: built as the compilers of its release did.
	quiet make -j"$JOBS" CC="gcc -std=gnu17 -fpermissive" ardopcf
	install -m755 ardopcf "$APPDIR/usr/bin/ardopcf"
	install -Dm644 LICENSE "$LICENSES/ardopcf/LICENSE"
	install -Dm644 lib/hid/LICENSE-orig.txt "$LICENSES/ardopcf/hidapi-LICENSE-orig.txt"
	install -Dm644 lib/rockliff/rrs.txt "$LICENSES/ardopcf/rockliff-rrs.txt"
	install -Dm644 lib/zf_log/LICENSE "$LICENSES/ardopcf/zf_log-LICENSE"
)

checkout direwolf "$WORK/direwolf"
(
	cd "$WORK/direwolf"
	quiet cmake -B _build -G Ninja -DCMAKE_BUILD_TYPE=Release -DUNITTEST=OFF -DOPTIONAL_DNSSD=OFF \
		-DCMAKE_PREFIX_PATH="$WORK/prefix"
	quiet cmake --build _build --target direwolf
	install -m755 _build/src/direwolf "$APPDIR/usr/bin/direwolf"
	install -Dm644 LICENSE "$LICENSES/direwolf/LICENSE"
	install -Dm644 external/LICENSE "$LICENSES/direwolf/external-LICENSE"
)

checkout mercury "$WORK/mercury"
(
	cd "$WORK/mercury"
	quiet make -j"$JOBS"
	install -m755 mercury "$APPDIR/usr/bin/mercury"
	install -Dm644 LICENSE "$LICENSES/mercury/LICENSE"
	install -Dm644 LICENSE-freedv "$LICENSES/mercury/LICENSE-freedv"
)

checkout xara "$WORK/xara"
echo "==> Rust $RUST_VERSION"
fetch "$RUSTUP_URL" "$RUSTUP_SHA256" "$WORK/rustup-init"
chmod +x "$WORK/rustup-init"
export RUSTUP_HOME="$WORK/rustup" CARGO_HOME="$WORK/cargo"
quiet "$WORK/rustup-init" -y --no-modify-path --profile minimal --default-toolchain "$RUST_VERSION"
(
	cd "$WORK/xara"
	# Every mode ("registered"); the crates are checked against Cargo.lock.
	"$CARGO_HOME/bin/cargo" build -q --release --locked -p xara --features registered
	install -m755 target/release/xara "$APPDIR/usr/bin/xara"
	install -Dm644 LICENSE "$LICENSES/xara/LICENSE"
	# The crates linked into it (MIT, Apache-2.0, Zlib or 0BSD).
	for c in "$CARGO_HOME"/registry/src/*/*/; do
		for f in "$c"LICENSE* "$c"COPYING*; do
			[ ! -f "$f" ] || install -Dm644 "$f" "$LICENSES/xara/crates/$(basename "$c")/$(basename "$f")"
		done
	done
)

install -m755 "$ROOT/build-aux/appimage/AppRun" "$APPDIR/AppRun"
cp "$ROOT/data/$APP_ID.desktop" "$APPDIR/"
cp "$ROOT/data/icons/$APP_ID-256.png" "$APPDIR/$APP_ID.png"
ln -s "$APP_ID.png" "$APPDIR/.DirIcon"

echo "==> AppImage"
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" "$WORK/appimagetool"
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" "$WORK/runtime"
chmod +x "$WORK/appimagetool"
NAME="Pat_Desktop-$VERSION-$ARCH.AppImage"
# Extract-and-run: build containers usually have no FUSE. The .zsync is
# written to the working directory, and names the AppImage it describes.
(
	cd "$OUT"
	rm -f "$NAME" "$NAME.zsync"
	APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$WORK/appimagetool" --no-appstream \
		--runtime-file "$WORK/runtime" -u "$UPDATE_INFO" "$APPDIR" "$NAME" >/dev/null
	[ -f "$NAME.zsync" ] || { echo "appimagetool wrote no $NAME.zsync (is zsyncmake installed?)" >&2; exit 1; }
)
echo "Built $OUT/$NAME (+ .zsync)"
