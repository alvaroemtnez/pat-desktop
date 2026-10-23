#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin the Flatpak build to an upstream Pat release.

Flatpak builds have no network access, so every Go module Pat depends on must
be listed as a source in the manifest. This script:

  1. resolves an upstream tag (default: the latest GitHub release),
  2. runs `go mod vendor` on a pristine checkout of that tag,
  3. writes build-aux/flatpak/pat-go-vendor.json with one archive source per
     vendored module (fetched from proxy.golang.org, sha256-pinned), plus the
     generated vendor/modules.txt,
  4. updates the `tag:` / `commit:` of the pat module in the manifest.

Upstream code is never modified; only the pin moves.

Usage: tools/update-pat.py [vX.Y.Z]   (requires git, go and network access)
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

UPSTREAM = "https://github.com/la5nta/pat.git"
ROOT = Path(__file__).resolve().parent.parent
FLATPAK_DIR = ROOT / "build-aux" / "flatpak"
MANIFEST = FLATPAK_DIR / "io.getpat.desktopapp.yml"
VENDOR_JSON = FLATPAK_DIR / "pat-go-vendor.json"
PROXY = "https://proxy.golang.org"


def latest_release() -> str:
    url = "https://api.github.com/repos/la5nta/pat/releases/latest"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)["tag_name"]


def escape(path: str) -> str:
    # Module proxy case-encoding: uppercase letters become "!" + lowercase.
    return re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), path)


def sha256_url(url: str) -> str:
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as resp:
        for chunk in iter(lambda: resp.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_modules_txt(text: str):
    """Yield (vendor_path, fetch_path, fetch_version) for each vendored module."""
    for line in text.splitlines():
        if not line.startswith("# "):
            continue
        parts = line[2:].split()
        if "=>" in parts:
            i = parts.index("=>")
            old, new = parts[0], parts[i + 1:]
            if len(new) != 2:
                sys.exit(f"local replace directives are not supported: {line}")
            yield old, new[0], new[1]
        elif len(parts) == 2:
            yield parts[0], parts[0], parts[1]


def main() -> None:
    tag = sys.argv[1] if len(sys.argv) > 1 else latest_release()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "pat"
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", tag,
                        UPSTREAM, str(src)], check=True)
        commit = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                                check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(["go", "mod", "vendor"], cwd=src, check=True,
                       env={**os.environ, "GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"})
        modules_txt = (src / "vendor" / "modules.txt").read_text()
        shutil.copy(src / "vendor" / "modules.txt", FLATPAK_DIR / "pat-modules.txt")

    sources = []
    for vendor_path, mod, ver in parse_modules_txt(modules_txt):
        url = f"{PROXY}/{escape(mod)}/@v/{escape(ver)}.zip"
        print(f"  {mod} {ver}", file=sys.stderr)
        sources.append({
            "type": "archive",
            "archive-type": "zip",
            "url": url,
            "sha256": sha256_url(url),
            # Zips are laid out as "<module>@<version>/...".
            "strip-components": len(mod.split("/")),
            "dest": f"vendor/{vendor_path}",
        })
    sources.append({"type": "file", "path": "pat-modules.txt",
                    "dest": "vendor", "dest-filename": "modules.txt"})
    VENDOR_JSON.write_text(json.dumps(sources, indent=2) + "\n")

    manifest = MANIFEST.read_text()
    manifest, n = re.subn(
        r"(url: https://github\.com/la5nta/pat\.git\n(\s+)tag: )\S+\n\s+commit: \S+",
        lambda m: f"{m.group(1)}{tag}\n{m.group(2)}commit: {commit}",
        manifest)
    if n != 1:
        sys.exit("could not find the pat git source in the manifest")
    MANIFEST.write_text(manifest)
    print(f"Pinned Pat {tag} ({commit[:12]}), {len(sources) - 1} Go modules.")


if __name__ == "__main__":
    main()
