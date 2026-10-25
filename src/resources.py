"""Paths of the files bundled with the application."""

import sys
from pathlib import Path


def resource_path(*parts):
    """Path of a bundled file: in the PyInstaller bundle, or in the project
    folder (the parent of src\\) when running from source."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)
