"""TOTP (RFC 6238) sin dependencias externas."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import urllib.parse

DIGITS = 6
STEP = 30


def generate_secret(length: int = 20) -> str:
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode(secret: str) -> bytes:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded.upper())


def _hotp(secret: str, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_decode(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def totp(secret: str, at: float | None = None, step: int = STEP, digits: int = DIGITS) -> str:
    counter = int((time.time() if at is None else at) // step)
    return _hotp(secret, counter, digits)


def verify(
    secret: str,
    code: str,
    window: int = 1,
    step: int = STEP,
    digits: int = DIGITS,
) -> bool:
    if not secret:
        return False
    clean = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(clean) != digits:
        return False
    now = time.time()
    for offset in range(-window, window + 1):
        candidate = totp(secret, now + offset * step, step, digits)
        if hmac.compare_digest(candidate, clean):
            return True
    return False


def provisioning_uri(secret: str, email: str, issuer: str = "TuPedidoJR") -> str:
    label = urllib.parse.quote(f"{issuer}:{email}")
    query = urllib.parse.urlencode({
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": DIGITS,
        "period": STEP,
    })
    return f"otpauth://totp/{label}?{query}"


def generate_recovery_codes(count: int = 8) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_code(code: str) -> str:
    normalized = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def check_second_factor(user, code: str) -> tuple[bool, bool]:
    """Valida un código TOTP o de recuperación.

    Devuelve (válido, usó_código_de_recuperación). Cuando se usa un código de
    recuperación se descuenta del usuario; el llamador debe guardar el cambio.
    """
    if verify(user.totp_secret or "", code):
        return True, False
    hashed = hash_code(code)
    try:
        saved = json.loads(user.totp_recovery_codes or "[]")
    except (TypeError, ValueError):
        saved = []
    if hashed in saved:
        saved.remove(hashed)
        user.totp_recovery_codes = json.dumps(saved)
        return True, True
    return False, False
