# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for tools/update-modems.py (python3 -m unittest discover -s tools -p 'test_*.py')."""

import importlib.util
import json
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "update_modems", Path(__file__).with_name("update-modems.py"))
um = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(um)

MANIFEST = """modules:
  - name: hamlib
    sources:
      - type: archive
        url: https://example.org/hamlib-4.7.2.tar.gz
        sha256: aaaa

  - name: direwolf
    sources:
      - type: git
        url: https://github.com/wb2osz/direwolf.git
        tag: 1.8.1
        commit: 1111

  - name: mercury
    sources:
      - type: git
        url: https://github.com/Rhizomatica/mercury.git
        tag: v1.9.23
        commit: 2222
"""

LOCK = """
version = 4

[[package]]
name = "xara"
version = "0.1.3"

[[package]]
name = "libc"
version = "0.2.191"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "abc123"
"""


class ManifestEditing(unittest.TestCase):
    def test_edits_only_the_named_module(self):
        start, end = um.module_block(MANIFEST, "direwolf")
        block = MANIFEST[start:end]
        self.assertEqual(um.get_value(block, "tag"), "1.8.1")
        block = um.set_value(um.set_value(block, "tag", "1.8.2"), "commit", "3333")
        text = MANIFEST[:start] + block + MANIFEST[end:]
        self.assertIn("tag: 1.8.2\n        commit: 3333", text)
        self.assertIn("tag: v1.9.23\n        commit: 2222", text)
        self.assertIn("sha256: aaaa", text)

    def test_last_module_runs_to_the_end(self):
        start, end = um.module_block(MANIFEST, "mercury")
        self.assertEqual(end, len(MANIFEST))

    def test_unknown_module(self):
        with self.assertRaises(SystemExit):
            um.module_block(MANIFEST, "vara")


class CargoSources(unittest.TestCase):
    def test_registry_crates_only(self):
        sources = um.cargo_sources(LOCK)
        archive, checksum, config = sources
        self.assertEqual(archive["url"], "https://static.crates.io/crates/libc/libc-0.2.191.crate")
        self.assertEqual(archive["sha256"], "abc123")
        self.assertEqual(archive["dest"], "cargo/vendor/libc-0.2.191")
        self.assertEqual(json.loads(checksum["contents"]), {"package": "abc123", "files": {}})
        self.assertIn('directory = "cargo/vendor"', config["contents"])

    def test_git_crates_are_refused(self):
        lock = LOCK.replace("registry+https://github.com/rust-lang/crates.io-index",
                            "git+https://example.org/x.git#deadbeef")
        with self.assertRaises(SystemExit):
            um.cargo_sources(lock)


if __name__ == "__main__":
    unittest.main()
