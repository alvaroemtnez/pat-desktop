# Changelog

All notable changes to Pat Desktop are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Each release notes the Pat version
it bundles.

## [Unreleased]

### Added

- Bundled modems, started with Pat from *Menu → Modems*: ardopcf 1.0.4.1.3 (ARDOP), xara 0.1.3 with every mode (VARA HF and FM), Mercury 1.9.23 (VARA HF interface), Direwolf 1.8.1 (packet, AGWPE) and Hamlib 4.7.2's rigctld (rig control). Each listens where Pat's configuration expects it, with the sound card and PTT chosen in the dialog.
- Flatpak and AppImage builds for aarch64 (64-bit ARM).
- AppImage delta updates through Gear Lever or AppImageUpdate (`.zsync` files in each release).
- Signed checksums: `SHA256SUMS.asc` (see docs/verifying.md).

### Changed

- Update Pat to v1.0.1.
- The Flatpak can use the sound server, for the modems' "System default" sound card.
- The log window shows the modems' output too.

### Fixed

- The page's scrollbar starts below Pat's top bar instead of running up next to the window buttons.
- The menu and window buttons are centred on Pat's top bar; they sat a few pixels too high.
- The About dialog and the software centre listing name the developer.

## [0.1.0] - 2026-10-23

First release, bundling Pat 1.0.0.

### Added

- Desktop window for Pat that starts and stops Pat automatically, with no terminal or browser needed.
- Pat's own top bar doubles as the title bar: the menu and window buttons sit at its right end, and its empty space drags the window.
- First launch opens Pat's configuration for callsign, radio and modems. It is also available from the menu.
- Winlink forms open in their own windows. Attachments are saved with the file dialog, and external links open in the browser.
- Dark mode that follows the desktop setting, in GNOME's dark colours. Winlink forms keep their own look.
- Desktop notifications for Pat's alerts.
- Live log viewer and a Restart Pat action.
- Confirmation before quitting during an active Winlink session.
- Flatpak bundle and AppImage builds.
