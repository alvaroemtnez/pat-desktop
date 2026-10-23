#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bump the pins in a checkout of the app's Flathub repository.

Flathub does not accept AI-generated or AI-assisted manifests, so the manifest
in the Flathub repo is written and owned by a human maintainer. This tool never
writes it from scratch. It only:

  * sets `tag:` and `commit:` of the git source whose `url:` is this repo,
  * copies the `tag:` and `commit:` of the upstream Pat source from
    build-aux/flatpak into it,
  * copies the generated Go module source list (pat-go-vendor.json and
    pat-modules.txt) next to it.

Both git sources must list `url:`, `tag:` and `commit:` in that order.

Usage: tools/flathub-bump.py --url REPO_URL --tag vX.Y.Z --commit SHA --flathub DIR
"""

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLATPAK_DIR = ROOT / "build-aux" / "flatpak"
PAT_URL = "https://github.com/la5nta/pat.git"


def pin_pattern(url):
    return re.compile(
        rf"(?P<head>url: {re.escape(url)}\n(?P<i>\s+)tag: )\S+\n(?P=i)commit: \S+")


def set_pin(text, url, tag, commit, path):
    text, n = pin_pattern(url).subn(
        lambda m: f"{m['head']}{tag}\n{m['i']}commit: {commit}", text)
    if n != 1:
        raise SystemExit(f"{path}: expected one git source with url: {url} "
                         "followed by tag: and commit:")
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="git URL of this repo, as in the manifest")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--flathub", required=True, type=Path,
                        help="checkout of the Flathub repository")
    args = parser.parse_args()

    (ours,) = FLATPAK_DIR.glob("*.yml")
    target = args.flathub / ours.name
    if not target.exists():
        raise SystemExit(f"{target} not found; the Flathub manifest must exist already")

    m = re.search(rf"url: {re.escape(PAT_URL)}\n\s+tag: (\S+)\n\s+commit: (\S+)",
                  ours.read_text())
    if not m:
        raise SystemExit(f"{ours}: Pat git source not found")
    pat_tag, pat_commit = m.groups()

    text = target.read_text()
    text = set_pin(text, args.url, args.tag, args.commit, target)
    text = set_pin(text, PAT_URL, pat_tag, pat_commit, target)
    target.write_text(text)
    for name in ("pat-go-vendor.json", "pat-modules.txt"):
        shutil.copy(FLATPAK_DIR / name, args.flathub / name)
    print(f"{target}: pinned {args.tag} and Pat {pat_tag}")


if __name__ == "__main__":
    main()
