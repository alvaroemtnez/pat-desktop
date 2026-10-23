#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the JSON body of the Forgejo release for a tag (used by CI).

Usage: tools/release-body.py vX.Y.Z
"""

import json
import sys

from changelog import section

INSTALL = """

### Install

- **Flatpak (recommended):** download `Pat_Desktop-{v}-x86_64.flatpak` and run
  `flatpak install --user Pat_Desktop-{v}-x86_64.flatpak`
- **AppImage:** needs Python 3, GTK 4, libadwaita 1.5+ and WebKitGTK 6.0 from your
  distribution (see the README). Make it executable and run it.

Verify downloads with `sha256sum -c --ignore-missing SHA256SUMS`."""


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    tag = sys.argv[1]
    version = tag.removeprefix("v")
    notes = section(version)
    if not notes:
        raise SystemExit(f"no changelog section for {version}")
    print(json.dumps({"tag_name": tag, "name": f"Pat Desktop {version}",
                      "body": notes + INSTALL.format(v=version)}))


if __name__ == "__main__":
    main()
