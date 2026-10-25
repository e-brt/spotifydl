"""Single source of the application version.

Used by the window title and About dialog, by build.ps1 for the executable's
file properties and the release archive name, and checked against
CHANGELOG.md by build.ps1. Follows Semantic Versioning (MAJOR.MINOR.PATCH).
"""

__version__ = "1.1.0"

if __name__ == "__main__":
    # `python src/version.py` prints the version, for build.ps1 and the workflow.
    print(__version__)
