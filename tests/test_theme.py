"""Light theme and theme switch (SPECIFICATION.md, section 8)."""

import unittest
from pathlib import Path

from helpers import AppTestCase

import theme


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
        self.assertIn(theme.THEMES["light"]["window"], window.styleSheet())
        self.assert_menu_checked(window, "light")
        self.assertTrue(window.theme_switch.isChecked())
        self.assertEqual(window.theme_switch._position, 1.0, "no animation at startup")
        self.assertEqual(self.saved_configs, [], "startup must not rewrite the configuration")

    def test_invalid_values_fall_back_to_dark(self):
        for settings in (None, {}, {"theme": "pink"}, "not a dict"):
            with self.subTest(settings=settings):
                window = self.window_with(settings)
                self.assertEqual(window.theme, "dark")
                self.assertIn(theme.THEMES["dark"]["window"], window.styleSheet())
                self.assert_menu_checked(window, "dark")

    def test_switch_changes_and_saves_the_theme(self):
        window = self.window_with({"theme": "light"})
        window.theme_switch.click()
        self.assertEqual(window.theme, "dark")
        self.assertEqual(self.saved_configs[-1]["settings"]["theme"], "dark")
        self.assert_menu_checked(window, "dark")
        self.assertTrue(self.wait(lambda: window.theme_switch._position == 0.0, 1), "knob animation")
        self.assertIn("light", window.theme_switch.toolTip())

    def test_menu_actions_change_the_theme_and_move_the_switch(self):
        window = self.window_with({"theme": "dark"})
        window.theme_actions["light"].trigger()
        self.assertEqual(window.theme, "light")
        self.assertEqual(self.saved_configs[-1]["settings"]["theme"], "light")
        self.assert_menu_checked(window, "light")
        self.assertTrue(window.theme_switch.isChecked())
        window.theme_actions["dark"].trigger()
        self.assertEqual(window.theme, "dark")
        self.assertEqual(self.saved_configs[-1]["settings"]["theme"], "dark")
        self.assert_menu_checked(window, "dark")
        self.assertFalse(window.theme_switch.isChecked())

    def test_choosing_the_current_theme_keeps_it_checked(self):
        window = self.window_with({"theme": "dark"})
        window.theme_actions["dark"].trigger()
        self.assertEqual(window.theme, "dark")
        self.assert_menu_checked(window, "dark")

    def assert_menu_checked(self, window, name):
        """Exactly one Theme menu entry is checked: the given one."""
        checked = [theme for theme, action in window.theme_actions.items() if action.isChecked()]
        self.assertEqual(checked, [name])

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
        colors = {theme.THEMES[name]["arrow"].lstrip("#") for name in theme.THEMES}
        self.assertEqual(names, sorted(f"arrow_{kind}_{color}.png" for kind in ("down", "up") for color in colors))


if __name__ == "__main__":
    unittest.main()
