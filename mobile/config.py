import json
import os
from pathlib import Path


DEFAULT_SERVER_URL = os.getenv("API_URL", "http://localhost:8080").rstrip("/")


def _app_data_dir() -> Path:
    """Persistent app-data folder. Works on desktop and packaged mobile apps."""
    for var in ("FLET_APP_STORAGE_DATA", "FLET_APP_STORAGE_PATH"):
        value = os.getenv(var)
        if value:
            return Path(value)
    return Path.home() / ".tupedidojr"


def get_app_data_dir() -> Path:
    """Public accessor for the persistent app-data folder."""
    return _app_data_dir()


def _config_file() -> Path:
    return _app_data_dir() / "server.json"


def get_device_location() -> dict | None:
    """Location written by the native Flutter geolocation layer."""
    try:
        data = json.loads((_app_data_dir() / "location.json").read_text(encoding="utf-8"))
        if data.get("lat") is None or data.get("lng") is None:
            return None
        return data
    except (OSError, ValueError):
        return None


def get_fcm_token() -> str | None:
    """Token written by the native Flutter FCM layer, if available."""
    try:
        data = json.loads((_app_data_dir() / "fcm_token.json").read_text(encoding="utf-8"))
        token = (data.get("token") or "").strip()
        return token or None
    except (OSError, ValueError):
        return None


def get_server_url() -> str:
    env_url = os.getenv("API_URL")
    if env_url:
        return env_url.rstrip("/")
    try:
        data = json.loads(_config_file().read_text(encoding="utf-8"))
        url = (data.get("api_url") or "").strip()
        if url:
            return url.rstrip("/")
    except (OSError, ValueError):
        pass
    return DEFAULT_SERVER_URL


def save_server_url(url: str) -> str:
    clean = (url or "").strip().rstrip("/")
    if clean and not clean.startswith(("http://", "https://")):
        clean = "http://" + clean
    if not clean:
        clean = DEFAULT_SERVER_URL
    try:
        _app_data_dir().mkdir(parents=True, exist_ok=True)
        _config_file().write_text(json.dumps({"api_url": clean}), encoding="utf-8")
    except OSError:
        pass
    return clean


API_BASE_URL = get_server_url()
WS_BASE_URL = API_BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
