"""Optional biometric unlock backed by secure storage."""
from __future__ import annotations

import flet as ft

try:
    from flet_local_auth import LocalAuthentication, LocalAuthException
    from flet_secure_storage import SecureStorage
except Exception:  # Desktop/web development without the mobile extensions.
    LocalAuthentication = None
    LocalAuthException = Exception
    SecureStorage = None


KEY_TOKEN = "tupedidojr_token"
KEY_EMAIL = "tupedidojr_email"
KEY_NAME = "tupedidojr_name"
KEY_BIOMETRIC = "tupedidojr_biometric"

auth = None
storage = None


def mobile_platform(page: ft.Page) -> bool:
    return page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)


async def init_services(page: ft.Page) -> None:
    global auth, storage
    if not mobile_platform(page) or LocalAuthentication is None or SecureStorage is None:
        return
    try:
        auth = LocalAuthentication()
        storage = SecureStorage()
        page.services.extend([auth, storage])
        page.update()
    except Exception:
        auth = None
        storage = None


async def biometric_available() -> bool:
    if auth is None:
        return False
    try:
        supported = await auth.is_device_supported()
        hardware = await auth.can_check_biometrics()
        return bool(supported and hardware)
    except Exception:
        return False


async def authenticate(reason: str = "Confirma tu identidad para entrar a TuPedidoJR") -> bool:
    if auth is None:
        return False
    try:
        return bool(await auth.authenticate(reason, biometric_only=False))
    except LocalAuthException:
        return False
    except Exception:
        return False


async def save_session(token: str, email: str = "", name: str = "") -> None:
    if storage is None:
        return
    try:
        await storage.set(KEY_TOKEN, token)
        await storage.set(KEY_EMAIL, email or "")
        await storage.set(KEY_NAME, name or "")
    except Exception:
        pass


async def load_session() -> dict:
    if storage is None:
        return {}
    try:
        token = await storage.get(KEY_TOKEN)
        if not token:
            return {}
        return {
            "token": token,
            "email": await storage.get(KEY_EMAIL) or "",
            "name": await storage.get(KEY_NAME) or "",
            "biometric": (await storage.get(KEY_BIOMETRIC)) == "true",
        }
    except Exception:
        return {}


async def set_biometric(enabled: bool) -> None:
    if storage is None:
        return
    try:
        await storage.set(KEY_BIOMETRIC, "true" if enabled else "false")
    except Exception:
        pass


async def is_biometric_enabled() -> bool:
    if storage is None:
        return False
    try:
        return (await storage.get(KEY_BIOMETRIC)) == "true"
    except Exception:
        return False


async def clear_session() -> None:
    if storage is None:
        return
    try:
        await storage.clear()
    except Exception:
        pass
