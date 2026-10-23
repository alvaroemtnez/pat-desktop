#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release the [Unreleased] changelog entries as a new version.

  * renames the `## [Unreleased]` section of CHANGELOG.md to
    `## [X.Y.Z] - DATE` and opens a new empty [Unreleased] section,
  * sets VERSION in pat_desktop/__init__.py,
  * adds the matching <release> to the AppStream metainfo.

Usage: tools/bump-version.py X.Y.Z [YYYY-MM-DD]
Then review, commit, and tag: git tag -a vX.Y.Z -m "Pat Desktop X.Y.Z"
"""

import datetime
import re
import sys

from changelog import CHANGELOG, INIT, metainfo_path, section, to_appstream


def main():
    if len(sys.argv) not in (2, 3) or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        raise SystemExit(__doc__)
    version = sys.argv[1]
    date = sys.argv[2] if len(sys.argv) == 3 else datetime.date.today().isoformat()

    text = CHANGELOG.read_text()
    if section(version, text) is not None:
        raise SystemExit(f"CHANGELOG.md already has a [{version}] section")
    notes = section("Unreleased", text)
    if not notes:
        raise SystemExit("The [Unreleased] section of CHANGELOG.md is empty")
    CHANGELOG.write_text(text.replace("## [Unreleased]",
                                      f"## [Unreleased]\n\n## [{version}] - {date}", 1))

    INIT.write_text(re.sub(r'^VERSION = ".*"$', f'VERSION = "{version}"',
                           INIT.read_text(), flags=re.M))

    metainfo = metainfo_path()
    entry = (f'<releases>\n    <release version="{version}" date="{date}">\n'
             f"      <description>\n{to_appstream(notes)}\n      </description>\n"
             f"    </release>")
    metainfo.write_text(metainfo.read_text().replace("<releases>", entry, 1))

    print(f"Released {version}. Review the diff, commit, then:\n"
          f'  git tag -a v{version} -m "Pat Desktop {version}"')


if __name__ == "__main__":
    main()
