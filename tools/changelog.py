#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""CHANGELOG.md helpers, used by bump-version.py and the release workflow.

Usage:
  tools/changelog.py notes VERSION   print the release notes of VERSION
  tools/changelog.py check VERSION   verify that VERSION is consistently released
  tools/changelog.py add ENTRY       add ENTRY under [Unreleased] → Changed (an
                                     "Update X to Y" entry replaces one for X)

VERSION is X.Y.Z, or X.Y.Z-beta.N for a pre-release of X.Y.Z (docs/RELEASING.md,
"Betas"): its notes are the [Unreleased] entries it previews, and it has no
section or <release> of its own until X.Y.Z is released.
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


VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-beta\.[1-9]\d*)?")


def parse_version(version):
    """(release, is_beta) for X.Y.Z or X.Y.Z-beta.N; None for anything else."""
    m = VERSION_RE.fullmatch(version)
    return (version.split("-")[0], m.group(4) is not None) if m else None


def section(version, text=None):
    """Body of the `## [version]` section, or None."""
    text = CHANGELOG.read_text() if text is None else text
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def release_notes(version, text=None):
    """What a release of VERSION publishes as notes: its section, or for a beta
    the [Unreleased] entries under a "Pre-release of" line. None if there are none."""
    parsed = parse_version(version)
    if not parsed:
        return None
    release, beta = parsed
    if not beta:
        return section(version, text)
    notes = section("Unreleased", text)
    return f"Pre-release of {release}, for testing.\n\n{notes}" if notes else None


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


SUBSECTIONS = ["Added", "Changed", "Fixed"]
UPDATE_RE = re.compile(r"^- (Update .+? to )")


def add_entry(entry, text, subsection="Changed"):
    """TEXT with `- ENTRY` under [Unreleased] → SUBSECTION.

    An "Update X to Y" entry replaces an earlier one for X, so a component
    bumped twice before a release is listed once, at its last version."""
    line = "- " + entry.removeprefix("- ").strip()
    start = text.index("## [Unreleased]")
    nxt = text.find("\n## [", start + 1)
    end = nxt + 1 if nxt != -1 else len(text)
    body = text[start:end].rstrip("\n").split("\n")

    update = UPDATE_RE.match(line)
    if update:
        body = [b for b in body if not b.startswith("- " + update.group(1))]

    heading = f"### {subsection}"
    if heading not in body:
        # Keep the Added, Changed, Fixed order.
        later = [f"### {s}" for s in SUBSECTIONS[SUBSECTIONS.index(subsection) + 1:]]
        at = next((i for i, b in enumerate(body) if b in later), len(body))
        while at > 1 and body[at - 1] == "":
            at -= 1
        body[at:at] = ["", heading, ""]
    i = body.index(heading) + 1
    while i < len(body) and body[i] == "":
        i += 1
    while i < len(body) and body[i].startswith("- "):
        i += 1
    body.insert(i, line)
    # Drop empty subsections left by a replaced entry.
    out = []
    for j, b in enumerate(body):
        if b.startswith("### ") and not any(
                x.startswith("- ") for x in body[j + 1:next(
                    (k for k in range(j + 1, len(body)) if body[k].startswith("### ")), len(body))]):
            continue
        out.append(b)
    # One blank line around each subsection heading.
    joined = re.sub(r"\n*(### [^\n]*)\n*", r"\n\n\1\n\n", "\n".join(out))
    cleaned = re.sub(r"\n{3,}", "\n\n", joined).rstrip("\n")
    return text[:start] + cleaned + "\n\n" + text[end:].lstrip("\n") if nxt != -1 \
        else text[:start] + cleaned + "\n"


def check(version):
    parsed = parse_version(version)
    if not parsed:
        return [f"{version} is not X.Y.Z or X.Y.Z-beta.N"]
    release, beta = parsed
    errors = []
    if code_version() != version:
        errors.append(f"pat_desktop/__init__.py has VERSION {code_version()}")
    if beta:
        if section(release):
            errors.append(f"{release} is already released; a beta comes before it")
        if not release_notes(version):
            errors.append("CHANGELOG.md has an empty [Unreleased] section, the beta's notes")
    else:
        if not section(version):
            errors.append(f"CHANGELOG.md has no (or an empty) [{version}] section")
        if f'<release version="{version}"' not in metainfo_path().read_text():
            errors.append(f"{metainfo_path().name} has no <release> for {version}")
    return errors


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("notes", "check", "add"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "add":
        CHANGELOG.write_text(add_entry(sys.argv[2], CHANGELOG.read_text()))
        return
    cmd, version = sys.argv[1], sys.argv[2].removeprefix("v")
    if cmd == "notes":
        notes = release_notes(version)
        if not notes:
            raise SystemExit(f"no release notes for {version}")
        print(notes)
    else:
        errors = check(version)
        if errors:
            raise SystemExit("\n".join(f"error: {e}" for e in errors))
        print(f"{version} is consistent")


if __name__ == "__main__":
    main()
