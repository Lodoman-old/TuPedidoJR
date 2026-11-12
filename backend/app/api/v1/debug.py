"""Log de errores enviado por la app móvil para diagnóstico."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request, Response

router = APIRouter()
logger = logging.getLogger(__name__)

LOG_PATH = Path("/tmp/tupedidojr_client_errors.log")
MAX_BYTES = 2 * 1024 * 1024


@router.post("/client-log", status_code=204)
async def client_log(request: Request) -> Response:
    try:
        data = await request.json()
    except Exception:
        return Response(status_code=204)

    message = str(data.get("message") or "")[:4000]
    detail = str(data.get("detail") or "")[:8000]
    version = str(data.get("version") or "")[:40]
    route = str(data.get("route") or "")[:300]

    logger.warning("Error en la app [%s] %s: %s", version, route, message)

    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_BYTES:
            LOG_PATH.write_text("", encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{version}] route={route} {message}\n{detail}\n---\n")
    except Exception:
        logger.exception("No se pudo guardar el log del cliente")

    return Response(status_code=204)
