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
    allowed = {k: str(settings.get(k, "")) for k in ("data_path", "base_url", "model", "env_path")}
    temporary = directory / "settings.tmp"
    temporary.write_text(json.dumps(allowed, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "settings.json")


def load_model_settings(settings, environ=None):
    """Reload the explicitly selected env file; never copy its key to preferences."""
    from dotenv import dotenv_values
    values = {}
    if settings.get('env_path'):
        try:
            values = dotenv_values(settings['env_path'], interpolate=False)
        except (OSError, ValueError, UnicodeError):
            pass
    environ = os.environ if environ is None else environ
    result = dict(settings)
    for field, name in (('base_url', 'LLM_BASE_URL'), ('model', 'LLM_MODEL')):
        value = environ.get(name) or values.get(name)
        if value:
            result[field] = value.strip()
    key = environ.get('LLM_API_KEY') or values.get('LLM_API_KEY') or ''
    return result, key.strip()
