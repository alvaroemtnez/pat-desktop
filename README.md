# Pat Desktop

**Pat, the Winlink client, as a regular desktop app.**

> [!IMPORTANT]
> Pat Desktop is an **unofficial**, community-maintained project. It is **not affiliated with, endorsed by or supported by** the [Pat project](https://getpat.io), its author Martin Hebnes Pedersen (LA5NTA), or the Winlink Development Team. Please report problems with Pat Desktop here, not upstream, unless you can reproduce them with the plain `pat` command.

[Pat](https://github.com/la5nta/pat) is an excellent cross-platform Winlink client. On Linux you normally install it with Go or a package, start it from a terminal (`pat http`) and use it from a browser at `http://localhost:8080`. Pat Desktop does that for you: it starts from your application menu, opens in its own window, and starts and stops Pat in the background.

![The Pat Desktop mailbox](data/screenshots/mailbox.png)

## Features

- **A real desktop app.** Launcher icon, its own window, single instance, keyboard shortcuts, desktop notifications for new messages.
- **No ports, no terminal.** Pat runs as a managed child process on a private loopback port. Closing the window shuts Pat down cleanly, and asks first if a Winlink session is in progress.
- **Radio setup from the app.** Your first launch opens Pat's configuration page (callsign, locator, ARDOP, VARA, PACTOR, AX.25, rigctld, GPSd, …). It is always under *Menu → Pat Configuration* (<kbd>Ctrl</kbd>+<kbd>,</kbd>).
- **Forms, attachments and links behave like a desktop app.** Winlink forms open in their own windows, attachments are saved through the normal file dialog, and external links open in your browser.
- **Troubleshooting built in.** *Menu → Show Log* gives a live view of Pat's output, and *Restart Pat* restarts it without restarting the app.
- **Pristine upstream Pat.** Pat is built unmodified from a pinned upstream release tag, the same code as the official binaries, and identifies itself to Winlink exactly as upstream Pat does.

## Installing

Pat Desktop is distributed as a Flatpak.

- **Flathub:** not yet available.
- **Test builds:** every release on this repository has a `pat-desktop-vX.Y.Z.flatpak` bundle:

  ```sh
  flatpak install --user pat-desktop-vX.Y.Z.flatpak
  ```

  The GNOME runtime is fetched from Flathub automatically.

### Radio hardware and permissions

| What | How it works in the Flatpak |
|---|---|
| Telnet / CMS, ARDOP, VARA, rigctld, AGWPE/Direwolf, GPSd | Over TCP. Works out of the box (`--share=network`). |
| Serial and USB devices (PACTOR modems, KISS TNCs, CAT/PTT cables) | Allowed (`--device=all`). Your user still needs host permission for the device, usually membership in the `dialout` group. |
| Linux kernel AX.25 (`ax25+linux` engine) | Pat Desktop reads the host's `/etc/ax25/axports`, but only after you opt in: `flatpak override --user --filesystem=host-etc:ro io.getpat.desktopapp` |

Pat runs inside the sandbox. External modem programs such as ARDOP, VARA (under Wine) or Direwolf run on your host as usual and Pat reaches them over TCP.

### Moving an existing Pat setup over

The Flatpak keeps its own copy of Pat's files. To reuse your current configuration and mailbox, quit Pat Desktop and run:

```sh
mkdir -p ~/.var/app/io.getpat.desktopapp/config ~/.var/app/io.getpat.desktopapp/data
cp -r ~/.config/pat ~/.var/app/io.getpat.desktopapp/config/
cp -r ~/.local/share/pat ~/.var/app/io.getpat.desktopapp/data/
```

Pat's `http_addr` setting is ignored: Pat Desktop always listens on a private loopback address. If you want to reach Pat from other devices on your network, use plain `pat http` instead.

## How it works

```
┌──────────────── Flatpak sandbox ────────────────┐
│  Pat Desktop (Python, GTK 4, libadwaita)        │
│   ├─ starts:  pat http --addr 127.0.0.1:<port>  │
│   ├─ WebKitGTK window showing Pat's own web UI  │
│   └─ stops it with SIGINT on quit               │
│  /app/bin/pat ← unmodified upstream, pinned tag │
└─────────────────────────────────────────────────┘
```

The wrapper does not change Pat or re-implement its UI. It handles what a browser tab can't do well: process lifecycle, windows for forms, downloads, notifications, external links, and hiding Pat's "download the new version" prompt, which doesn't apply when the app is updated as a whole. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains why Pat is built in instead of being downloaded at runtime.

## Building

You need `flatpak` and `org.flatpak.Builder` from Flathub:

```sh
flatpak install --user flathub org.flatpak.Builder
flatpak run org.flatpak.Builder --user --install --install-deps-from=flathub \
    --force-clean build-dir build-aux/flatpak/io.getpat.desktopapp.yml
flatpak run io.getpat.desktopapp
```

### Hacking without Flatpak

The wrapper is plain Python and needs PyGObject with GTK 4, libadwaita ≥ 1.6, WebKitGTK 6.0 and libsoup 3, plus a `pat` binary:

```sh
PAT_DESKTOP_PAT_BINARY=$(command -v pat) PAT_DESKTOP_DEBUG=1 python3 -m pat_desktop
```

`PAT_DESKTOP_DEBUG=1` enables the WebKit inspector (right click → Inspect Element). Careful: outside the sandbox this uses your real `~/.config/pat`.

### Updating Pat

```sh
tools/update-pat.py            # latest upstream release, or: tools/update-pat.py v1.2.3
```

This re-pins the upstream tag and commit in the manifest and regenerates `build-aux/flatpak/pat-go-vendor.json`, the list of Go modules Pat needs, because Flathub builds run without network access. A weekly CI job does this automatically and opens a pull request.

### Project layout

| Path | Contents |
|---|---|
| `pat_desktop/` | The wrapper application |
| `data/` | Desktop entry, AppStream metainfo, icons, screenshots |
| `build-aux/flatpak/` | Flatpak manifest and generated Go module sources |
| `tools/` | Pat updater, version bump, Flathub pin bump, app-ID rename |
| `.forgejo/workflows/` | CI, weekly Pat update check, tagged releases |
| `docs/` | Architecture notes and the publishing guide |

## Releasing

See [docs/PUBLISHING.md](docs/PUBLISHING.md). In short: `tools/bump-version.py X.Y.Z "notes"`, commit, push a `vX.Y.Z` tag. CI builds the bundle, creates the release, and opens a pull request on the Flathub repository.

## AI use disclosure

Most of this repository was written with an AI coding assistant (Anthropic's Claude, through Claude Code): the wrapper application in `pat_desktop/`, the tools in `tools/`, the CI workflows, the local Flatpak manifest, the desktop and metainfo files, and the documentation. The maintainer directs the work and reviews every change before it is pushed. The icons come from the official Pat logo, and the screenshots are captures of the running app.

Pat itself is not part of this repository and contains none of this code. It is built from the untouched upstream source.

In line with [Flathub's policy](https://docs.flathub.org/docs/for-app-authors/requirements#generative-ai-policy), the manifest in the Flathub repository is written by a human, not generated.

## License

Pat Desktop is free software, licensed under the [GNU General Public License v3.0 or later](LICENSE).

Bundled components keep their own licenses: Pat is MIT-licensed (© Martin Hebnes Pedersen, LA5NTA), its web UI includes MIT-licensed libraries, and libax25 is LGPL-2.1. The Pat name and logo belong to the Pat project and are used here only to identify the software being packaged.

## Acknowledgements

All the radio work is done by [Pat](https://github.com/la5nta/pat) and its contributors. If Pat is useful to you, consider supporting the upstream project.
