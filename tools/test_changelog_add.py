# SPDX-License-Identifier: GPL-3.0-or-later
"""`tools/changelog.py add`, used by the weekly update pull request."""

import unittest

import changelog

BASE = """# Changelog

## [Unreleased]

## [0.1.0] - 2026-10-23

### Added
- First release
"""


class AddEntry(unittest.TestCase):
    def test_creates_changed_in_an_empty_unreleased(self):
        text = changelog.add_entry("Update Direwolf to 1.8.2.", BASE)
        self.assertEqual(changelog.section("Unreleased", text),
                         "### Changed\n\n- Update Direwolf to 1.8.2.")
        self.assertIn("## [0.1.0] - 2026-10-23\n\n### Added\n- First release", text)

    def test_a_newer_update_replaces_the_older_one(self):
        text = changelog.add_entry("Update Direwolf to 1.8.2.", BASE)
        text = changelog.add_entry("Update Pat to v1.0.2.", text)
        text = changelog.add_entry("Update Direwolf to 1.8.3.", text)
        self.assertEqual(changelog.section("Unreleased", text),
                         "### Changed\n\n- Update Pat to v1.0.2.\n- Update Direwolf to 1.8.3.")

    def test_keeps_added_before_and_fixed_after(self):
        text = BASE.replace("## [Unreleased]\n",
                            "## [Unreleased]\n\n### Added\n\n- A\n\n### Fixed\n\n- F\n")
        text = changelog.add_entry("Update Mercury to v1.9.24.", text)
        self.assertEqual(changelog.section("Unreleased", text),
                         "### Added\n\n- A\n\n### Changed\n\n- Update Mercury to v1.9.24.\n\n"
                         "### Fixed\n\n- F")


if __name__ == "__main__":
    unittest.main()
