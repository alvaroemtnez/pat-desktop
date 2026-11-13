#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin a bundled modem (or Hamlib) to an upstream release.

Each component is a module of the Flatpak manifest, named as below, built
from a pristine upstream release. This script moves its pin:

  - git sources: the `tag:` and `commit:` lines;
  - archive sources (Hamlib's release tarball): `url:` and `sha256:`;
  - xara: also build-aux/flatpak/xara-cargo-sources.json, the crates in its
    Cargo.lock, which the offline Flatpak build needs.

The AppImage build reads the same pins. Upstream code is never modified.

Usage: tools/update-modems.py [NAME [TAG]]
  NAME  one of the components below; without it, every one that follows
        upstream releases. TAG defaults to the latest upstream release.
Prints "NAME TAG" for each component whose pin changed.
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLATPAK_DIR = ROOT / "build-aux" / "flatpak"
MANIFEST = FLATPAK_DIR / "io.getpat.desktopapp.yml"
CARGO_SOURCES = FLATPAK_DIR / "xara-cargo-sources.json"

# name: (GitHub repo for "latest release", source kind, follows upstream)
COMPONENTS = {
    "hamlib": ("Hamlib/Hamlib", "archive", True),
    "ardopcf": ("pflarue/ardop", "git", True),
    "direwolf": ("wb2osz/direwolf", "git", True),
    "mercury": ("Rhizomatica/mercury", "git", True),
    # Discontinued upstream (November 2026): pinned to the mirror, by hand.
    "xara": (None, "git", False),
}
HAMLIB_URL = "https://github.com/Hamlib/Hamlib/releases/download/{tag}/hamlib-{tag}.tar.gz"
USER_AGENT = {"User-Agent": "pat-desktop-update"}


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=USER_AGENT)
    return urllib.request.urlopen(req, timeout=timeout)


def latest_release(repo):
    with fetch(f"https://api.github.com/repos/{repo}/releases/latest", 30) as resp:
        return json.load(resp)["tag_name"]


def sha256_url(url):
    h = hashlib.sha256()
    with fetch(url) as resp:
        for chunk in iter(lambda: resp.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def module_block(text, name):
    """(start, end) of the manifest module `name`."""
    m = re.search(rf"^  - name: {re.escape(name)}\n", text, re.M)
    if not m:
        sys.exit(f"module {name} not found in {MANIFEST.name}")
    nxt = re.compile(r"^  - name: ", re.M).search(text, m.end())
    return m.start(), nxt.start() if nxt else len(text)


def get_value(block, key):
    m = re.search(rf"^ +{key}: *(\S+)$", block, re.M)
    return m.group(1) if m else None


def set_value(block, key, value):
    new, n = re.subn(rf"^( +{key}: *)\S+$", lambda m: m.group(1) + value, block, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"no {key}: line to update")
    return new


def tag_commit(url, tag):
    out = subprocess.run(["git", "ls-remote", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                         check=True, capture_output=True, text=True).stdout.split("\n")
    refs = dict(reversed(line.split("\t")) for line in out if line)
    # An annotated tag's commit is the peeled ^{} entry.
    commit = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not commit:
        sys.exit(f"tag {tag} not found at {url}")
    return commit


def cargo_sources(lock_text):
    """flatpak-builder sources for every crates.io package in a Cargo.lock."""
    lock = tomllib.loads(lock_text)
    sources = []
    for pkg in lock.get("package", []):
        source = pkg.get("source", "")
        if not source:
            continue  # the workspace's own crates
        if not source.startswith("registry+https://github.com/rust-lang/crates.io-index"):
            sys.exit(f"unsupported crate source {source} ({pkg['name']})")
        name, version, checksum = pkg["name"], pkg["version"], pkg["checksum"]
        dest = f"cargo/vendor/{name}-{version}"
        sources.append({
            "type": "archive", "archive-type": "tar-gzip",
            "url": f"https://static.crates.io/crates/{name}/{name}-{version}.crate",
            "sha256": checksum, "dest": dest,
        })
        sources.append({
            "type": "inline", "dest": dest, "dest-filename": ".cargo-checksum.json",
            "contents": json.dumps({"package": checksum, "files": {}}),
        })
    sources.append({
        "type": "inline", "dest": "cargo", "dest-filename": "config.toml",
        "contents": ('[source.crates-io]\nreplace-with = "vendored-sources"\n\n'
                     '[source.vendored-sources]\ndirectory = "cargo/vendor"\n'),
    })
    return sources


def write_cargo_sources(url, tag):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
                        "--branch", tag, url, tmp],
                       check=True)
        lock = (Path(tmp) / "Cargo.lock").read_text()
    CARGO_SOURCES.write_text(json.dumps(cargo_sources(lock), indent=2) + "\n")


def update(name, tag=None):
    repo, kind, _follows = COMPONENTS[name]
    text = MANIFEST.read_text()
    start, end = module_block(text, name)
    block = text[start:end]
    if kind == "git":
        url = get_value(block, "url")
        if tag is None:
            if not repo:
                sys.exit(f"{name} has no upstream releases to follow; give a tag")
            tag = latest_release(repo)
        if get_value(block, "tag") == tag and not (name == "xara" and not CARGO_SOURCES.exists()):
            return None
        block = set_value(block, "tag", tag)
        block = set_value(block, "commit", tag_commit(url, tag))
        if name == "xara":
            write_cargo_sources(url, tag)
    else:
        tag = tag or latest_release(repo)
        url = HAMLIB_URL.format(tag=tag)
        if get_value(block, "url") == url:
            return None
        block = set_value(block, "url", url)
        block = set_value(block, "sha256", sha256_url(url))
    MANIFEST.write_text(text[:start] + block + text[end:])
    return tag


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if args and args[0] not in COMPONENTS:
        sys.exit(f"unknown component {args[0]}; one of: {', '.join(COMPONENTS)}")
    names = [args[0]] if args else [n for n, c in COMPONENTS.items() if c[2]]
    for name in names:
        tag = update(name, args[1] if len(args) > 1 else None)
        if tag:
            print(name, tag)


if __name__ == "__main__":
    main()
