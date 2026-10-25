"""Opens the window at its minimum size and prints the squeezed fields as JSON.

Run by test_layout.py with the real Windows platform: the offscreen platform
used by the other tests has no real fonts and computes different sizes. The
window is fully transparent, so nothing appears on screen.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main_window  # noqa: E402
import profiles  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from theme import THEMES  # noqa: E402

FIELDS = ["name_edit", "url_edit", "destination_edit", "browse_button", "format_combo",
          "bitrate_combo", "threads_spin", "save_button", "start_button", "stop_button"]

profiles.save_config = lambda config: None
results = {}
qt = QApplication([])
for theme in THEMES:
    main_window.load_config = lambda theme=theme: {"version": 1, "settings": {"theme": theme}, "profiles": [{
        "id": "a", "name": "Test", "url": "https://open.spotify.com/playlist/x",
        "destination": "C:/Music/Test", "threads": 1}]}
    window = main_window.MainWindow()
    window.setWindowOpacity(0.0)
    window.show()
    window.resize(100, 100)  # the window stops at its minimum size
    for _ in range(20):
        qt.processEvents()
    results[theme] = {
        "width": window.width(),
        "squeezed": {
            name: [getattr(window, name).height(), getattr(window, name).minimumSizeHint().height()]
            for name in FIELDS
            if getattr(window, name).height() < getattr(window, name).minimumSizeHint().height()
        },
    }
    window.close()
print(json.dumps(results))
