#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""CHANGELOG.md helpers, used by bump-version.py and the release workflow.

Usage:
  tools/changelog.py notes VERSION   print the changelog section of VERSION
  tools/changelog.py check VERSION   verify that VERSION is consistently released
"""

import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
INIT = ROOT / "pat_desktop" / "__init__.py"


def metainfo_path():
    (path,) = (ROOT / "data").glob("*.metainfo.xml")
    return path


def section(version, text=None):
    """Body of the `## [version]` section, or None."""
    text = CHANGELOG.read_text() if text is None else text
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def code_version():
    return re.search(r'^VERSION = "(.*)"$', INIT.read_text(), re.M).group(1)


def _inline(text):
    text = escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links: keep the text
    return re.sub(r"\*\*?([^*]+)\*\*?", r"<em>\1</em>", text)


def to_appstream(markdown, indent="        "):
    """Convert a changelog section to AppStream description markup."""
    out, items, para = [], [], []

    def flush():
        if para:
            out.append(f"{indent}<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append(f"{indent}<ul>")
            out.extend(f"{indent}  <li>{_inline(i)}</li>" for i in items)
            out.append(f"{indent}</ul>")
            items.clear()

    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            flush()
        elif line.startswith("### "):
            flush()
            out.append(f"{indent}<p>{_inline(line[4:])}:</p>")
        elif line.startswith(("- ", "* ")):
            if para:
                flush()
            items.append(line[2:])
        elif items:
            items[-1] += " " + line
        else:
            para.append(line)
    flush()
    return "\n".join(out)


def check(version):
    errors = []
    if code_version() != version:
        errors.append(f"pat_desktop/__init__.py has VERSION {code_version()}")
    if not section(version):
        errors.append(f"CHANGELOG.md has no (or an empty) [{version}] section")
    if f'<release version="{version}"' not in metainfo_path().read_text():
        errors.append(f"{metainfo_path().name} has no <release> for {version}")
    return errors


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("notes", "check"):
        raise SystemExit(__doc__)
    cmd, version = sys.argv[1], sys.argv[2].removeprefix("v")
    if cmd == "notes":
        notes = section(version)
        if not notes:
            raise SystemExit(f"no changelog section for {version}")
        print(notes)
    else:
        errors = check(version)
        if errors:
            raise SystemExit("\n".join(f"error: {e}" for e in errors))
        print(f"{version} is consistent")


if __name__ == "__main__":
    main()
