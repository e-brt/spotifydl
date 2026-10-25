"""Light theme and theme switch (SPECIFICATION.md, section 8)."""

import unittest
from pathlib import Path

import app
from helpers import AppTestCase


class ThemeTests(AppTestCase):

    def window_with(self, settings):
        if settings is None:
            self.config.pop("settings", None)
        else:
            self.config["settings"] = settings
        return self.make_window()

    def test_saved_theme_is_applied_at_startup(self):
        window = self.window_with({"theme": "light"})
        self.assertEqual(window.theme, "light")
        self.assertIn(app.THEMES["light"]["window"], window.styleSheet())
        self.assertTrue(window.light_theme_action.isChecked())
        self.assertTrue(window.theme_switch.isChecked())
        self.assertEqual(window.theme_switch._position, 1.0, "no animation at startup")
        self.assertEqual(self.saved_configs, [], "startup must not rewrite the configuration")

    def test_invalid_values_fall_back_to_dark(self):
        for settings in (None, {}, {"theme": "pink"}, "not a dict"):
            with self.subTest(settings=settings):
                window = self.window_with(settings)
                self.assertEqual(window.theme, "dark")
                self.assertIn(app.THEMES["dark"]["window"], window.styleSheet())

    def test_switch_changes_and_saves_the_theme(self):
        window = self.window_with({"theme": "light"})
        window.theme_switch.click()
        self.assertEqual(window.theme, "dark")
        self.assertEqual(self.saved_configs[-1]["settings"]["theme"], "dark")
        self.assertFalse(window.light_theme_action.isChecked())
        self.assertTrue(self.wait(lambda: window.theme_switch._position == 0.0, 1), "knob animation")
        self.assertIn("light", window.theme_switch.toolTip())

    def test_menu_action_changes_the_theme_and_moves_the_switch(self):
        window = self.window_with({"theme": "dark"})
        window.light_theme_action.trigger()
        self.assertEqual(window.theme, "light")
        self.assertEqual(self.saved_configs[-1]["settings"]["theme"], "light")
        self.assertTrue(window.theme_switch.isChecked())

    def test_saving_the_theme_keeps_the_profiles(self):
        window = self.window_with({"theme": "dark"})
        window.theme_switch.click()
        self.assertEqual(self.saved_configs[-1]["profiles"][0]["name"], "Test")

    def test_theme_saved_even_if_settings_was_not_a_dict(self):
        window = self.window_with("not a dict")
        window.theme_switch.click()
        self.assertEqual(self.saved_configs[-1]["settings"], {"theme": "light"})

    def test_arrow_images_are_generated_per_theme(self):
        window = self.window_with({"theme": "dark"})
        window.theme_switch.click()
        names = sorted(path.name for path in Path(window._arrow_dir.path()).iterdir())
        colors = {app.THEMES[name]["arrow"].lstrip("#") for name in app.THEMES}
        self.assertEqual(names, sorted(f"arrow_{kind}_{color}.png" for kind in ("down", "up") for color in colors))


if __name__ == "__main__":
    unittest.main()
