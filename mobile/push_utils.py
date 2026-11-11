import asyncio

from mobile.api import api
from mobile.config import get_fcm_token


_last_registered_token: str | None = None


async def register_device_token(force: bool = False, attempts: int = 6, delay: float = 3.0) -> bool:
    """Register the native FCM token once the Flutter layer has written it.

    The Dart side writes ``fcm_token.json`` into the app data directory during
    startup, so on a cold start the file may appear a few seconds later.
    """
    global _last_registered_token
    for _ in range(attempts):
        token = get_fcm_token()
        if token and api.token and (force or token != _last_registered_token):
            try:
                await api.register_push_token(token, "android", "Android app")
                _last_registered_token = token
                return True
            except Exception:
                pass
        await asyncio.sleep(delay)
    return False


async def watch_device_token():
    """Registra tokens que llegan tarde o cambian mientras la app está abierta."""
    global _last_registered_token
    while True:
        await asyncio.sleep(20)
        if not api.token:
            continue
        token = get_fcm_token()
        if token and token != _last_registered_token:
            try:
                await api.register_push_token(token, "android", "Android app")
                _last_registered_token = token
            except Exception:
                pass
