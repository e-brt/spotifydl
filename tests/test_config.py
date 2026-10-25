"""Location of the user's files and migration from earlier versions."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT  # noqa: F401  (puts the project on sys.path)

import config_manager


class UserFilesLocationTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app_dir = Path(self._tmp.name)
        for target, attribute, value in [
            (config_manager, "app_dir", lambda: self.app_dir),
            (config_manager, "_migrated", False),
        ]:
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_user_files_are_in_the_data_folder(self):
        self.assertEqual(config_manager.config_path(), self.app_dir / "data" / "config.json")
        config_manager.save_config({"version": 1, "profiles": []})
        self.assertTrue((self.app_dir / "data" / "config.json").is_file())
        self.assertFalse((self.app_dir / "config.json").exists())

    def test_files_of_an_earlier_version_are_moved(self):
        (self.app_dir / "config.json").write_text('{"version": 1, "profiles": [{"name": "Rock"}]}', encoding="utf-8")
        (self.app_dir / "spotify_cache.json").write_text('{"tracks": {}}', encoding="utf-8")
        config = config_manager.load_config()
        self.assertEqual(config["profiles"][0]["name"], "Rock")
        self.assertFalse((self.app_dir / "config.json").exists())
        self.assertFalse((self.app_dir / "spotify_cache.json").exists())
        self.assertTrue((self.app_dir / "data" / "spotify_cache.json").is_file())

    def test_existing_data_files_are_never_overwritten(self):
        data = self.app_dir / "data"
        data.mkdir()
        (data / "config.json").write_text('{"version": 1, "profiles": [{"name": "New"}]}', encoding="utf-8")
        (self.app_dir / "config.json").write_text('{"version": 1, "profiles": [{"name": "Old"}]}', encoding="utf-8")
        config = config_manager.load_config()
        self.assertEqual(config["profiles"][0]["name"], "New")
        self.assertTrue((self.app_dir / "config.json").exists(), "the old file must be left untouched")


if __name__ == "__main__":
    unittest.main()
