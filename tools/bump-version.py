#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Set the Pat Desktop version and add a release entry to the metainfo.

Usage: tools/bump-version.py X.Y.Z "One-line release note" [YYYY-MM-DD]
Then commit and tag: git tag -a vX.Y.Z -m vX.Y.Z
"""

import datetime
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) not in (3, 4) or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        raise SystemExit(__doc__)
    version, note = sys.argv[1], sys.argv[2]
    date = sys.argv[3] if len(sys.argv) == 4 else datetime.date.today().isoformat()

    init = ROOT / "pat_desktop" / "__init__.py"
    text, n = re.subn(r'^VERSION = ".*"$', f'VERSION = "{version}"', init.read_text(),
                      flags=re.MULTILINE)
    if n != 1:
        raise SystemExit(f"VERSION not found in {init}")
    init.write_text(text)

    (metainfo,) = (ROOT / "data").glob("*.metainfo.xml")
    text = metainfo.read_text()
    if f'<release version="{version}"' in text:
        raise SystemExit(f"release {version} already in {metainfo.name}")
    entry = (f'<releases>\n    <release version="{version}" date="{date}">\n'
             f'      <description>\n        <p>{escape(note)}</p>\n'
             f'      </description>\n    </release>')
    metainfo.write_text(text.replace("<releases>", entry, 1))
    print(f"Version set to {version}. Commit, then: git tag -a v{version} -m v{version}")


if __name__ == "__main__":
    main()
