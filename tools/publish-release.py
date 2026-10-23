#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish a release with the given files to Forgejo and, optionally, GitHub.

The same files go to both, so checksums match everywhere. The release notes
are the version's CHANGELOG.md section plus install instructions. Re-running
is safe: an existing release is reused and only missing files are uploaded.

Usage: tools/publish-release.py vX.Y.Z FILE...

Environment:
  FORGEJO_API     e.g. https://code.example/api/v1/repos/OWNER/REPO (required)
  FORGEJO_TOKEN   token allowed to create releases (required)
  GH_TOKEN        GitHub token with Contents read/write on GH_REPO; without
                  it the GitHub release is skipped
  GH_REPO         OWNER/REPO of the GitHub mirror
  GH_TAG_TIMEOUT  seconds to wait for the mirror to receive the tag (900)
  GH_API, GH_UPLOADS  API base URLs (for testing; default to github.com's)
"""

import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from changelog import section

INSTALL = """

### Install

- **Flatpak (recommended):** download `Pat_Desktop-{v}-x86_64.flatpak` and run
  `flatpak install --user Pat_Desktop-{v}-x86_64.flatpak`
- **AppImage:** needs Python 3, GTK 4, libadwaita 1.5+ and WebKitGTK 6.0 from your
  distribution (see the README). Make it executable and run it.

Verify downloads with `sha256sum -c --ignore-missing SHA256SUMS`."""


def request(method, url, token, auth="token", data=None, content_type=None):
    headers = {"Authorization": f"{auth} {token}", "Accept": "application/json",
               "User-Agent": "pat-desktop-release"}
    if isinstance(data, (dict, list)):
        data, content_type = json.dumps(data).encode(), "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read()
    return json.loads(body) if body else None


def get_or_none(url, token, auth):
    try:
        return request("GET", url, token, auth)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def release_payload(tag):
    version = tag.removeprefix("v")
    notes = section(version)
    if not notes:
        raise SystemExit(f"no CHANGELOG.md section for {version}")
    return {"tag_name": tag, "name": f"Pat Desktop {version}",
            "body": notes + INSTALL.format(v=version)}


def multipart(field, path):
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n")
    body = head.encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def publish_forgejo(api, token, tag, files):
    release = (get_or_none(f"{api}/releases/tags/{tag}", token, "token")
               or request("POST", f"{api}/releases", token, data=release_payload(tag)))
    existing = {a["name"] for a in release.get("assets") or []}
    for path in files:
        if path.name in existing:
            print(f"Forgejo: {path.name} already uploaded")
            continue
        body, ctype = multipart("attachment", path)
        request("POST", f"{api}/releases/{release['id']}/assets?name={path.name}",
                token, data=body, content_type=ctype)
        print(f"Forgejo: uploaded {path.name}")


def publish_github(api, uploads, repo, token, tag, files, timeout):
    # The tag reaches GitHub through the Forgejo push mirror; creating the
    # release first would make GitHub create a conflicting tag of its own.
    deadline = time.monotonic() + timeout
    while not get_or_none(f"{api}/repos/{repo}/git/ref/tags/{tag}", token, "Bearer"):
        if time.monotonic() > deadline:
            raise SystemExit(f"GitHub: tag {tag} did not reach {repo} within {timeout}s; "
                             "is the push mirror running?")
        print(f"GitHub: waiting for the mirror to push {tag}...")
        time.sleep(15)

    release = (get_or_none(f"{api}/repos/{repo}/releases/tags/{tag}", token, "Bearer")
               or request("POST", f"{api}/repos/{repo}/releases", token, "Bearer",
                          data=release_payload(tag)))
    existing = {a["name"] for a in release.get("assets") or []}
    for path in files:
        if path.name in existing:
            print(f"GitHub: {path.name} already uploaded")
            continue
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        request("POST", f"{uploads}/repos/{repo}/releases/{release['id']}/assets"
                f"?name={path.name}", token, "Bearer", data=path.read_bytes(),
                content_type=ctype)
        print(f"GitHub: uploaded {path.name}")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    tag, files = sys.argv[1], [Path(f) for f in sys.argv[2:]]
    env = os.environ
    publish_forgejo(env["FORGEJO_API"].rstrip("/"), env["FORGEJO_TOKEN"], tag, files)
    if env.get("GH_TOKEN"):
        publish_github(env.get("GH_API", "https://api.github.com").rstrip("/"),
                       env.get("GH_UPLOADS", "https://uploads.github.com").rstrip("/"),
                       env["GH_REPO"], env["GH_TOKEN"], tag, files,
                       int(env.get("GH_TAG_TIMEOUT", "900")))
    else:
        print("GH_TOKEN not set; skipping the GitHub release.")


if __name__ == "__main__":
    main()
