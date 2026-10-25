import json
import sys
import uuid
from pathlib import Path


CONFIG_FILENAME = "config.json"
# spotDL's own defaults, so existing libraries are not downloaded again.
DEFAULT_FORMAT = "mp3"
DEFAULT_BITRATE = "128k"


def config_dir():
    """Store the configuration next to the executable or source entry point."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent

    base.mkdir(parents=True, exist_ok=True)
    return base


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
