"""Version, changelog and vendor manifest consistency."""

import json
import re
import unittest

from helpers import ROOT

import main_window
from version import __version__

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseTests(unittest.TestCase):

    def test_version_is_semantic(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")

    def test_changelog_describes_the_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__version__}]", changelog)

    def test_version_is_shown_in_the_application(self):
        self.assertIn(f"Version {__version__}", main_window.about_text())

    def test_license_and_notices_exist(self):
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "vendor.json").read_text(encoding="utf-8"))
        for component in manifest["components"]:
            with self.subTest(component=component["name"]):
                self.assertIn(component["version"], notices, "THIRD_PARTY_NOTICES.md is out of date")

    def test_vendor_manifest(self):
        manifest = json.loads((ROOT / "vendor.json").read_text(encoding="utf-8"))
        names = []
        for component in manifest["components"]:
            with self.subTest(component=component["name"]):
                self.assertTrue(component["archive"]["url"].startswith("https://"))
                self.assertIn(component["version"], component["archive"]["url"],
                              "the archive URL must be pinned to the version")
                self.assertRegex(component["archive"]["sha256"], SHA256)
                license_file = component["license_file"]
                self.assertTrue(license_file.get("url") or license_file.get("archive_path"))
                self.assertRegex(license_file["sha256"], SHA256)
                for file in component["files"]:
                    self.assertRegex(file["sha256"], SHA256)
                    names.append(file["name"])
        self.assertEqual(sorted(names), ["deno.exe", "ffmpeg.exe", "ffprobe.exe"])


if __name__ == "__main__":
    unittest.main()
