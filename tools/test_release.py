#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release and beta rules of tools/changelog.py and tools/publish-release.py.

Run: python3 -m unittest discover -s tools -p 'test_*.py'
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import changelog

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("publish_release", TOOLS / "publish-release.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)

CHANGELOG = """# Changelog

## [Unreleased]

### Changed
- Update Pat to v1.0.1

## [0.1.0] - 2026-10-23

### Added
- First release
"""

METAINFO = """<component><releases>
    <release version="0.1.0" date="2026-10-23"/>
  </releases></component>
"""


class Repo:
    """A throwaway CHANGELOG.md, __init__.py and metainfo that changelog.py reads."""

    def __init__(self, version, text=CHANGELOG):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "data").mkdir()
        (root / "data" / "app.metainfo.xml").write_text(METAINFO)
        (root / "CHANGELOG.md").write_text(text)
        (root / "__init__.py").write_text(f'VERSION = "{version}"\n')
        self.patches = [
            mock.patch.object(changelog, "ROOT", root),
            mock.patch.object(changelog, "CHANGELOG", root / "CHANGELOG.md"),
            mock.patch.object(changelog, "INIT", root / "__init__.py"),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()
        self.dir.cleanup()


class ParseVersion(unittest.TestCase):
    def test_releases_and_betas(self):
        self.assertEqual(changelog.parse_version("0.2.0"), ("0.2.0", False))
        self.assertEqual(changelog.parse_version("0.2.0-beta.3"), ("0.2.0", True))

    def test_anything_else_is_refused(self):
        for v in ["0.2", "0.2.0.1", "v0.2.0", "0.2.0-beta", "0.2.0-beta.0", "0.2.0-rc.1",
                  "0.02.0", "0.2.0 ", "0.2.0\n0.3.0", ""]:
            self.assertIsNone(changelog.parse_version(v), v)


class Notes(unittest.TestCase):
    def test_a_release_publishes_its_section(self):
        self.assertEqual(changelog.release_notes("0.1.0", CHANGELOG), "### Added\n- First release")

    def test_a_beta_publishes_the_unreleased_entries_it_previews(self):
        self.assertEqual(changelog.release_notes("0.2.0-beta.1", CHANGELOG),
                         "Pre-release of 0.2.0, for testing.\n\n### Changed\n- Update Pat to v1.0.1")

    def test_an_empty_unreleased_section_gives_a_beta_no_notes(self):
        empty = CHANGELOG.replace("### Changed\n- Update Pat to v1.0.1\n", "")
        self.assertIsNone(changelog.release_notes("0.2.0-beta.1", empty))


class Check(unittest.TestCase):
    def test_a_beta_is_consistent_without_a_section_or_metainfo_release(self):
        with Repo("0.2.0-beta.1"):
            self.assertEqual(changelog.check("0.2.0-beta.1"), [])

    def test_a_beta_needs_its_version_set_and_unreleased_entries(self):
        with Repo("0.1.0"):
            self.assertEqual(len(changelog.check("0.2.0-beta.1")), 1)
        with Repo("0.2.0-beta.1", CHANGELOG.replace("### Changed\n- Update Pat to v1.0.1\n", "")):
            self.assertEqual(len(changelog.check("0.2.0-beta.1")), 1)

    def test_no_beta_of_a_version_already_released(self):
        with Repo("0.1.0-beta.1"):
            self.assertIn("already released", changelog.check("0.1.0-beta.1")[0])

    def test_a_release_still_needs_its_section_and_metainfo_release(self):
        with Repo("0.1.0"):
            self.assertEqual(changelog.check("0.1.0"), [])
        with Repo("0.2.0"):
            self.assertEqual(len(changelog.check("0.2.0")), 2)

    def test_a_malformed_tag_is_refused(self):
        with Repo("0.2.0-rc.1"):
            self.assertEqual(len(changelog.check("0.2.0-rc.1")), 1)


class Payload(unittest.TestCase):
    def test_only_a_beta_is_a_prerelease(self):
        with Repo("0.2.0-beta.1"):
            beta = publish.release_payload("v0.2.0-beta.1")
            release = publish.release_payload("v0.1.0")
        self.assertIs(beta["prerelease"], True)
        self.assertTrue(beta["body"].startswith("Pre-release of 0.2.0"))
        self.assertIn("Pat_Desktop-0.2.0-beta.1-x86_64.flatpak", beta["body"])
        self.assertIs(release["prerelease"], False)
        self.assertTrue(release["body"].startswith("### Added"))

    def test_a_malformed_tag_publishes_nothing(self):
        with Repo("0.2.0"), self.assertRaises(SystemExit):
            publish.release_payload("v0.2.0-rc.1")


if __name__ == "__main__":
    unittest.main()
