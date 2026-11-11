"""Control file for the Android background location service."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from mobile.api import api
from mobile.config import get_app_data_dir, get_server_url


def _control_file():
    return get_app_data_dir() / "background_location.json"


def set_enabled(enabled: bool) -> None:
    data = {
        "enabled": bool(enabled),
        "api_url": get_server_url(),
        "token": api.token or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _control_file().parent.mkdir(parents=True, exist_ok=True)
        _control_file().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def configure_from_profile(profile: dict | None) -> None:
    if not profile:
        set_enabled(False)
        return
    enabled = bool(profile.get("is_available")) or bool(profile.get("current_order_id"))
    set_enabled(enabled)
