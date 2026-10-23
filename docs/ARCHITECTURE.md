# Architecture

## Decision: build pristine upstream Pat into the app, pinned by tag

Pat Desktop bundles Pat. The Flatpak manifest builds it from the **unmodified
upstream source** at a pinned release tag and commit. Pat is not forked,
mirrored, patched or vendored into this repository. Moving to a new Pat
release changes two lines in the manifest plus a generated dependency list.

### The alternative we rejected: downloading the Pat binary at runtime

The wrapper could download upstream's release tarball (static binaries exist
for `linux_amd64` and `linux_arm64`) into the app's data directory and run it,
with its own updater. It is technically possible, but:

- **Integrity.** Upstream publishes no checksums or signatures for release
  assets. The binary holds Winlink credentials and keys a radio transmitter,
  so running unverified downloads would be a real supply-chain risk.
- **No reproducibility.** Two users on the same Pat Desktop version could run
  different Pat versions, which makes bug reports hard to act on.
- **More code in the wrapper.** It would need an updater, a version checker,
  rollback, and architecture detection.
- **It would rule out Flathub**, which requires building everything from
  source with every input listed in the manifest.

### What we keep from the "untouched core" idea

- Pat is never modified, so `AppName` and `Version` stay as upstream intends.
  Upstream asks forks not to change these, because Winlink tracks client
  versions.
- An update is a reviewable diff: `tag`, `commit` and the Go module list.
- `tools/update-pat.py` and the weekly *Update Pat* workflow find new upstream
  releases and open a pull request automatically. Upstream releases about
  every 3–4 months, so maintenance is merging a bot PR a few times a year.

## Components

| Component | Technology | Notes |
|---|---|---|
| Wrapper | Python 3, PyGObject, GTK 4, libadwaita ≥ 1.5, WebKitGTK 6.0, libsoup 3 | Flatpak: provided by the GNOME runtime. AppImage: taken from the system |
| Pat | Go, `-tags 'libax25 static'` | Same build tags as upstream's Linux release |
| libax25 0.0.12-rc4 | C, static | Same version as upstream's `make.bash`. In the Flatpak, `sysconfdir=/run/host/etc`, so axports is read from the host after an opt-in override |

## Packaging

The Flatpak manifest (`build-aux/flatpak/`) is the single source of truth for
the Pat and libax25 pins. Both formats build from it:

- **Flatpak bundle** (`tools/build-flatpak.sh`): fully self-contained on the
  GNOME runtime, sandboxed, with offline Go module sources. This is the
  recommended format.
- **AppImage** (`tools/build-appimage.sh`): reads the same pins from the
  manifest, verifies the Pat commit and the libax25 checksum, and builds Pat
  with modules verified against Pat's `go.sum`. It bundles only Pat and the
  Python wrapper. Python, GTK, libadwaita and WebKitGTK come from the host,
  because bundling WebKitGTK in an AppImage is large and fragile (WebKit
  starts helper processes from fixed paths, and graphics drivers must match
  the host). `AppRun` checks for these libraries and names the packages to
  install. The build runs in Debian 12, so Pat needs glibc ≥ 2.34. The
  appimagetool and AppImage runtime binaries are pinned by SHA-256.

## Process model

1. `PatBackend` picks a loopback port (remembered between runs so the web
   UI's origin, and with it localStorage, stays stable) and runs
   `pat http --addr 127.0.0.1:<port>`.
2. It polls the port until Pat accepts connections, then the window loads `/ui`.
3. On quit it sends `SIGINT`. Pat's first SIGINT aborts an active connection
   instead of exiting, so a second SIGINT follows after 2 s and `SIGKILL`
   after 10 s.
4. Pat reloads its configuration in-process and restarts its HTTP server, so
   the window retries failed loads instead of showing an error.
5. If Pat exits unexpectedly, the window shows an error page with *Restart*
   and *Show Log*.

## Web UI integration

| Pat web UI behaviour | Pat Desktop handling |
|---|---|
| `window.open()` for forms, `target=_blank` attachments | Same-origin popups open in a child window that shares the session, so form results reach the composer. Pat's `window.close()` closes it |
| Links to other sites | Opened in the default browser through the portal |
| Downloads and attachments | Native save dialog through the portal |
| HTML5 notifications | Sent as desktop notifications |
| "New Pat version" prompt | `/api/new-release-check` is blocked with a WebKit content filter. Updates arrive through the app instead |

## Known limitations

- The locator "use my position" button relies on browser geolocation and is
  untested in the sandbox. GPSd or typing the locator works.
- Pat's `http_addr` setting is ignored. Remote access from other devices is
  out of scope.
- Any local process can reach Pat's HTTP API on the loopback port, exactly as
  with `pat http`. Pat can only listen on TCP, not on a Unix socket.
