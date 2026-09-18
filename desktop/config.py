"""User-local configuration; credentials are kept in memory only."""
import json
import os
from pathlib import Path


def user_directory():
    return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "EmpathyCopilot"


def read_settings(directory=None):
    path = (directory or user_directory()) / "settings.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings, directory=None):
    directory = directory or user_directory()
    directory.mkdir(parents=True, exist_ok=True)
    # Never persist an API key alongside plain-text preferences.
    allowed = {k: str(settings.get(k, "")) for k in ("data_path", "base_url", "model")}
    temporary = directory / "settings.tmp"
    temporary.write_text(json.dumps(allowed, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "settings.json")
