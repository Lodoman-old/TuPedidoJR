import asyncio

from mobile.api import api
from mobile.config import get_fcm_token


async def register_device_token(attempts: int = 6, delay: float = 3.0) -> bool:
    """Register the native FCM token once the Flutter layer has written it.

    The Dart side writes ``fcm_token.json`` into the app data directory during
    startup, so on a cold start the file may appear a few seconds later.
    """
    for _ in range(attempts):
        token = get_fcm_token()
        if token and api.token:
            try:
                await api.register_push_token(token, "android", "Android app")
                return True
            except Exception:
                pass
        await asyncio.sleep(delay)
    return False
