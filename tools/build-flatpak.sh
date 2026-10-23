#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Pat Desktop Flatpak bundle (single-file .flatpak) for this machine's
# architecture. Uses flatpak-builder if installed, or org.flatpak.Builder
# from Flathub.
#
# Usage: tools/build-flatpak.sh [OUTPUT_DIR]   (default: dist/)
# Extra flatpak-builder options can be passed in FLATPAK_BUILDER_ARGS,
# e.g. FLATPAK_BUILDER_ARGS="--install --user" to also install the result.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)
APP_ID=$(sed -n 's/^APP_ID = "\(.*\)"$/\1/p' "$ROOT/pat_desktop/__init__.py")
VERSION=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$ROOT/pat_desktop/__init__.py")
ARCH=$(flatpak --default-arch)

if command -v flatpak-builder >/dev/null 2>&1; then
	BUILDER=flatpak-builder
else
	BUILDER="flatpak run org.flatpak.Builder"
fi

cd "$ROOT"
# shellcheck disable=SC2086 # word splitting is intended
$BUILDER ${FLATPAK_BUILDER_ARGS:-} --install-deps-from=flathub --force-clean \
	--repo=repo build-dir "build-aux/flatpak/$APP_ID.yml"

TARGET="$OUT/Pat_Desktop-$VERSION-$ARCH.flatpak"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
	repo "$TARGET" "$APP_ID"
echo "Built $TARGET"
