"""Window layout at its minimum size."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import app
from helpers import ROOT  # noqa: F401  (puts the project on sys.path)

PROBE = Path(__file__).with_name("min_size_probe.py")


@unittest.skipUnless(sys.platform == "win32", "measured with the real Windows platform")
class MinimumSizeTests(unittest.TestCase):

    def test_no_field_is_squeezed_at_the_minimum_size(self):
        # A separate process with the real platform: the offscreen platform
        # used by the other tests has no real fonts and other sizes.
        env = dict(os.environ, QT_QPA_PLATFORM="windows")
        result = subprocess.run([sys.executable, str(PROBE)], capture_output=True, text=True,
                                timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        measures = json.loads(result.stdout.strip().splitlines()[-1])
        for theme, measure in measures.items():
            with self.subTest(theme=theme):
                self.assertGreaterEqual(measure["width"], app.MIN_WINDOW_WIDTH)
                self.assertEqual(measure["squeezed"], {}, "field: [height, needed height]")


if __name__ == "__main__":
    unittest.main()
