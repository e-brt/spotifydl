"""Location of the user's files and migration from earlier versions."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import AppTestCase

import config_manager
import main_window
import worker


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


class CacheLocationTests(AppTestCase):
    """File → Show cache location."""

    def test_menu_entry(self):
        window = self.make_window()
        file_menu = window.menuBar().actions()[0].menu()
        self.assertEqual([action.text() for action in file_menu.actions()],
                         ["Show configuration location", "Show cache location", "Open logs folder"])

    def test_shows_the_path_the_worker_uses(self):
        window = self.make_window()
        shown = []
        with mock.patch.object(main_window.QMessageBox, "information",
                               lambda parent, title, text: shown.append((title, text))):
            window._show_cache_location()
        expected = config_manager.config_dir() / worker.CACHE_FILENAME
        self.assertEqual(shown[0][0], "Spotify cache")
        self.assertIn(str(expected), shown[0][1])

    def test_text_says_whether_the_cache_exists_yet(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "spotify_cache.json"
            self.assertIn("does not exist yet", main_window.cache_location_text(path))
            path.write_text("{}", encoding="utf-8")
            text = main_window.cache_location_text(path)
            self.assertNotIn("does not exist yet", text)
            self.assertIn("can be deleted at any time", text)


if __name__ == "__main__":
    unittest.main()
