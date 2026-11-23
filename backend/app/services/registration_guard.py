"""Protección simple de formularios públicos de registro.

El límite vive en memoria del proceso. Con varios workers conviene moverlo a
Redis, pero para el volumen actual es suficiente y evita ráfagas de bots.
"""
from __future__ import annotations

import os
import time

from fastapi import HTTPException, Request

from app.core.config import settings
from app.services.security_service import client_ip

_WINDOW_SECONDS = 10 * 60
_MAX_PER_WINDOW = 20
_hits: dict[str, list[float]] = {}


def check_registration(request: Request) -> None:
    """Limita a 20 registros por IP cada 10 minutos en producción."""
    if settings.DEBUG or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    now = time.monotonic()
    ip = client_ip(request)
    recent = [moment for moment in _hits.get(ip, []) if now - moment < _WINDOW_SECONDS]
    if len(recent) >= _MAX_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail="Demasiados registros desde esta red. Intenta más tarde.",
        )
    recent.append(now)
    _hits[ip] = recent


def reject_honeypot(value: str | None) -> None:
    """Si el campo oculto viene lleno, es un bot."""
    if value and value.strip():
        raise HTTPException(status_code=400, detail="Solicitud inválida")
