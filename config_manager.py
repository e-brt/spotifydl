import json
import sys
import uuid
from pathlib import Path


CONFIG_FILENAME = "config.json"
# Folder next to the executable (or app.py) holding the user's files.
DATA_DIRNAME = "data"
# Files written at run time; earlier versions kept them next to the executable.
USER_FILES = ("config.json", "config.json.broken", "spotify_cache.json")
# spotDL's own defaults, so existing libraries are not downloaded again.
DEFAULT_FORMAT = "mp3"
DEFAULT_BITRATE = "128k"

_migrated = False


def app_dir():
    """Folder of the executable, or of app.py when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_dir():
    """Folder of the user's files (configuration, Spotify cache): data\\ next
    to the executable or source entry point."""
    global _migrated
    base = app_dir() / DATA_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    if not _migrated:
        _migrated = True
        migrate_user_files(app_dir(), base)
    return base


def migrate_user_files(old_dir, new_dir):
    """Move user files left next to the executable by an earlier version.

    A file already present in the new folder is kept, and the old one is
    then left untouched: nothing is ever overwritten or deleted.
    """
    for name in USER_FILES:
        old, new = Path(old_dir) / name, Path(new_dir) / name
        if old.is_file() and not new.exists():
            try:
                old.replace(new)
            except OSError:
                pass


def config_path():
    return config_dir() / CONFIG_FILENAME


def default_config():
    return {
        "version": 1,
        "settings": {"theme": "dark"},
        "profiles": [
            {
                "id": uuid.uuid4().hex[:12],
                "name": "My first playlist",
                "url": "",
                "destination": str(Path.home() / "Music"),
                "threads": 1,
                "format": DEFAULT_FORMAT,
                "bitrate": DEFAULT_BITRATE,
            }
        ],
    }


def load_config():
    path = config_path()

    if not path.exists():
        config = default_config()
        save_config(config)
        return config

    try:
        with path.open("r", encoding="utf-8") as file:
            config = json.load(file)

        if not isinstance(config, dict):
            raise ValueError("Configuration root must be a JSON object.")

        config.setdefault("settings", {"theme": "dark"})
        config.setdefault("profiles", [])

        for profile in config["profiles"]:
            profile.setdefault("id", uuid.uuid4().hex[:12])
            profile.setdefault("name", "Unnamed profile")
            profile.setdefault("url", "")
            profile.setdefault("destination", str(Path.home() / "Music"))
            profile.setdefault("threads", 1)
            profile.setdefault("format", DEFAULT_FORMAT)
            profile.setdefault("bitrate", DEFAULT_BITRATE)

        return config

    except (OSError, json.JSONDecodeError, ValueError):
        # Preserve the damaged configuration for manual recovery.
        broken_path = path.with_suffix(".json.broken")

        try:
            path.replace(broken_path)
        except OSError:
            pass

        config = default_config()
        save_config(config)
        return config


def save_config(config):
    path = config_path()
    temp_path = path.with_suffix(".json.tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)

    temp_path.replace(path)
